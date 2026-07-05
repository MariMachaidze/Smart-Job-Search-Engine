# Smart Job Search Engine

A personal AI-powered job hunting CRM that automatically scrapes company careers pages, learns your preferences from your feedback, and helps you manage your entire application process — from discovery to offer.

> Built in public, one phase at a time. Follow the build log below to see progress.

---

## The Problem

Job hunting is tedious. You manually visit dozens of careers pages, copy-paste job descriptions, try to remember which CV you sent where, and lose track of who you've contacted for referrals. Most job boards show you irrelevant roles and there's no easy way to track everything in one place.

## The Solution

An intelligent local web app that does the heavy lifting:
- Automatically finds and scrapes job listings from any company's careers page
- Learns what kinds of roles you actually want based on your feedback
- Tells you which CV to use for each role and exactly how to tailor it
- Tracks every application, referral, and interview stage in one place
- Gets smarter every time you use it

---

## Features

### Intelligent Scraping
- Provide a list of company names. The agent finds their careers pages automatically
- Handles pagination, infinite scroll, and varied page structures
- Polite crawling with request delays to avoid rate limiting

### Preference Learning
- No keywords to configure, just rate jobs as Relevant or Not Relevant
- AI analyses your ratings and builds a preference profile in plain language
- You can review, edit, and correct the profile before each new scan
- Gets more accurate over time as you provide more feedback

### CV Analysis (On Demand)
- multiple CVs supported (e.g. robotics-focused and AI/ML-focused)
- For each relevant job: recommends which CV to use and why
- Lists specific missing skills and high-level gaps
- Never modifies your actual CV files, only gives advice

### Application Tracking
- Track every job through: Saved → Applied → Interviewing → Rejected / Offer
- Log why you applied, referral status, and personal notes per job
- Change tracking between scans: New / Closed jobs flagged automatically

### Analytics
- Per-run and daily statistics
- Application funnel visualisation
- Company breakdown — who posts the most relevant roles
- Preference accuracy tracking over time

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python, FastAPI |
| Frontend | Jinja2, Tailwind CSS, HTMX |
| Database | SQLite + aiosqlite |
| Scraping | Playwright (headless Chromium) |
| Search | Brave Search API |
| AI | Anthropic Claude API |
| Infrastructure | Docker, Docker Compose |

---

## Project Structure

```
Smart-Job-Search-Engine/
├── app/                        # FastAPI web application
│   ├── main.py                 # App entry point
│   ├── templates/              # Jinja2 HTML templates
│   ├── static/                 # CSS and JS assets
│   └── Dockerfile
├── scraper/                    # Playwright scraper service
│   └── Dockerfile
├── data/                       # SQLite database (not committed)
├── input/                      # Your input files (not committed)
│   ├── companies.csv           # List of companies to scan
│   └── cvs/
│       ├── cv_robotics.txt     # Robotics-focused CV
│       └── cv_ai.txt           # AI/ML-focused CV
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## Getting Started

### Prerequisites
- [Docker Desktop](https://www.docker.com/products/docker-desktop)
- [Git](https://git-scm.com)

### 1. Clone the repo
```bash
git clone https://github.com/YOUR_USERNAME/Smart-Job-Search-Engine.git
cd Smart-Job-Search-Engine
```

### 2. Set up environment variables
```bash
cp .env.example .env
```
Open `.env` and fill in your API keys:
- `ANTHROPIC_API_KEY` — from [console.anthropic.com](https://console.anthropic.com)
- `BRAVE_API_KEY` — from [brave.com/search/api](https://brave.com/search/api)

### 3. Add your input files
Create `input/companies.csv`:
```csv
company
Anthropic
DeepMind
Boston Dynamics
```

Add your CVs as plain text files:
```
input/cvs/cv_robotics.txt
input/cvs/cv_ai.txt
```

### 4. Run
```bash
docker compose watch
```

Open [http://localhost:5000](http://localhost:5000)

---

## Environment Variables

See `.env.example` for all required variables:

| Variable | Where to get it |
|---|---|
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) |
| `BRAVE_API_KEY` | [brave.com/search/api](https://brave.com/search/api) |

---

## How It Works

```
companies.csv
    │
    ▼
Brave Search API ──► finds careers page URL per company
    │
    ▼
Playwright ──► scrapes all job listings (handles pagination + scroll)
    │
    ▼
Rating Queue ──► you rate each job: Relevant / Not Relevant
    │
    ▼
Preference Profile ──► AI learns what you want, you review + confirm
    │
    ▼
Next Scan ──► filtered automatically by your preferences
    │
    ▼
Relevant Jobs ──► CV analysis, application tracking, change detection
```

---

## Build Log

| Phase | Description | Status |
|---|---|---|
| 0 | Project skeleton — Docker, FastAPI, GitHub | ✅ Done |
| 1 | Brave Search — company name → careers URL | ⬜ |
| 2 | Playwright scraper — careers URL → job list | ⬜ |
| 3 | Job detail extractor — job URL → structured data | ⬜ |
| 4 | Database layer — full SQLite schema + helpers | ⬜ |
| 5 | UI shell — all pages with fake data | ⬜ |
| 6 | Scraping + UI connected with live progress | ⬜ |
| 7 | Rating queue with real scraped data | ⬜ |
| 8 | Preference learning — AI profile generation | ⬜ |
| 9 | CV analysis — on-demand per relevant job | ⬜ |
| 10 | Change tracking — new / closed job detection | ⬜ |
| 11 | Analytics — stats, funnel, trends | ⬜ |
| 12 | Smart filtering — preference-based scrape filter | ⬜ |

---

## Roadmap (Post-MVP)

- [ ] Cloud deployment for always-on access
- [ ] Kubernetes migration (learning exercise)
- [ ] Email/browser notifications for new relevant jobs
- [ ] Export to CSV / PDF
- [ ] Mobile-friendly UI
