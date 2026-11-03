# JobFlow Automator

Find relevant jobs, rate them, and generate a tailored, ATS-friendly resume for each one, all from one dashboard.

JobFlow does three things:

1. **Search:** scrapes job postings from your configured sources (LinkedIn and Naukri by default) and stores them with the post date, scrape date, link, location, salary and company details.
2. **Rate:** an AI rates each job on how well you fit (0-100) and how good the company is (0-100), labels the company type (product, startup, MNC, IT services, and so on) and the work mode, then shortlists jobs that pass your rules.
3. **Tailor:** for each shortlisted job, it rewrites your summary, experience bullets, skills and projects from your baseline resume to match the job description, and compiles a PDF.

You apply yourself, then track progress (Applied, Got a call, Interviewing, Offer, Rejected...) in the dashboard. All data is saved to Google Sheets and to a local SQLite database.

```text
Search fresh jobs ──> New ──> Rate ──> Shortlisted ──> Build resume ──> Resume ready
                                  └──> Not a fit
You apply ──> Applied ──> Got a call ──> Interviewing ──> Offer
                    └──> Rejected / No response / Withdrawn
```

---

## Setup

Requirements: Python 3.11+, a LaTeX install with `pdflatex` (on macOS: `brew install --cask basictex`), a Cursor API key, and a Google service account.

```bash
cd "JobFlow Automator"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then fill it in
```

`.env` keys:

| Key | What it is |
|---|---|
| `CURSOR_API_KEY` | Cursor SDK key, used for rating and resume tailoring |
| `GOOGLE_SHEETS_CREDENTIALS_FILE` | Path to the service account JSON (default `config/credentials.json`) |
| `GOOGLE_SHEET_URL` | The Google Sheet to store jobs in. Share it with the service account email as **Editor**. |
| `STORE_PRIMARY` / `STORE_MIRRORS` | Where data lives. Default: Sheets is the source of truth, and SQLite gets a copy of every write. |
| `SQLITE_PATH` | Local database file (default `data/jobs.db`) |

The Google Sheets API must be enabled in the service account's Google Cloud project.

## Run

```bash
source .venv/bin/activate
streamlit run ui/app.py          # opens the dashboard at http://localhost:8501
```

Everything is available from the dashboard. The same actions also work from the command line:

```bash
python cli.py search            # scrape all enabled sources + rate new jobs
python cli.py build             # tailored resumes for all shortlisted jobs
python cli.py build --ids <id>  # resume for specific jobs
python cli.py rate --ids <id>   # re-rate specific jobs
python cli.py refilter          # re-apply shortlist rules after changing Settings (no AI calls)
python cli.py sync              # copy the Google Sheet into SQLite (after editing the Sheet by hand)
python cli.py migrate           # upgrade stored data after a version change
```

---

## Dashboard

| Page | What you do there |
|---|---|
| **Dashboard** | See counts per stage. Click **Search fresh jobs** to scrape and rate, or **Build resumes for shortlisted**. Shows your best matches and your application pipeline. |
| **Jobs** | Filter by status, fit, company rating, company type, source and post date. Change **Status** and **Notes** directly in the table and click **Save changes**. Tick rows to build resumes or re-rate them. |
| **Job** | One job in detail: scores, reasons, skills you match and gaps, the job description, a status and notes form, and resume download or rebuild. |
| **Settings** | Search terms, location, posted-within window, job type, remote only, sites, shortlist rules (minimum fit and company rating, allowed company types, work mode) and title filters. |
| **Resume baseline** | Edit your baseline resume, the fixed resume details (contact, job titles and dates, education, certifications, achievements) and the tailoring instructions. |

The pages are in a top navigation bar, which collapses into a menu on narrow screens. When you start a search or a resume build, an **Activity** panel at the bottom of the page shows live progress: which job is being tailored, keywords matched, PDF compiled, and any errors. It refreshes every 2 seconds and updates the page when the task finishes.

### Job statuses

