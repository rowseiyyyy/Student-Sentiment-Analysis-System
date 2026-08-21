# TODO: Complete system enhancements (bugs, tests, password reset, student history)

## A) Bug Fixes
- [x] 1. Backend: remove duplicated `user_id` line in `backend/app/api/evaluation.py`
- [x] 2. Frontend: replace hardcoded "By Department" ledger bars with real analytics data in `admin.js`
- [x] 3. Frontend: implement proper XLSX export (SheetJS) in `admin.js` + index.html
- [x] 4. Backend: relax strengths/areas_for_improvement validation in `submit_evaluation`

## C) Password Reset + User Profile Management
- [x] 5. Backend: add forgot-password / reset-password / profile endpoints in `auth.py`
- [x] 6. Backend: add auth schemas (forgot, reset, profile update)
- [x] 7. Frontend: wire forgot-password + profile UI into `api.js` / index.html / dashboards

## D) Student "My Submissions" History
- [x] 8. Frontend: add "My Submissions" tab to student module

## B) Expand Test Coverage
- [x] 9. Add `tests/test_prediction.py`
- [x] 10. Add `tests/test_imports.py`
- [x] 11. Extend `tests/test_analytics.py` (empty data, category filtering)
- [x] 12. Extend `tests/test_ml.py` (rollback, performance, confusion-matrix)
- [x] 13. Extend `tests/test_auth.py` (password reset, profile update)

## Verify
- [x] 14. Run pytest to verify all changes (40 passed)

## Additional fixes made during verification
- [x] 15. `limiter.enabled = False` in `tests/conftest.py` to prevent rate-limit tripping across tests
- [x] 16. Added `student_id`/`course`/`year_level` to `UserOut` schema so profile responses include student info
