import cv_agent
from database import CompanyFolder


def test_folders_include_cv_base(db_session, test_company):
    cv = CompanyFolder(company_id=test_company.id, name="CVs", is_cv_base=True)
    plain = CompanyFolder(company_id=test_company.id, name="Docs", is_cv_base=False)
    db_session.add_all([cv, plain])
    db_session.flush()

    assert cv_agent.folders_include_cv_base(db_session, test_company.id, [cv.id, plain.id]) is True
    assert cv_agent.folders_include_cv_base(db_session, test_company.id, [plain.id]) is False
    # folder_ids=None means "all company folders" -> true because a cv_base exists
    assert cv_agent.folders_include_cv_base(db_session, test_company.id, None) is True
    # no company -> false
    assert cv_agent.folders_include_cv_base(db_session, None, [cv.id]) is False