| Status | Meaning |
|---|---|
| New | Just scraped, not rated yet |
| Shortlisted | Passed your shortlist rules |
| Not a fit | Rated below your rules |
| Resume ready | Tailored resume built |
| Applied | You applied (the date is recorded automatically) |
| Got a call | Recruiter or HR reached out |
| Interviewing | In interview rounds |
| Offer | Offer received |
| Rejected | Company said no |
| No response | No reply after applying |
| Withdrawn / Skipped | You dropped it |

---

## How resume tailoring works

- **Facts come only from** `config/baseline_resume.md`, your full resume in plain markdown. Add projects, metrics and skills there; more detail gives stronger resumes.
- **Fixed details** come from `config/candidate.json`: name and contact, job titles, companies and dates, education, certifications and achievements. The AI never changes these.
- For each job, the AI writes:
  - a **headline** using the job's title wording,
  - a **summary** aimed at the role,
  - **5-7 Epsilon bullets and 3-5 Deqode bullets**, ordered by relevance and using the job's keywords where truthful,
  - **grouped skills**, with the job's skills first,
  - the **2-3 most relevant projects**.
- **Tailoring mode** (Settings):
  - **Flexible**, the default: reshapes your real Epsilon and Deqode work around each job. It uses the job's vocabulary, highlights the aspects the job cares about, and mentions tools and practices that naturally go with your work (CI/CD, microservices, testing and so on).
  - **Strict:** stays close to your baseline wording.
  - Neither mode invents employers, titles, dates, degrees, certifications, metrics or whole projects.
- **Lean skills:** 4-5 groups with job-relevant skills first. Redundant basics (for example Firebase next to PostgreSQL and Databricks) are dropped, and Web3 gets at most one mention unless the job is about Web3.
- **Accuracy guard:** every number in the generated text is checked against the baseline. If the AI uses a metric that isn't in your baseline, the resume is regenerated without it.
- **ATS report:** each resume records the job keywords it covers and the ones you don't have, plus an **ATS match %**.
- **Output:** `output/<Company>/<Name>_<Role>_<id>.pdf`, plus the `.tex` source in case you want to hand-edit. The template is single column with standard headings and selectable text, which ATS parsers read well.

The PDF layout is `templates/resume_template.tex` with the `templates/resume.cls` style. The tailoring rules are in `prompts/resume.md` and the rating rules in `prompts/score.md`; both can be edited from the dashboard.

---

## Cover letters (on demand)

On the **Job** page, open any job and use the **Cover letter** section:

1. Optionally add notes, such as the hiring manager's name, a referral, why you want this company, or the tone you want.
2. Click **Generate cover letter**. It takes about 20 seconds, and progress shows in Activity.
3. Edit the text if you like (blank lines separate paragraphs) and click **Save edits** to update the PDF.
4. Download the **PDF** or **.txt**, or copy the text from the copy box.

The letter is 4 short paragraphs (about 230-300 words): a hook, 2-3 proof points mapped to the job's top requirements, why this company, and a close. Like the resume, it only uses facts from your baseline. Files are saved next to the resume as `output/<Company>/<Name>_Cover_Letter_<Role>_<id>.pdf` (and `.txt`). The writing rules are in `prompts/cover_letter.md`.

From the command line: `python cli.py cover --ids <job id> --notes "Hiring manager: Priya"`.

## Data storage

Each job has these columns, in both the Google Sheet (`Jobs` tab) and SQLite:

`id, company, title, url, source, location, work_mode, job_type, salary, date_posted, date_scraped, status, fit_score, company_rating, company_type, score_reason, matched_skills, missing_skills, resume_path, ats_match, resume_keywords, date_applied, notes, updated_at, company_info, description, cover_letter_path`

- Jobs are deduplicated by their normalised URL, so a job is never stored twice.
- If you edit the Sheet by hand, run `python cli.py sync` (or `sync` from the CLI) to refresh SQLite.
- To use only SQLite, set `STORE_PRIMARY=sqlite` and `STORE_MIRRORS=` in `.env`.

