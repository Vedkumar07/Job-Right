# Role Radar

Role Radar is a local, single-user job discovery and application assistant. It collects public job postings from configured company sources, ranks them against separate resume/role lanes, and can fill supported employer forms through a Chrome extension.

The dashboard and collector run on your computer. Candidate profile data and application history are stored in a local SQLite database. No hosted database, paid job-data API, AI API, or cloud browser is required.

## Contents

- [Features](#features)
- [Requirements](#requirements)
- [Run Role Radar](#run-role-radar)
- [Install the Chrome helper](#install-the-chrome-helper)
- [Set up resumes and matching](#set-up-resumes-and-matching)
- [Configure job sources](#configure-job-sources)
- [How application automation works](#how-application-automation-works)
- [Data and privacy](#data-and-privacy)
- [Tests](#tests)
- [Project layout](#project-layout)
- [Limitations](#limitations)

## Features

- Local dashboard for matches, saved roles, applications, unanswered questions, source coverage, automation settings, and resume lanes.
- Separate resumes and target roles for different job families. Each opening is scored against enabled lanes and the best matching lane is selected for automation.
- Explainable heuristic scores based on role fit, relevant skill overlap, location preference, and experience requirements. Scores do not estimate hiring probability or verify eligibility.
- Geography-first display order: remote roles that appear open to applicants in India, India-based jobs, then other locations. Country-restricted remote roles are demoted to the worldwide group. The location parser uses job-feed text and is not a legal or eligibility check.
- Public job collectors for Greenhouse, Lever, Ashby, SmartRecruiters, and bounded public career-page `JobPosting` data. Source boards can be added one at a time or imported by CSV.
- Visible job-card import for YC/Work at a Startup and Naukri from pages opened by the user in Chrome. This reads rendered cards; it does not use private platform APIs.
- A local Chrome helper that fills known fields, advances supported application steps, records blockers, and can submit eligible applications under the saved settings.
- A reusable answer bank. The helper reuses user-provided facts, keeps bespoke answers scoped, and leaves unknown or sensitive answers for the user.
- Application and helper history, explicit employer-confirmation detection, duplicate-submission reservations, and local notifications.
- Dashboard payload capped to 1,000 ranked jobs with shortened descriptions so a large local database does not overwhelm the browser. The server-side automation queue still evaluates the complete active job set.

## Requirements

- Python 3.11 or newer.
- Chrome or Chromium for browser-based applications.
- Network access for public job collection.
- No Python package or npm install is required; the app uses the Python standard library and plain JavaScript.
- PDF text extraction uses the system `pdftotext` program. DOCX, TXT, Markdown, or pasted resume text can be used without PDF tooling.

## Run Role Radar

From the repository root:

```sh
./start.sh
```

Open [http://127.0.0.1:8877](http://127.0.0.1:8877). The server binds to loopback only; do not expose it directly to the public internet.

The collector checks configured sources at startup and then on its per-source schedule (12 hours by default) while the server is running. The computer must be awake and online for collection. `Ctrl+C` stops the server and scheduler.

Run a one-time collection and exit:

```sh
python3 server.py --once
```

Run the dashboard without its built-in scheduler, for example when using the included systemd timer:

```sh
python3 server.py --no-scheduler
```

The `scripts/` folder contains user-service and timer templates. Review and adjust their paths before installing. Use either the built-in scheduler or the 09:00/21:00 Asia/Kolkata timer, not both.

## Install the Chrome helper

1. Start the Python server and open the dashboard at `http://127.0.0.1:8877`.
2. In Chrome, open `chrome://extensions` and enable Developer mode.
3. Choose **Load unpacked** and select the repository's `extension/` directory. For example: `/home/your-user/role-radar/extension`.
4. Check the extension details and confirm it is loaded from this repository path. Avoid leaving another old Role Radar copy enabled; two copies can both control tabs.
5. Open the dashboard and click the extension icon. Version 4.0.3's popup runs a connection check and shows whether the server, dashboard profile, and helper heartbeat are connected.

Fresh installs and extension updates start with automatic tab opening paused. Review the profile and settings first. If desired, enable **Let the helper open strong matches** in the extension popup and use **Run agent now** in the dashboard. The helper processes one job at a time in one reusable tab and pauses when it needs review.

The current manifest uses `storage`, `activeTab`, `scripting`, `alarms`, `tabs`, and `notifications`. It requests access to HTTPS sites so it can work on employer pages; it does not request Chrome's browsing-history permission.

## Set up resumes and matching

1. Open **Resumes & role lanes** and create a lane for each kind of role you want (for example, backend, data, or DevOps).
2. Add the resume text or upload a PDF, DOCX, TXT, or Markdown resume. Review extracted text before saving.
3. Set target role keywords and factual experience for each lane. Paused lanes are excluded from matching and automation.
4. Fill shared applicant contact details in the profile. Keep these as the applicant's own facts; lanes change the role resume, not the applicant identity.
5. Use the location selector to view India-friendly remote roles, India roles, or other locations. **India + remote first** is the default view; **All locations** is available.

Matching is a transparent heuristic. Review role descriptions, required experience, employment eligibility, and location restrictions yourself.

## Configure job sources

The initial `sources.json` contains candidate company boards. A candidate source is not a verified partnership or guarantee that its board still exists. Failures are shown in source coverage.

You can add sources in **Company coverage** or import a CSV:

```csv
company,kind,board,category
Example Company,greenhouse,example,Startup
Another Company,career_page,https://example.com/careers,MNC
```

Supported kinds are `greenhouse`, `lever`, `ashby`, `smartrecruiters`, and `career_page`. Career-page collection is bounded to public same-host pages and respects robots.txt; it cannot execute arbitrary JavaScript or access gated pages.

For YC/Work at a Startup or Naukri, open a listings page in Chrome while the helper is enabled. The extension captures up to 100 visible job cards per batch and imports only supported job URLs. It does not sign in for you, bypass anti-bot controls, or collect a hidden platform feed.

The dashboard browser view is intentionally limited to the top 1,000 ranked openings. All jobs remain in SQLite and the server queue; use filters and source coverage to inspect the visible set. This app does not enumerate every company or every job on the internet.

## How application automation works

The application agent uses the profile and selected resume lane, fills supported native fields and some ARIA controls, advances recognized form steps, and checks required fields. It can follow a visible, explicitly labelled HTTPS **Apply** link associated with the queued job.

The extension and server coordinate through a short-lived local session token. Submission reservations prevent repeat submit clicks. “Submission attempted” is distinct from a confirmed submission; Role Radar records confirmation only when it detects an employer confirmation page.

The queue pauses for unknown required answers, login/account creation, CAPTCHA, unsupported controls, changed resume facts, or other review conditions. It never guesses legal or sensitive answers and does not bypass login, CAPTCHA, verification codes, or site restrictions. Some employer forms and redirects are not supported.

The dashboard's **Autopilot enabled** and **Automatic submission** settings control server policy. The Chrome popup's **Let the helper open strong matches** controls whether the extension opens queued jobs. Automatic opening is off after a fresh install/update; turn it on only after reviewing the saved profile and policy.

## Data and privacy

- SQLite data is stored in `data/radar.sqlite3` by default. This contains personal profile/resume text, saved answers, collected jobs, and application history. It is excluded from Git.
- Set `RADAR_DATA_DIR` before starting the server to use a different local data directory.
- Resume text, extension configuration, and application events are served by the local Python process. This project has no cloud backend or external AI service.
- The extension stores its helper configuration and unsynced history in Chrome extension storage. Export history from the extension popup if you need a separate copy.
- To delete local application data, stop the server and remove the configured data directory. Also clear the extension profile/history from Chrome if you want those removed.
- Do not commit resumes, exported profiles, SQLite files, `.env` files, credentials, Chrome profile data, or the separate `whatsupdha/` project.

## Tests

Run the Python suite:

```sh
python3 -m unittest discover -s tests -v
```

Run browser-helper and UI fixtures:

```sh
node tests/test_helper.cjs
node tests/test_driver.cjs
node tests/test_facts.cjs
node tests/test_learning.cjs
node tests/test_platforms.cjs
node tests/test_ui_lanes.cjs
```

The tests use synthetic data and mocked Chrome/DOM APIs. They do not prove compatibility with every live employer portal. Live Chrome and employer-form validation should be done on a test application before relying on automation.

## Project layout

```text
core.py                 SQLite schema, collection, feed adapters, and utilities
role_matching.py        Resume-lane analysis and relevance scoring
application_profile.py  Structured facts, question capture, and answer reuse
automation.py           Queue, profile revisions, and submission policy
platform_ingest.py      Validated YC/Naukri visible-card import
server.py               Local HTTP server and JSON API
web/                    Dashboard source files
dist/                   Mirrored static dashboard files
extension/              Chrome Manifest V3 helper
sources.json            Candidate public job-board sources
scripts/                Optional systemd service/timer templates
tests/                  Python and JavaScript fixture tests
```

The project is designed for local single-user use. No cloud deployment, background service installation, or live employer application is included by default.
