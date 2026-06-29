"""Shared, mostly-pure logic for importing a whole directory tree into a RAG folder system.

The two routers (companion ``agent_folders`` and company ``company_rag``) inject their own
find/create-folder and ingestion callbacks, so the tree-resolution and import loop here
stay tenant-agnostic and unit-testable without a database.
"""

import json
import logging

import redis_client

logger = logging.getLogger(__name__)

# Abuse guards (aligned with the single-upload limits).
MAX_IMPORT_FILES = 200
MAX_IMPORT_TOTAL_SIZE = 200 * 1024 * 1024  # 200 MB
IMPORT_TASK_TTL = 3600  # 1 hour, like doc_task:*


def split_relative_path(rel_path):
    """Split a browser webkitRelativePath into (dir_segments, filename).

    'Contrats/2024/bail.pdf' -> (['Contrats', '2024'], 'bail.pdf').
    Backslashes are normalised to '/', '.'/empty segments are dropped, and '..'
    pops the previous segment (defensive normalisation against path traversal).
    """
    norm = (rel_path or "").replace("\\", "/")
    parts = []
    for seg in norm.split("/"):
        if not seg or seg == ".":
            continue
        if seg == "..":
            if parts:
                parts.pop()
            continue
        parts.append(seg)
    if not parts:
        return [], ""
    return parts[:-1], parts[-1]


def resolve_folder_for_path(dir_segments, destination_parent_id, find_child, create_child, cache):
    """Ensure the folder chain for dir_segments exists under destination_parent_id.

    Merges into existing same-named children (find_child) and lazily creates the rest
    (create_child). Returns the leaf folder id, or destination_parent_id if dir_segments
    is empty. Results are memoised per (destination_parent_id, path-so-far) in ``cache``.

    find_child(parent_id, name) -> folder_id | None
    create_child(parent_id, name) -> folder_id
    """
    parent = destination_parent_id
    path_key = ()
    for seg in dir_segments:
        path_key = path_key + (seg,)
        cache_key = (destination_parent_id, path_key)
        if cache_key in cache:
            parent = cache[cache_key]
            continue
        existing = find_child(parent, seg)
        fid = existing if existing is not None else create_child(parent, seg)
        cache[cache_key] = fid
        parent = fid
    return parent


def run_folder_import(items, destination_parent_id, find_child, create_child, ingest_file, is_supported, set_status):
    """Import each (filename, rel_path, content) item under destination_parent_id.

    Skips unsupported files (is_supported), creates folders lazily (no empty folders),
    ingests supported files into their resolved folder, and reports progress via
    set_status(total, done, skipped, failed, root_folder_id, status). Per-file ingestion
    errors are counted as ``failed`` without aborting the batch. Returns a summary dict.
    """
    cache = {}
    total = len(items)
    done = skipped = failed = 0
    root_folder_id = None
    for filename, rel_path, content in items:
        if not is_supported(filename, content):
            skipped += 1
            set_status(total, done, skipped, failed, root_folder_id, "processing")
            continue
        dir_segments, _ = split_relative_path(rel_path)
        try:
            folder_id = resolve_folder_for_path(dir_segments, destination_parent_id, find_child, create_child, cache)
            if root_folder_id is None and dir_segments:
                root_folder_id = cache[(destination_parent_id, (dir_segments[0],))]
            ingest_file(filename, content, folder_id)
            done += 1
        except Exception as e:
            logger.warning(f"folder import: failed on {rel_path}: {e}")
            failed += 1
        set_status(total, done, skipped, failed, root_folder_id, "processing")
    set_status(total, done, skipped, failed, root_folder_id, "completed")
    return {"total": total, "done": done, "skipped": skipped, "failed": failed, "root_folder_id": root_folder_id}


def set_import_status(task_id, total, done, skipped, failed, root_folder_id, status, error=None):
    """Write an import task status to Redis (no-op if Redis is unavailable)."""
    r = redis_client.get_redis()
    if r is None:
        return
    r.setex(
        f"import_task:{task_id}",
        IMPORT_TASK_TTL,
        json.dumps(
            {
                "task_id": task_id,
                "status": status,
                "total": total,
                "done": done,
                "skipped": skipped,
                "failed": failed,
                "root_folder_id": root_folder_id,
                "error": error,
            }
        ),
    )


def get_import_status(task_id):
    """Read an import task status from Redis. Returns dict or None."""
    r = redis_client.get_redis()
    if r is None:
        return None
    data = r.get(f"import_task:{task_id}")
    return json.loads(data) if data else None
