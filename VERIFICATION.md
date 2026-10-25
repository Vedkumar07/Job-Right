# Verification

Last checked: 2026-10-25.

## Automated checks

- `python3 -m unittest discover -s tests`: 80 Python tests passed.
- `python3 -m py_compile server.py platform_ingest.py application_profile.py automation.py core.py role_matching.py`: passed.
- `python3 -m json.tool extension/manifest.json`: passed.
- JavaScript syntax checks passed for the dashboard and Chrome extension scripts.
- `node tests/test_helper.cjs`: mocked Chrome API checks passed, including one reusable helper tab for sequential jobs and fail-closed behavior after extension update.
- `node tests/test_driver.cjs`: content-controller fixture passed for a two-step application, one reservation/submit attempt, confirmation detection, unknown answers, and login blockers.
- `node tests/test_facts.cjs`, `node tests/test_learning.cjs`, `node tests/test_platforms.cjs`, and `node tests/test_ui_lanes.cjs`: passed.
- `web/app.js` and `dist/app.js` are mirrored.

## Limits of these checks

- Browser and employer DOMs are fixtures or mocks; there has been no live Chrome session or real employer form submission from the test environment.
- Public company-board IDs are candidates until a successful collection run verifies them.
- The app only checks configured public sources. It does not enumerate the whole internet, bypass logins/CAPTCHAs, or guarantee support for every employer form.
- This test run does not install a systemd service, deploy a site, or start a persistent collector.