---

## Company career boards (Fortune 500 and top tech)

The `company_boards` source pulls jobs straight from company career sites through their public job feeds. It's more reliable than LinkedIn scraping (no blocking) and gives real posting dates and full descriptions.

| Platform | Companies included |
|---|---|
| Workday | NVIDIA, Salesforce, Adobe, Intel, Target, Mastercard, PayPal, HP, Morgan Stanley, Equinix |
| Greenhouse | Stripe, Databricks, Coinbase, Airbnb, Okta, MongoDB, Datadog, GitLab, Rubrik, Elastic, Zscaler, Twilio, Samsara, Razorpay |
| Lever | Zeta, CRED, Paytm, JumpCloud |
| Ashby | OpenAI, Notion, Snowflake, Sarvam AI |

Configure it in **Settings → Company career boards**: turn it on or off, set the maximum posting age, the maximum jobs per company, and the location keywords (default: Bangalore, Bengaluru, India). To add a company, put its board ID in the JSON list:

- Greenhouse: `boards.greenhouse.io/<id>` → `"<id>": "Company Name"`
- Lever: `jobs.lever.co/<id>` → `"<id>": "Company Name"`
- Ashby: `jobs.ashbyhq.com/<id>` → `"<id>": "Company Name"`
- Workday: the careers URL → `{"company": "Name", "url": "https://<tenant>.wdN.myworkdayjobs.com/<site>"}`

Google, Microsoft, Amazon and Apple run their own career sites and aren't covered; LinkedIn via JobSpy still finds their postings.

## Adding a new job source

Sources are plugins in `services/sources/`. To add one, for example a company careers API:

```python
# services/sources/my_source.py
from services.sources import register_source
from services.sources.base import JobSource, RawJob


@register_source
class MySource(JobSource):
    name = "my_source"

    def fetch(self) -> list[RawJob]:
        # self.config = this source's block in config/settings.json
        # self.search = shared search settings, e.g. posted_within_hours
        return [RawJob(company="Acme", title="Full Stack Engineer", url="https://...",
                       description="...", source="my_source", date_posted="2026-10-29")]
```

Then enable it in `config/settings.json`:

```json
"sources": {
  "jobspy": { "enabled": true, "...": "..." },
  "my_source": { "enabled": true }
}
```

Deduplication, title filters, rating, storage and resumes work for it automatically.

---

## Project layout

```text
cli.py                    command line entry point
ui/app.py                 Streamlit dashboard
core/
  config.py               loads .env and config files
  models.py               Job model and statuses
  llm.py                  Cursor SDK wrapper (JSON output)
  store/                  storage: Google Sheets, SQLite and a wrapper that writes to both
services/
  sources/                pluggable job sources (jobspy_source.py = LinkedIn, Naukri, Indeed...)
  scraper.py              runs sources, dedupes and filters, stores new jobs
  scorer.py               fit score, company rating, company type, shortlist rules
  resume_builder.py       tailoring, accuracy guard, LaTeX to PDF
config/
  settings.json           search and shortlist settings (edited from the Settings page)
  baseline_resume.md      your full resume, the source of truth for tailoring
  candidate.json          fixed resume details
  credentials.json        Google service account (git-ignored)
prompts/                  AI instructions for rating and tailoring
templates/                LaTeX resume template and class file
data/jobs.db              SQLite copy of all jobs
output/<Company>/         generated resumes
logs/                     run logs
```

## Troubleshooting

- **"Jobs sheet columns are out of date"**: run `python cli.py migrate`.
- **Google Sheets 403 error**: enable the Sheets API for the service account's project and share the Sheet with the service account email.
- **pdflatex error**: check that `pdflatex` is on your PATH. The full LaTeX error is saved in the job's Notes.
- **No jobs found**: widen **Posted within**, add search terms, or loosen the title filters in Settings.
