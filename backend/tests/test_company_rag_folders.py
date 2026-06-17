"""Pure unit tests for company_rag_folder_ids helpers in routers.agents.

These tests do NOT require a real database — the helpers are pure functions.
conftest.py sets DATABASE_URL before any import so routers.agents imports cleanly.
"""

import json

from routers.agents import _parse_folder_ids, _folder_ids_out


def test_parse_folder_ids_empty_means_all():
    assert _parse_folder_ids("") is None
    assert _parse_folder_ids("[]") is None
    assert _parse_folder_ids(None) is None


def test_parse_folder_ids_valid_list():
    # Assert on the parsed value, not exact JSON whitespace.
    assert json.loads(_parse_folder_ids("[1, 2, 3]")) == [1, 2, 3]
    # String-form ids are accepted too.
    assert json.loads(_parse_folder_ids('["4", "5"]')) == [4, 5]


def test_parse_folder_ids_garbage_means_all():
    assert _parse_folder_ids("not json") is None
    assert _parse_folder_ids('{"a":1}') is None


def test_parse_folder_ids_drops_non_positive_and_non_int():
    # Negatives, zero, booleans and non-numeric entries are dropped.
    assert _parse_folder_ids("[-1, 0, 2]") == json.dumps([2])
    assert _parse_folder_ids("[true, false, 3]") == json.dumps([3])
    assert _parse_folder_ids('["x", null, 7]') == json.dumps([7])
    # A list with only invalid ids collapses to None (= all folders).
    assert _parse_folder_ids("[-1, 0]") is None


def test_folder_ids_out_filters_types():
    assert _folder_ids_out(None) == []
    assert _folder_ids_out("[1, 2]") == [1, 2]
    assert _folder_ids_out("garbage") == []
    assert _folder_ids_out('{"a": 1}') == []
    # Corrupt stored data: non-int elements are dropped, bools excluded.
    assert _folder_ids_out('[1, "evil", null, true, 3]') == [1, 3]


def test_parse_then_out_round_trip():
    for raw in ["[1, 2, 3]", "[42]", "[]", None, "", "[-1, 0]"]:
        stored = _parse_folder_ids(raw)
        out = _folder_ids_out(stored)
        assert isinstance(out, list)
        assert all(isinstance(i, int) and not isinstance(i, bool) for i in out)
        if stored is not None:
            assert len(out) > 0
