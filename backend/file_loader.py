import pdfplumber
from typing import List
import nltk
from nltk.tokenize import sent_tokenize, blankline_tokenize
import os

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
        print(f"Error loading PDF: {e}")
        return text.replace('\x00', '')
    # Log si aucun texte extrait
    if not text.strip():
        print(f"Warning: No text extracted from PDF {path}")
    return text.replace('\x00', '')

def chunk_text(text: str, chunk_size: int = 2000, overlap: int = 200, chunk_type: str = "auto") -> List[str]:
    """
    Découpe le texte en chunks logiques : paragraphes, phrases, ou taille fixe.
    chunk_type: "paragraph", "sentence", "auto" (par défaut : auto)
    """

    import logging
    logger = logging.getLogger("file_loader")
    chunks = []
    try:
        if chunk_type == "paragraph":
            text = text.replace('\x00', '')
            chunks = []
            try:
                paragraphs = [p for p in blankline_tokenize(text) if p.strip()]
            except Exception as e:
                logger.error(f"NLTK blankline_tokenize failed: {e}")
                paragraphs = [text]
            for p in paragraphs:
                if len(p) > chunk_size:
                    try:
                        sentences = sent_tokenize(p)
                    except Exception as e:
                        logger.error(f"NLTK sent_tokenize failed: {e}")
                        sentences = [p]
                    current = ""
                    for s in sentences:
                        if len(current) + len(s) < chunk_size:
                            current += " " + s
                        else:
                            chunks.append(current.strip())
                            current = s
                    if current:
                        chunks.append(current.strip())
                else:
                    chunks.append(p.strip())
        elif chunk_type == "sentence":
            try:
                sentences = sent_tokenize(text)
            except Exception as e:
                logger.error(f"NLTK sent_tokenize failed: {e}")
                sentences = [text]
            current = ""
            for s in sentences:
                if len(current) + len(s) < chunk_size:
                    current += " " + s
                else:
                    chunks.append(current.strip())
                    current = s
            if current:
                chunks.append(current.strip())
        else:  # auto
            # Si le texte contient beaucoup de retours à la ligne, découpe en paragraphes
            if text.count('\n') > 10:
                return chunk_text(text, chunk_size, overlap, chunk_type="paragraph")
            else:
                return chunk_text(text, chunk_size, overlap, chunk_type="sentence")
    except Exception as e:
        logger.error(f"Error during chunking: {e}")
        chunks = [text]
    # Ajoute l'overlap
    final_chunks = []
    for i, chunk in enumerate(chunks):
        if i == 0:
            final_chunks.append(chunk)
        else:
            prev = final_chunks[-1]
            overlap_text = prev[-overlap:] if len(prev) > overlap else prev
            final_chunks.append(overlap_text + " " + chunk)
    result_chunks = [c.strip() for c in final_chunks if c.strip()]
    logger.info(f"chunk_text produced {len(result_chunks)} chunks.")
    return result_chunks
