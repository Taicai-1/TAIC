"""
Input Validation & Sanitization

This module provides validation and sanitization utilities for user inputs
to prevent security vulnerabilities and ensure data integrity.

Security considerations:
- Prevent XSS attacks (remove/escape HTML/JS)
- Prevent SQL injection (validate types, lengths)
- Prevent path traversal (sanitize filenames)
- Prevent buffer overflow (enforce length limits)
"""

import re
from typing import Optional
from pydantic import BaseModel, Field, validator
from fastapi import HTTPException


# ============================================================================
# VALIDATION CONSTANTS
# ============================================================================

# Length limits
MAX_USERNAME_LENGTH = 50
MAX_EMAIL_LENGTH = 100
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128

MAX_AGENT_NAME_LENGTH = 200
MAX_AGENT_CONTEXTE_LENGTH = 10000
MAX_AGENT_BIOGRAPHIE_LENGTH = 5000

MAX_MESSAGE_LENGTH = 10000
MAX_CONVERSATION_TITLE_LENGTH = 255

MAX_TEAM_NAME_LENGTH = 200
MAX_TEAM_CONTEXTE_LENGTH = 10000

MAX_URL_LENGTH = 2048

# File upload limits
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
ALLOWED_FILE_EXTENSIONS = {
    'pdf', 'txt', 'docx', 'doc', 'pptx', 'ppt',
    'xlsx', 'xls', 'csv', 'md', 'html', 'htm'
}

# Regex patterns
EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
URL_REGEX = re.compile(
    r'^https?://'  # http:// or https://
    r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain
    r'localhost|'  # localhost
    r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # or IP
    r'(?::\d+)?'  # optional port
    r'(?:/?|[/?]\S+)$', re.IGNORECASE
)

# Dangerous patterns to remove
SCRIPT_PATTERN = re.compile(r'<script[^>]*>.*?</script>', re.IGNORECASE | re.DOTALL)
HTML_TAG_PATTERN = re.compile(r'<[^>]+>')
SQL_INJECTION_PATTERNS = [
    re.compile(r"(\bOR\b.*?=.*?|\bAND\b.*?=.*?)", re.IGNORECASE),
    re.compile(r"(UNION.*SELECT|DROP.*TABLE|INSERT.*INTO|DELETE.*FROM)", re.IGNORECASE),
]


# ============================================================================
# SANITIZATION FUNCTIONS
# ============================================================================

def sanitize_html(text: str) -> str:
    """
    Remove HTML/script tags from user input to prevent XSS.

    Security: Prevents stored XSS attacks by stripping script and HTML tags.
    Safe characters (quotes, apostrophes, &) are preserved — the frontend
    (React) auto-escapes all rendered strings, so entity encoding here
    would only corrupt legitimate content like "C'est quoi ?".
    """
    if not text:
        return text

    # Remove script tags first (most dangerous)
    text = SCRIPT_PATTERN.sub('', text)

    # Remove all HTML tags
    text = HTML_TAG_PATTERN.sub('', text)

    return text


def sanitize_filename(filename: str) -> str:
    """
    Sanitize filename to prevent path traversal attacks.

    Security: Prevents directory traversal attacks like ../../../etc/passwd
    """
    if not filename:
        return filename

    # Remove path separators and dangerous characters
    filename = filename.replace('\\', '_').replace('/', '_')
    filename = filename.replace('..', '_')

    # Remove null bytes
    filename = filename.replace('\x00', '')

    # Keep only safe characters (alphanumeric, dash, underscore, dot)
    filename = re.sub(r'[^a-zA-Z0-9._-]', '_', filename)

    # Limit length
    if len(filename) > 255:
        # Keep extension
        name, ext = filename.rsplit('.', 1) if '.' in filename else (filename, '')
        filename = name[:250] + ('.' + ext if ext else '')

    return filename


def sanitize_text(text: str, max_length: Optional[int] = None) -> str:
    """
    General text sanitization: remove control characters, normalize whitespace.

    Security: Prevents null byte injection and control character attacks.
    """
    if not text:
        return text

    # Remove null bytes
    text = text.replace('\x00', '')

    # Remove other control characters (except newline, tab, carriage return)
    text = ''.join(char for char in text if ord(char) >= 32 or char in '\n\r\t')

    # Normalize whitespace (collapse multiple spaces)
    text = re.sub(r'[ \t]+', ' ', text)

    # Trim
    text = text.strip()

    # Enforce max length
    if max_length and len(text) > max_length:
        text = text[:max_length]

    return text


def check_sql_injection_attempt(text: str) -> bool:
    """
    Check if text contains SQL injection patterns.

    Returns True if suspicious patterns detected (for logging/blocking).
    """
    if not text:
        return False

    for pattern in SQL_INJECTION_PATTERNS:
        if pattern.search(text):
            return True

    return False


