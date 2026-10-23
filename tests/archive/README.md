# tests/archive

Archived UI E2E tests for the old two-page UI (`/static/archive/two-page/`).
The UI was replaced by the studio pages (`/studio`, `/studio/app`), so these files are kept for reference only.
File contents are unchanged from when they were moved. They depend on fixtures in `tests/e2e/conftest.py`, so they do not run from this folder as is.

## Old scenario to new case (`tests/e2e/test_studio_ui.py`, `test_studio_voice_real.py`)

| Old case | New case |
|----------|----------|
| test_home_presets_and_form | test_studio_list_and_filter |
| (two-page Creation error) | test_create_empty_rejected |
| test_csv_create_to_talk | test_csv_create_to_workspace |
| test_preset_to_talk_receipt, test_receipt_collapses | test_preset_chat_receipt |
| test_scorecard_tab | test_scorecard_restaurant |
| test_ab_tab | test_ab_compare |
| test_share_link_direct_entry | test_share_link_fresh_context |
| test_expired_agent | test_unknown_agent_recovery |
| test_busy_error | test_busy_error |
| test_mic_denied | test_mic_denied_or_hidden |
| test_mobile_390 | test_mobile_390 |
| test_same_origin_only | test_same_origin_only |
| test_no_engine_terms | test_no_engine_or_mock_terms |
| test_talk_mic_voice_question | test_studio_voice_real |
