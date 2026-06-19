"""Support account: cross-company access. Task 1 covers the model + contextvars;
endpoint/behavior tests are added in Task 9 (PG-backed)."""

import database


def test_is_support_defaults_falsey():
    from tests.factories import UserFactory

    u = UserFactory.build()
    # Column default applies at INSERT; on a built (un-flushed) instance it's False/None.
    assert getattr(u, "is_support", None) in (False, None)


def test_support_session_contextvar_roundtrip():
    database.set_support_session(True)
    assert database.is_support_session() is True
    database.set_support_session(False)
    assert database.is_support_session() is False


def test_get_current_company_id_reads_contextvar():
    database.set_current_company_id(4242)
    assert database.get_current_company_id() == 4242
    database.set_current_company_id(None)
