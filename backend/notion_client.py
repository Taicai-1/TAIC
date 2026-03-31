"""
Notion API Client
Lightweight client for fetching content from Notion pages and databases.
Uses the Notion REST API directly via requests.
"""

import os
import re
import logging

import requests

logger = logging.getLogger(__name__)

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def get_notion_token(company_id: int = None) -> str | None:
    """Get Notion API token from org-level credentials only.
    No global env var fallback - Notion must be configured at the org level."""
    if not company_id:
        return None

    try:
        from database import SessionLocal, Company
        db = SessionLocal()
        company = db.query(Company).filter(Company.id == company_id).first()
        db.close()
        if company and company._notion_api_key:
            org_token = company.org_notion_api_key
            if org_token:
                return org_token.strip()
    except Exception as e:
        logger.warning(f"Failed to get org Notion token for company {company_id}: {e}")

    return None


def _headers(company_id: int = None) -> dict:
    token = get_notion_token(company_id)
    if not token:
        raise RuntimeError("Notion is not configured for this organization")
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


# Store company_id in module-level var so internal recursive calls can use it
_current_company_id = None


def extract_notion_id(url_or_id: str) -> str:
    """Extract a Notion UUID from a URL or raw ID string."""
    url_or_id = url_or_id.strip()

    # Already a UUID (with or without dashes)
    uuid_pattern = re.compile(r"^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$", re.I)
    if uuid_pattern.match(url_or_id):
        return url_or_id.replace("-", "")

    # Notion URL: https://www.notion.so/workspace/Page-Title-abc123def456...
    # The ID is the last 32 hex chars (no dashes) at the end of the path
    match = re.search(r"([0-9a-f]{32})(?:\?|$)", url_or_id, re.I)
    if match:
        return match.group(1)

    # Fallback: try the last segment after the last dash
    match = re.search(r"-([0-9a-f]{32})$", url_or_id, re.I)
    if match:
        return match.group(1)

    raise ValueError(f"Cannot extract Notion ID from: {url_or_id}")


def fetch_page_title(page_id: str, company_id: int = None) -> str:
    """Fetch the title of a Notion page."""
    resp = requests.get(f"{NOTION_API_BASE}/pages/{page_id}", headers=_headers(company_id), timeout=15)
    resp.raise_for_status()
    data = resp.json()

    properties = data.get("properties", {})
    for prop in properties.values():
        if prop.get("type") == "title":
            title_parts = prop.get("title", [])
            return "".join(t.get("plain_text", "") for t in title_parts) or "Untitled"
    return "Untitled"


def fetch_database_title(database_id: str, company_id: int = None) -> str:
    """Fetch the title of a Notion database."""
    resp = requests.get(f"{NOTION_API_BASE}/databases/{database_id}", headers=_headers(company_id), timeout=15)
    resp.raise_for_status()
    data = resp.json()
    title_parts = data.get("title", [])
    return "".join(t.get("plain_text", "") for t in title_parts) or "Untitled Database"


def fetch_page_content(page_id: str, company_id: int = None) -> list[dict]:
    """Fetch all blocks from a Notion page (recursive for nested blocks)."""
    global _current_company_id
    _current_company_id = company_id
    blocks = []
    _fetch_blocks_recursive(page_id, blocks)
    _current_company_id = None
    return blocks


