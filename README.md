# JobHunter AI 🎯

An autonomous job application agent I built because I was tired of spending hours every day manually applying to jobs. It scrapes job boards, matches listings to your resume using AI, and applies on your behalf — all while you sleep.

---

## Why I built this

Honestly, job hunting is exhausting. I was spending 3-4 hours a day just going through LinkedIn, Indeed, Glassdoor... copying and pasting the same information into the same forms over and over. I thought there has to be a better way to do this.

So I decided to build something that does it for me.

The idea is simple — you upload your resume once, set your preferences, and the agent takes care of everything else. It finds recently posted jobs across 10 job boards, scores each one against your profile using AI, generates a personalized cover letter, and submits the application. Everything gets logged so you can see exactly what it did.

It's not perfect. Some job boards are harder to automate than others. But it works well enough that I'm using it myself while job hunting right now.

---

## What it does

- **Resume Parsing** — Upload your resume and Claude AI extracts your skills, experience, certifications, and job preferences automatically
- **Multi-board Scraping** — Monitors LinkedIn, Indeed, Glassdoor, ZipRecruiter, Dice, Monster, AngelList, Naukri, CareerBuilder, and SimplyHired
- **AI Job Matching** — Scores each job 0-100% based on how well it matches your profile
- **Auto-Apply** — Handles LinkedIn Easy Apply, Indeed Apply, and company portals (Greenhouse, Lever, Workday)
- **Cover Letter Generation** — Writes a personalized cover letter for each application using your actual experience
- **Job Tracker Dashboard** — Real-time view of every job found, applied to, or skipped
- **Scheduled Scanning** — Runs automatically every 3 hours in the background

---

## Tech Stack

**Backend**
- Python + FastAPI
- PostgreSQL (hosted on Railway)
- asyncpg for async database operations
- APScheduler for background job scheduling
- Playwright for browser automation

**AI**
- Anthropic Claude API for resume parsing, job matching, and cover letter generation
- Prompt engineering for structured JSON output

**Frontend**
- Vanilla HTML/CSS/JavaScript
- 4-page application (Dashboard, Resume Parser, Job Scraper, Auto-Apply Engine)

**Deployment**
- Railway (backend + database)
- Vercel (frontend, coming soon)

---

## Project Structure

```
jobhunter-ai/
├── main.py           # FastAPI app — 17 REST API endpoints
├── database.py       # PostgreSQL layer — all tables and queries
├── scraper.py        # Playwright scrapers for 10 job boards
├── applier.py        # Auto-apply engine (LinkedIn, Indeed, Greenhouse, Lever, Workday)
├── requirements.txt
├── Procfile
├── railway.json
└── frontend/
    ├── job-hunter-app.html     # Main dashboard
    ├── resume-parser.html      # Resume upload and AI parsing
    ├── job-scraper.html        # Job scanning and AI matching
    └── auto-apply-engine.html  # HunterBot control center
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/users/register` | Create account |
| POST | `/api/users/login` | Login |
| POST | `/api/resume/parse` | Parse resume with AI |
| GET | `/api/resume/{user_id}` | Get saved resume |
| POST | `/api/preferences` | Save job preferences |
| POST | `/api/scan/{user_id}` | Trigger job board scan |
| GET | `/api/jobs/{user_id}` | Get all matched jobs |
| POST | `/api/apply` | Apply to a job |
| GET | `/api/applications/{user_id}` | Get all applications |
| POST | `/api/cover-letter/generate` | Generate cover letter |
| GET | `/api/dashboard/{user_id}` | Get dashboard stats |
| GET | `/health` | Health check |

---

## Getting Started

**Requirements**
- Python 3.11+
- PostgreSQL database
- Anthropic API key (get one at console.anthropic.com)

**Setup**

```bash
# Clone the repo
git clone https://github.com/Polavamsi/jobhunter-ai.git
cd jobhunter-ai

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browser
playwright install chromium

# Create .env file
echo 'ANTHROPIC_API_KEY=your-key-here
DATABASE_URL=your-postgres-url-here' > .env

# Run locally
uvicorn main:app --reload
```

Open `http://localhost:8000/docs` to see all API endpoints.

---

## Current Status

The backend is fully deployed and running. Resume parsing, job matching, and cover letter generation all work. The auto-apply engine is built and handles Greenhouse, Lever, and Workday portals.

Things still in progress:
- Frontend user authentication (right now user IDs are hardcoded for testing)
- Real job scraping is working for most boards but some require login sessions
- PDF/DOCX resume upload (text paste works fine for now)
- Dashboard is showing sample data until I connect it to the real API

I'm actively working on this and using it for my own job search. Will keep updating as I improve it.

---

## What I learned building this

This project taught me a lot more than I expected. Setting up async database connections, dealing with CORS, browser automation, prompt engineering for structured output, deploying to Railway — none of this was straightforward.

The hardest part was honestly getting the database to connect properly on Railway. Internal networking between services was frustrating. Also learned the hard way that you should never put API keys directly in your code (used .env from day one but still).

If you're building something similar and get stuck, feel free to open an issue. I probably ran into the same problem.

---

## Live Demo

Backend API: https://captivating-amazement-production-55ce.up.railway.app  
API Docs: https://captivating-amazement-production-55ce.up.railway.app/docs

---

## License

MIT — do whatever you want with it.

---

*Built by Vamsi Krishna Pola while job hunting in 2026. McKinney, TX.*