def validate_file_extension(filename: str) -> bool:
    """
    Validate file extension against whitelist.

    Security: Prevent upload of executable files or scripts.
    """
    if not filename or '.' not in filename:
        return False

    ext = filename.rsplit('.', 1)[1].lower()
    return ext in ALLOWED_FILE_EXTENSIONS


# Magic bytes signatures for allowed file types
FILE_SIGNATURES = {
    'pdf': [b'%PDF'],
    'docx': [b'PK\x03\x04'],  # ZIP-based (OOXML)
    'doc': [b'\xd0\xcf\x11\xe0'],  # OLE2
    'pptx': [b'PK\x03\x04'],
    'ppt': [b'\xd0\xcf\x11\xe0'],
    'xlsx': [b'PK\x03\x04'],
    'xls': [b'\xd0\xcf\x11\xe0'],
}


def validate_file_content(content: bytes, filename: str) -> bool:
    """
    Validate file content matches its extension by checking magic bytes.

    Security: Prevents upload of disguised malicious files (e.g. exe renamed to .pdf).
    Text-based formats (txt, csv, md, html) are always allowed.
    """
    if not filename or '.' not in filename:
        return False

    ext = filename.rsplit('.', 1)[1].lower()

    # Text-based formats: no magic bytes to check
    if ext in {'txt', 'csv', 'md', 'html', 'htm'}:
        return True

    # Check magic bytes for binary formats
    signatures = FILE_SIGNATURES.get(ext)
    if not signatures:
        return True  # Unknown format, let extension check handle it

    for sig in signatures:
        if content[:len(sig)] == sig:
            return True

    return False


def validate_file_size(size_bytes: int) -> bool:
    """
    Validate file size is within limits.

    Security: Prevent DoS attacks via large file uploads.
    """
    return 0 < size_bytes <= MAX_FILE_SIZE


# ============================================================================
# ENHANCED PYDANTIC MODELS WITH VALIDATION
# ============================================================================

