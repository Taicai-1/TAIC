import pdfplumber
import re
import logging
from typing import List
import nltk
from nltk.tokenize import sent_tokenize
import os
import tiktoken

logger = logging.getLogger("file_loader")

# Patch NLTK pour rediriger 'punkt_tab' vers 'punkt'
import nltk.data
_original_find = nltk.data.find
def patched_find(resource_name, paths=None):
    if 'punkt_tab' in resource_name:
        resource_name = resource_name.replace('punkt_tab', 'punkt')
    return _original_find(resource_name, paths)
nltk.data.find = patched_find

# Setup robust NLTK punkt for Cloud Run
NLTK_DATA_PATH = '/tmp/nltk_data'
os.makedirs(NLTK_DATA_PATH, exist_ok=True)
if NLTK_DATA_PATH not in nltk.data.path:
    nltk.data.path.append(NLTK_DATA_PATH)
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt', download_dir=NLTK_DATA_PATH)

# Token encoder for chunk sizing (cl100k_base is a good general approximation)
_enc = tiktoken.get_encoding("cl100k_base")


def _count_tokens(text: str) -> int:
    """Count tokens using tiktoken."""
    return len(_enc.encode(text))


def load_text_from_pdf(path: str) -> str:
    """Load text from PDF file"""
    text = ""
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception as e:
        logger.error(f"Error loading PDF: {e}")
        return text.replace('\x00', '')
    if not text.strip():
        logger.warning(f"No text extracted from PDF {path}")
    return text.replace('\x00', '')


# ---------------------------------------------------------------------------
# Hybrid chunking: clean → recursive split → sentence-boundary overlap
# ---------------------------------------------------------------------------

def _clean_text(text: str) -> str:
    """Clean raw text before chunking: remove artifacts, normalize whitespace."""
    text = text.replace('\x00', '')
    text = text.replace('\r\n', '\n').replace('\r', '\n')

    # Detect and remove repeated headers/footers (lines appearing 3+ times)
    lines = text.split('\n')
    line_counts: dict = {}
    for line in lines:
        stripped = line.strip()
        if stripped and len(stripped) > 5:
            line_counts[stripped] = line_counts.get(stripped, 0) + 1
    repeated = {line for line, count in line_counts.items() if count >= 3}
    if repeated:
        lines = [l for l in lines if l.strip() not in repeated]
        text = '\n'.join(lines)

    # Collapse 3+ consecutive newlines into 2
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Collapse multiple spaces into one
    text = re.sub(r' {2,}', ' ', text)
    return text.strip()


def _recursive_split(text: str, max_tokens: int, separators: List[str]) -> List[str]:
    """Recursively split text using a hierarchy of separators.

    Tries the first separator; if any resulting piece is still too large,
    falls back to the next separator, and so on.
    Last resort: hard split by tokens.
    """
    if _count_tokens(text) <= max_tokens:
        return [text]

    if not separators:
        # Hard split by tokens as last resort
        tokens = _enc.encode(text)
        chunks = []
        for i in range(0, len(tokens), max_tokens):
            chunks.append(_enc.decode(tokens[i:i + max_tokens]))
        return chunks

    sep = separators[0]
    remaining_seps = separators[1:]

    parts = text.split(sep)
    chunks: List[str] = []
    current = ""

    for part in parts:
        candidate = current + sep + part if current else part
        if _count_tokens(candidate) <= max_tokens:
            current = candidate
        else:
            if current:
                chunks.append(current)
            # If this single part is still too big, split it with next separator
            if _count_tokens(part) > max_tokens:
                sub_chunks = _recursive_split(part, max_tokens, remaining_seps)
                chunks.extend(sub_chunks)
                current = ""
            else:
                current = part

    if current:
        chunks.append(current)

    return chunks


def _sentence_overlap(chunk: str, max_overlap_tokens: int) -> str:
    """Extract the last complete sentences from a chunk for overlap context."""
    try:
        sentences = sent_tokenize(chunk)
    except Exception:
        # Fallback: take last N characters roughly equal to max_overlap_tokens * 4
        tail = chunk[-(max_overlap_tokens * 4):]
        # Try to start at a word boundary
        space_idx = tail.find(' ')
        return tail[space_idx + 1:] if space_idx != -1 else tail

    overlap_sentences: List[str] = []
    token_count = 0
    for s in reversed(sentences):
        s_tokens = _count_tokens(s)
        if token_count + s_tokens > max_overlap_tokens:
            break
        overlap_sentences.insert(0, s)
        token_count += s_tokens

    return ' '.join(overlap_sentences) if overlap_sentences else ''


def chunk_text(text: str, chunk_size: int = 512, overlap: int = 50, **kwargs) -> List[str]:
    """Hybrid chunking: recursive splitting + PDF cleanup + sentence-boundary overlap.

    Args:
        text: Raw text to chunk.
        chunk_size: Target chunk size in tokens (default 512, good for embedding models).
        overlap: Overlap between chunks in tokens using complete sentences (default 50).

    Returns:
        List of text chunks ready for embedding.
    """
    if not text or not text.strip():
        return []

    # Step 1: Clean text (remove PDF artifacts, normalize whitespace)
    text = _clean_text(text)
    if not text:
        return []

    # Step 2: Recursive split with separator hierarchy
    # \n\n = paragraphs, \n = lines, ". " = sentences, " " = words
    separators = ['\n\n', '\n', '. ', ' ']
    raw_chunks = _recursive_split(text, chunk_size, separators)

    # Step 3: Add sentence-boundary overlap (complete sentences, not cut characters)
    final_chunks: List[str] = []
    for i, chunk in enumerate(raw_chunks):
        chunk = chunk.strip()
        if not chunk:
            continue
        if i > 0 and overlap > 0:
            overlap_text = _sentence_overlap(raw_chunks[i - 1], overlap)
            if overlap_text:
                chunk = overlap_text + "\n" + chunk
        final_chunks.append(chunk)

    logger.info(f"chunk_text: {len(final_chunks)} chunks ({chunk_size} tokens target, {overlap} tokens overlap)")
    return final_chunks