def _fetch_blocks_recursive(block_id: str, blocks: list, depth: int = 0):
    """Recursively fetch blocks and their children."""
    if depth > 3:
        return

    cursor = None
    while True:
        params = {"page_size": 100}
        if cursor:
            params["start_cursor"] = cursor

        resp = requests.get(
            f"{NOTION_API_BASE}/blocks/{block_id}/children",
            headers=_headers(_current_company_id),
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        for block in data.get("results", []):
            blocks.append(block)
            if block.get("has_children"):
                _fetch_blocks_recursive(block["id"], blocks, depth + 1)

        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")


def fetch_database_entries(database_id: str, company_id: int = None) -> list[dict]:
    """Query all entries from a Notion database."""
    entries = []
    cursor = None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor

        resp = requests.post(
            f"{NOTION_API_BASE}/databases/{database_id}/query",
            headers=_headers(company_id),
            json=body,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        entries.extend(data.get("results", []))

        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    return entries


def _rich_text_to_str(rich_texts: list) -> str:
    return "".join(rt.get("plain_text", "") for rt in rich_texts)


def blocks_to_text(blocks: list[dict]) -> str:
    """Convert Notion blocks to readable plain text."""
    lines = []
    for block in blocks:
        btype = block.get("type", "")
        bdata = block.get(btype, {})

        if btype in ("paragraph", "quote", "callout"):
            text = _rich_text_to_str(bdata.get("rich_text", []))
            if text:
                prefix = "> " if btype == "quote" else ""
                lines.append(f"{prefix}{text}")

        elif btype == "heading_1":
            text = _rich_text_to_str(bdata.get("rich_text", []))
            lines.append(f"\n# {text}")

        elif btype == "heading_2":
            text = _rich_text_to_str(bdata.get("rich_text", []))
            lines.append(f"\n## {text}")

        elif btype == "heading_3":
            text = _rich_text_to_str(bdata.get("rich_text", []))
            lines.append(f"\n### {text}")

        elif btype == "bulleted_list_item":
            text = _rich_text_to_str(bdata.get("rich_text", []))
            lines.append(f"- {text}")

        elif btype == "numbered_list_item":
            text = _rich_text_to_str(bdata.get("rich_text", []))
            lines.append(f"1. {text}")

        elif btype == "to_do":
            text = _rich_text_to_str(bdata.get("rich_text", []))
            checked = bdata.get("checked", False)
            marker = "[x]" if checked else "[ ]"
            lines.append(f"- {marker} {text}")

        elif btype == "code":
            text = _rich_text_to_str(bdata.get("rich_text", []))
            lang = bdata.get("language", "")
            lines.append(f"```{lang}\n{text}\n```")

        elif btype == "toggle":
            text = _rich_text_to_str(bdata.get("rich_text", []))
            lines.append(f"<toggle> {text}")

        elif btype == "divider":
            lines.append("---")

        elif btype == "table_row":
            cells = bdata.get("cells", [])
            row = " | ".join(_rich_text_to_str(cell) for cell in cells)
            lines.append(f"| {row} |")

        elif btype == "child_page":
            title = bdata.get("title", "")
            lines.append(f"[Child page: {title}]")

        elif btype == "child_database":
            title = bdata.get("title", "")
            lines.append(f"[Child database: {title}]")

    return "\n".join(lines)


def database_entries_to_text(entries: list[dict]) -> str:
    """Convert Notion database entries to readable text."""
    lines = []
    for entry in entries:
        props = entry.get("properties", {})
        row_parts = []
        for prop_name, prop_val in props.items():
            ptype = prop_val.get("type", "")
            value = ""
            if ptype == "title":
                value = _rich_text_to_str(prop_val.get("title", []))
            elif ptype == "rich_text":
                value = _rich_text_to_str(prop_val.get("rich_text", []))
            elif ptype == "number":
                value = str(prop_val.get("number", ""))
            elif ptype == "select":
                sel = prop_val.get("select")
                value = sel.get("name", "") if sel else ""
            elif ptype == "multi_select":
                value = ", ".join(s.get("name", "") for s in prop_val.get("multi_select", []))
            elif ptype == "date":
                d = prop_val.get("date")
                if d:
                    value = d.get("start", "")
                    if d.get("end"):
                        value += f" -> {d['end']}"
            elif ptype == "checkbox":
                value = "Yes" if prop_val.get("checkbox") else "No"
            elif ptype == "status":
                st = prop_val.get("status")
                value = st.get("name", "") if st else ""
            elif ptype == "url":
                value = prop_val.get("url", "") or ""
            elif ptype == "email":
                value = prop_val.get("email", "") or ""
            elif ptype == "phone_number":
                value = prop_val.get("phone_number", "") or ""
            elif ptype == "people":
                value = ", ".join(p.get("name", "") for p in prop_val.get("people", []))
            elif ptype == "relation":
                value = f"({len(prop_val.get('relation', []))} relations)"
            elif ptype == "formula":
                formula = prop_val.get("formula", {})
                value = str(formula.get(formula.get("type", ""), ""))

            if value:
                row_parts.append(f"{prop_name}: {value}")

        if row_parts:
            lines.append(" | ".join(row_parts))

    return "\n".join(lines)
