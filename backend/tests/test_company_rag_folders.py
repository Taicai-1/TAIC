"""Pure unit tests for company_rag_folder_ids helpers in routers.agents.

These tests do NOT require a real database — the helpers are pure functions.
conftest.py sets DATABASE_URL before any import so routers.agents imports cleanly.
"""

from routers.agents import _parse_folder_ids, _folder_ids_out


def test_parse_folder_ids_empty_means_all():
    assert _parse_folder_ids("") is None
    assert _parse_folder_ids("[]") is None
    assert _parse_folder_ids(None) is None


def test_parse_folder_ids_valid_list():
    assert _parse_folder_ids("[1, 2, 3]") == "[1, 2, 3]"


def test_parse_folder_ids_garbage_means_all():
    assert _parse_folder_ids("not json") is None
    assert _parse_folder_ids('{"a":1}') is None


def test_folder_ids_out_roundtrip():
    assert _folder_ids_out(None) == []
    assert _folder_ids_out("[1, 2]") == [1, 2]
    assert _folder_ids_out("garbage") == []
