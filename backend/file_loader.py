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
    if "punkt_tab" in resource_name:
        resource_name = resource_name.replace("punkt_tab", "punkt")
    return _original_find(resource_name, paths)


nltk.data.find = patched_find

# Setup robust NLTK punkt for Cloud Run
NLTK_DATA_PATH = "/tmp/nltk_data"
os.makedirs(NLTK_DATA_PATH, exist_ok=True)
if NLTK_DATA_PATH not in nltk.data.path:
    nltk.data.path.append(NLTK_DATA_PATH)
try:
    nltk.data.find("tokenizers/punkt")
except LookupError:
    nltk.download("punkt", download_dir=NLTK_DATA_PATH)

# Token encoder for chunk sizing (cl100k_base is a good general approximation)
_enc = tiktoken.get_encoding("cl100k_base")


def _count_tokens(text: str) -> int:
    """Count tokens using tiktoken."""
    return len(_enc.encode(text))


def load_text_from_pdf(path: str, progress_callback=None) -> str:
    """Load text from PDF file, with optional page-level progress reporting."""
    text = ""
    try:
        with pdfplumber.open(path) as pdf:
            total_pages = len(pdf.pages)
            for page_num, page in enumerate(pdf.pages):
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
                if progress_callback and total_pages > 0:
                    # Extraction spans 15-28% in the overall pipeline
                    pct = 15 + int(((page_num + 1) / total_pages) * 13)
                    progress_callback("extracting", pct, page_num + 1, total_pages)
    except Exception as e:
        logger.error(f"Error loading PDF: {e}", exc_info=True)
        return text.replace("\x00", "")
    if not text.strip():
        logger.warning(f"No text extracted from PDF {path}")
    return text.replace("\x00", "")


# ---------------------------------------------------------------------------
# Hybrid chunking: clean → recursive split → sentence-boundary overlap
# ---------------------------------------------------------------------------


def _clean_text(text: str) -> str:
    """Clean raw text before chunking: remove artifacts, normalize whitespace."""
    text = text.replace("\x00", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Detect and remove repeated headers/footers (lines appearing 3+ times)
    lines = text.split("\n")
    line_counts: dict = {}
    for line in lines:
        stripped = line.strip()
        if stripped and len(stripped) > 5:
            line_counts[stripped] = line_counts.get(stripped, 0) + 1
    repeated = {line for line, count in line_counts.items() if count >= 3}
    if repeated:
        lines = [l for l in lines if l.strip() not in repeated]
        text = "\n".join(lines)

    # Collapse 3+ consecutive newlines into 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Collapse multiple spaces into one
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


def _sentence_split(text: str, max_tokens: int) -> List[str]:
    """Split text into chunks of complete sentences.

    Uses NLTK sent_tokenize for accurate sentence detection, then groups
    sentences together up to max_tokens. Ensures chunks always start and
    end at sentence boundaries for readability.

    Hierarchy: paragraphs → sentences → hard token split (last resort).
    """
    if _count_tokens(text) <= max_tokens:
        return [text]

    # Split into paragraphs first to preserve structure
    paragraphs = text.split("\n\n")

    # Collect all sentences with paragraph break markers
    all_sentences: List[str] = []
    for i, para in enumerate(paragraphs):
        para = para.strip()
        if not para:
            continue
        try:
            sentences = sent_tokenize(para)
        except Exception:
            # Fallback: split on ". " then " " for very broken text
            sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', para) if s.strip()]
            if not sentences:
                sentences = [para]
        for sent in sentences:
            sent = sent.strip()
            if sent:
                all_sentences.append(sent)
        # Add paragraph break marker between paragraphs (not after last)
        if i < len(paragraphs) - 1:
            all_sentences.append("\n\n")

    # Group sentences into chunks respecting max_tokens
    chunks: List[str] = []
    current_parts: List[str] = []
    current_tokens = 0

    for sent in all_sentences:
        if sent == "\n\n":
            # Paragraph break: add to current group if it fits
            if current_parts:
                current_parts.append(sent)
            continue

        sent_tokens = _count_tokens(sent)

        # Single sentence exceeds max_tokens → hard split by tokens
        if sent_tokens > max_tokens:
            if current_parts:
                chunk_text_val = _join_parts(current_parts)
                if chunk_text_val.strip():
                    chunks.append(chunk_text_val.strip())
                current_parts = []
                current_tokens = 0
            tokens = _enc.encode(sent)
            for j in range(0, len(tokens), max_tokens):
                chunks.append(_enc.decode(tokens[j : j + max_tokens]))
            continue

        # Would adding this sentence exceed the limit?
        if current_tokens + sent_tokens > max_tokens and current_parts:
            chunk_text_val = _join_parts(current_parts)
            if chunk_text_val.strip():
                chunks.append(chunk_text_val.strip())
            current_parts = []
            current_tokens = 0

        current_parts.append(sent)
        current_tokens += sent_tokens

    # Flush remaining
    if current_parts:
        chunk_text_val = _join_parts(current_parts)
        if chunk_text_val.strip():
            chunks.append(chunk_text_val.strip())

    return chunks


def _join_parts(parts: List[str]) -> str:
    """Join sentence parts, using spaces between sentences and preserving paragraph breaks."""
    result = []
    for part in parts:
        if part == "\n\n":
            result.append("\n\n")
        else:
            if result and result[-1] != "\n\n":
                result.append(" ")
            result.append(part)
    return "".join(result)


def _sentence_overlap(chunk: str, max_overlap_tokens: int) -> str:
    """Extract the last complete sentences from a chunk for overlap context."""
    try:
        sentences = sent_tokenize(chunk)
    except Exception:
        # Fallback: take last N characters roughly equal to max_overlap_tokens * 4
        tail = chunk[-(max_overlap_tokens * 4) :]
        # Try to start at a word boundary
        space_idx = tail.find(" ")
        return tail[space_idx + 1 :] if space_idx != -1 else tail

    overlap_sentences: List[str] = []
    token_count = 0
    for s in reversed(sentences):
        s_tokens = _count_tokens(s)
        if token_count + s_tokens > max_overlap_tokens:
            break
        overlap_sentences.insert(0, s)
        token_count += s_tokens

    return " ".join(overlap_sentences) if overlap_sentences else ""


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

    # Step 2: Sentence-aware split (paragraphs → sentences → hard token split)
    raw_chunks = _sentence_split(text, chunk_size)

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