class UserCreateValidated(BaseModel):
    """User registration with validation"""
    username: str = Field(..., min_length=3, max_length=MAX_USERNAME_LENGTH)
    email: str = Field(..., min_length=3, max_length=MAX_EMAIL_LENGTH)
    password: str = Field(..., min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
    invite_code: Optional[str] = Field(None, max_length=32)

    @validator('email')
    def validate_email(cls, v):
        if not EMAIL_REGEX.match(v):
            raise ValueError('Invalid email format')
        return v.lower()

    @validator('username')
    def validate_username(cls, v):
        # Only alphanumeric, dash, underscore
        if not re.match(r'^[a-zA-Z0-9_-]+$', v):
            raise ValueError('Username can only contain letters, numbers, dash, and underscore')
        return sanitize_text(v, MAX_USERNAME_LENGTH)

    @validator('password')
    def validate_password_strength(cls, v):
        # Require at least: 1 uppercase, 1 lowercase, 1 digit
        if not re.search(r'[A-Z]', v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not re.search(r'[a-z]', v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not re.search(r'[0-9]', v):
            raise ValueError('Password must contain at least one digit')
        return v


class ChangePasswordRequest(BaseModel):
    """Password change request with validation"""
    current_password: str = Field(..., min_length=1, max_length=MAX_PASSWORD_LENGTH)
    new_password: str = Field(..., min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)

    @validator('new_password')
    def validate_password_strength(cls, v):
        if not re.search(r'[A-Z]', v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not re.search(r'[a-z]', v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not re.search(r'[0-9]', v):
            raise ValueError('Password must contain at least one digit')
        return v


class AgentCreateValidated(BaseModel):
    """Agent creation with validation"""
    name: str = Field(..., min_length=1, max_length=MAX_AGENT_NAME_LENGTH)
    contexte: Optional[str] = Field(None, max_length=MAX_AGENT_CONTEXTE_LENGTH)
    biographie: Optional[str] = Field(None, max_length=MAX_AGENT_BIOGRAPHIE_LENGTH)
    profile_photo: Optional[str] = Field(None, max_length=MAX_URL_LENGTH)
    statut: Optional[str] = Field('public', pattern='^(public|private)$')
    type: Optional[str] = Field('conversationnel', pattern='^(conversationnel|recherche_live)$')

    @validator('name')
    def validate_name(cls, v):
        v = sanitize_text(v, MAX_AGENT_NAME_LENGTH)
        if not v:
            raise ValueError('Agent name cannot be empty')
        return v

    @validator('contexte', 'biographie')
    def sanitize_markdown(cls, v):
        if not v:
            return v
        # Remove scripts but allow basic HTML (for markdown rendering)
        v = SCRIPT_PATTERN.sub('', v)
        # Check for SQL injection attempts
        if check_sql_injection_attempt(v):
            raise ValueError('Invalid content detected')
        return sanitize_text(v)

    @validator('profile_photo')
    def validate_url(cls, v):
        if not v:
            return v
        if not URL_REGEX.match(v):
            raise ValueError('Invalid URL format')
        return v


class MessageCreateValidated(BaseModel):
    """Message creation with validation"""
    conversation_id: int = Field(..., gt=0)
    role: str = Field(..., pattern='^(user|assistant|system)$')
    content: str = Field(..., min_length=1, max_length=MAX_MESSAGE_LENGTH)

    @validator('content')
    def sanitize_content(cls, v):
        v = sanitize_html(v)
        v = sanitize_text(v, MAX_MESSAGE_LENGTH)
        if not v:
            raise ValueError('Message content cannot be empty')
        # Check for SQL injection attempts
        if check_sql_injection_attempt(v):
            raise ValueError('Invalid content detected')
        return v


class QuestionRequestValidated(BaseModel):
    """Question request with validation"""
    question: str = Field(..., min_length=1, max_length=MAX_MESSAGE_LENGTH)
    selected_documents: list[int] = Field(default_factory=list)
    agent_id: Optional[int] = Field(None, gt=0)
    team_id: Optional[int] = Field(None, gt=0)
    conversation_id: Optional[int] = Field(None, gt=0)
    history: Optional[list] = None

    @validator('question')
    def sanitize_question(cls, v):
        v = sanitize_html(v)
        v = sanitize_text(v, MAX_MESSAGE_LENGTH)
        if not v:
            raise ValueError('Question cannot be empty')
        return v

    @validator('selected_documents')
    def validate_document_ids(cls, v):
        # Ensure all IDs are positive integers
        if not all(isinstance(doc_id, int) and doc_id > 0 for doc_id in v):
            raise ValueError('Invalid document IDs')
        # Limit number of documents
        if len(v) > 100:
            raise ValueError('Too many documents selected (max 100)')
        return v


class ConversationTitleValidated(BaseModel):
    """Conversation title with validation"""
    title: str = Field(..., min_length=1, max_length=MAX_CONVERSATION_TITLE_LENGTH)

    @validator('title')
    def sanitize_title(cls, v):
        v = sanitize_html(v)
        v = sanitize_text(v, MAX_CONVERSATION_TITLE_LENGTH)
        if not v:
            raise ValueError('Title cannot be empty')
        return v


class UrlUploadValidated(BaseModel):
    """URL upload with validation"""
    url: str = Field(..., min_length=1, max_length=MAX_URL_LENGTH)
    agent_id: Optional[int] = Field(None, gt=0)

    @validator('url')
    def validate_url(cls, v):
        if not URL_REGEX.match(v):
            raise ValueError('Invalid URL format')
        # Prevent SSRF attacks on internal networks
        blocked_patterns = [
            'localhost', '127.0.0.1', '0.0.0.0',
            '192.168.', '10.', '172.16.', '172.17.', '172.18.', '172.19.',
            '172.20.', '172.21.', '172.22.', '172.23.', '172.24.', '172.25.',
            '172.26.', '172.27.', '172.28.', '172.29.', '172.30.', '172.31.',
            '169.254.', '[::1]', '[fc', '[fd', 'metadata.google.internal',
        ]
        if any(pattern in v.lower() for pattern in blocked_patterns):
            raise ValueError('Access to internal networks is not allowed')
        return v


class TeamCreateValidated(BaseModel):
    """Team creation with validation"""
    name: str = Field(..., min_length=1, max_length=MAX_TEAM_NAME_LENGTH)
    contexte: Optional[str] = Field(None, max_length=MAX_TEAM_CONTEXTE_LENGTH)
    leader_agent_id: int = Field(..., gt=0)
    action_agent_ids: list[int] = Field(default_factory=list)

    @validator('name')
    def validate_name(cls, v):
        v = sanitize_text(v, MAX_TEAM_NAME_LENGTH)
        if not v:
            raise ValueError('Team name cannot be empty')
        return v

    @validator('contexte')
    def sanitize_contexte(cls, v):
        if not v:
            return v
        v = SCRIPT_PATTERN.sub('', v)
        return sanitize_text(v, MAX_TEAM_CONTEXTE_LENGTH)

    @validator('action_agent_ids')
    def validate_agent_ids(cls, v):
        if not all(isinstance(aid, int) and aid > 0 for aid in v):
            raise ValueError('Invalid agent IDs')
        if len(v) > 50:
            raise ValueError('Too many agents (max 50)')
        return v


# ============================================================================
# VALIDATION HELPERS FOR DIRECT USE
# ============================================================================

def validate_id_parameter(value: any, name: str = "ID") -> int:
    """
    Validate that a parameter is a positive integer.

    Security: Prevents SQL injection via ID parameters.
    """
    try:
        id_val = int(value)
        if id_val <= 0:
            raise HTTPException(status_code=400, detail=f"Invalid {name}: must be positive")
        return id_val
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail=f"Invalid {name}: must be an integer")


def validate_email_format(email: str) -> bool:
    """Validate email format"""
    return bool(EMAIL_REGEX.match(email))
