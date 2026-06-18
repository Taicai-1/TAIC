"""WS4: 2FA backup code generation + single-use verification (pure, no DB)."""

from auth import generate_backup_codes, verify_and_consume_backup_code


def test_generate_returns_ten_codes_and_hashes():
    import json

    codes, hashed_json = generate_backup_codes()
    assert len(codes) == 10
    assert len(json.loads(hashed_json)) == 10
    # Hashes must not equal the plaintext.
    assert all(c not in hashed_json for c in codes)


def test_valid_code_verifies_and_is_consumed():
    import json

    codes, hashed_json = generate_backup_codes()
    ok, new_json = verify_and_consume_backup_code(codes[0], hashed_json)
    assert ok is True
    assert len(json.loads(new_json)) == 9  # one consumed
    # Same code no longer works against the updated set.
    ok2, _ = verify_and_consume_backup_code(codes[0], new_json)
    assert ok2 is False


def test_wrong_code_rejected():
    _, hashed_json = generate_backup_codes()
    ok, new_json = verify_and_consume_backup_code("not-a-real-code", hashed_json)
    assert ok is False
    assert new_json is None


def test_empty_store_rejected():
    ok, new_json = verify_and_consume_backup_code("anything", None)
    assert ok is False
