"""
JobHunter AI — FastAPI Backend (Anthropic Claude)
"""
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import anthropic
import asyncio
import json
import os
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from database import db
from scraper import scrape_all_boards
import httpx

load_dotenv()

app = FastAPI(title="JobHunter AI API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

claude = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
scheduler = AsyncIOScheduler()


# ─── MODELS ────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    name: str
    email: str
    password: str

class ResumeUpload(BaseModel):
    user_id: str
    resume_text: str

class JobPreferences(BaseModel):
    user_id: str
    roles: List[str]
    location: str
    experience_level: str
    min_match_threshold: int = 75
    max_applies_per_day: int = 25
    auto_apply_enabled: bool = True
    generate_cover_letters: bool = True
    scan_frequency_hours: int = 3

class ManualJobAdd(BaseModel):
    user_id: str
    job_url: str
    job_title: Optional[str] = None
    company: Optional[str] = None

class ApplyRequest(BaseModel):
    user_id: str
    job_id: str
    cover_letter: Optional[str] = None


# ─── STARTUP / SHUTDOWN ────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    try:
        await db.connect()
        await db.create_tables()
        print("✅ JobHunter AI backend started")
    except Exception as e:
        print(f"⚠️ DB connection failed: {e} — app starting anyway")
    scheduler.start()

@app.on_event("shutdown")
async def shutdown():
    scheduler.shutdown()
    await db.disconnect()


# ─── USERS ─────────────────────────────────────────────────────────────────

@app.post("/api/users/register")
async def register(user: UserCreate):
    existing = await db.get_user_by_email(user.email)
    if existing:
        raise HTTPException(400, "Email already registered")
    user_id = await db.create_user(user.name, user.email, user.password)
    return {"success": True, "user_id": user_id, "name": user.name}

@app.post("/api/users/login")
async def login(email: str, password: str):
    user = await db.verify_user(email, password)
    if not user:
        raise HTTPException(401, "Invalid credentials")
    return {"success": True, "user_id": user["id"], "name": user["name"]}

@app.get("/api/users/{user_id}")
async def get_user(user_id: str):
    user = await db.get_user(user_id)
    if not user:
        raise HTTPException(404, "User not found")
    return user


# ─── RESUME ────────────────────────────────────────────────────────────────

@app.post("/api/resume/parse")
async def parse_resume(payload: ResumeUpload):
    prompt = f"""Parse this resume and respond ONLY with valid JSON, no markdown, no backticks.

Schema:
{{
  "name": "Full Name",
  "initials": "VK",
  "title": "Job Title",
  "location": "City, State",
  "email": "email",
  "phone": "phone",
  "summary": "2-sentence summary",
  "skills": {{"languages":[],"ml":[],"cloud":[],"databases":[]}},
  "experience": [{{"role":"","company":"","period":""}}],
  "certifications": [],
  "projects": [],
  "jobPreferences": {{
    "targetRoles": [],
    "targetIndustries": [],
    "experienceLevel": "",
    "openToRemote": true,
    "openToRelocation": true
  }},
  "confidence": "97%"
}}

Resume:
{payload.resume_text}"""

    response = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = response.content[0].text.replace("```json", "").replace("```", "").strip()
    profile = json.loads(raw)
    try:
        await db.save_resume(payload.user_id, payload.resume_text, profile)
    except Exception as e:
        print(f"⚠️ Could not save resume: {e}")
    return {"success": True, "profile": profile}

@app.get("/api/resume/{user_id}")
async def get_resume(user_id: str):
    resume = await db.get_resume(user_id)
    if not resume:
        raise HTTPException(404, "No resume found")
    return resume


# ─── PREFERENCES ───────────────────────────────────────────────────────────

@app.post("/api/preferences")
async def save_preferences(prefs: JobPreferences):
    await db.save_preferences(prefs.user_id, prefs.dict())
    if scheduler.get_job("auto_scan"):
        scheduler.reschedule_job("auto_scan", trigger="interval", hours=prefs.scan_frequency_hours)
    return {"success": True}

@app.get("/api/preferences/{user_id}")
async def get_preferences(user_id: str):
    prefs = await db.get_preferences(user_id)
    return prefs or {}


# ─── SCANNING ──────────────────────────────────────────────────────────────

@app.post("/api/scan/{user_id}")
async def trigger_scan(user_id: str, background_tasks: BackgroundTasks):
    background_tasks.add_task(run_scan_for_user, user_id)
    return {"success": True, "message": "Scan started in background"}

@app.get("/api/scan/status/{user_id}")
async def get_scan_status(user_id: str):
    status = await db.get_scan_status(user_id)
    return status or {"status": "idle", "last_scan": None, "jobs_found": 0}

async def run_scan_for_user(user_id: str):
    try:
        await db.update_scan_status(user_id, "scanning")

        # Get user profile and preferences
        resume = await db.get_resume(user_id)
        prefs = await db.get_preferences(user_id)

        if not resume:
            print(f"No resume found for user {user_id}")
            await db.update_scan_status(user_id, "idle", jobs_found=0)
            return

        profile = resume.get("profile", {})
        
        # Get target roles from profile or preferences
        target_roles = []
        if prefs:
            target_roles = prefs.get("roles", [])
        if not target_roles:
            target_roles = profile.get("jobPreferences", {}).get("targetRoles", [])
        if not target_roles:
            target_roles = ["Software Engineer", "Data Scientist", "Data Analyst"]

        location = "Remote + USA"
        if prefs:
            location = prefs.get("location", "Remote + USA")

        # Get experience level from preferences
        exp_level = prefs.get("experience_level", "Entry Level") if prefs else "Entry Level"

        # 1. Scrape real jobs from Greenhouse + Lever
        print(f"🔍 Scanning for: {target_roles} | Level: {exp_level}")
        raw_jobs = await scrape_all_boards(
            roles=target_roles,
            location=location,
            experience_level=exp_level,
            days_back=2
        )

        if not raw_jobs:
            print("No jobs found in this scan")
            await db.update_scan_status(user_id, "idle", jobs_found=0)
            return

        # 2. Filter already-seen jobs
        existing_ids = await db.get_seen_job_ids(user_id)
        new_jobs = [j for j in raw_jobs if j["external_id"] not in existing_ids]
        print(f"📋 {len(new_jobs)} new jobs (filtered {len(raw_jobs) - len(new_jobs)} already seen)")

        if not new_jobs:
            await db.update_scan_status(user_id, "idle", jobs_found=0)
            return

        # 3. AI match scoring
        scored_jobs = await match_jobs_to_profile(claude, new_jobs, {**profile, "raw_text": resume.get("raw_text", "")})

        # 4. Save to database
        await db.save_jobs(user_id, scored_jobs)
        await db.update_scan_status(user_id, "idle", jobs_found=len(new_jobs))

        # 5. Log activity
        await db.log_activity(
            user_id, "scan",
            f"✅ Scan complete — found {len(new_jobs)} new jobs across Greenhouse and Lever",
            {"jobs_found": len(new_jobs), "roles": target_roles}
        )

        # 6. Auto-apply if enabled
        if prefs and prefs.get("auto_apply_enabled"):
            threshold = prefs.get("min_match_threshold", 75)
            daily_limit = prefs.get("max_applies_per_day", 25)
            todays_count = await db.get_todays_apply_count(user_id)
            remaining = daily_limit - todays_count

            high_matches = [
                j for j in scored_jobs
                if j.get("match", 0) >= threshold
                and not j.get("is_easy_apply", False)
            ][:remaining]

            print(f"⚡ Auto-applying to {len(high_matches)} high-match jobs")
            for job in high_matches:
                try:
                    from applier import auto_apply_to_job
                    await auto_apply_to_job(user_id, job, claude, prefs or {})
                except Exception as e:
                    print(f"Apply error: {e}")

    except Exception as e:
        await db.update_scan_status(user_id, "error")
        print(f"Scan error for {user_id}: {e}")
        import traceback
        traceback.print_exc()


async def match_jobs_to_profile(claude_client, jobs, profile):
    """Score each job individually against full resume using Claude AI"""
    if not jobs:
        return []

    # Get full resume text
    raw_text = profile.get("raw_text", "")
    if not raw_text:
        skills = sum(profile.get("skills", {}).values(), [])
        experience = profile.get("experience", [])
        raw_text = f"Title: {profile.get('title')}\nSkills: {', '.join(skills)}\nExperience: {len(experience)} roles"

    scored = []

    for job in jobs:
        print(f"Scoring {jobs.index(job)+1}/{len(jobs)}: {job.get('title')} @ {job.get('company')}")
        try:
            response = claude_client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=200,
                messages=[{
                    "role": "user",
                    "content": f"""You are an experienced technical recruiter. Read both the JD and candidate's resume carefully and give an honest match score from 0 to 100. Consider whether the candidate's actual experience, skills, and background genuinely qualify them for this specific role. Be realistic — for example if the job asks for 5 years of experience and the candidate has 1 year, that's a poor match regardless of skill overlap. If the role is senior and the candidate is junior, reflect that honestly in the score. Be like a ruthless but caring mentor — score honestly so the candidate only applies to jobs they genuinely have a shot at.

CANDIDATE RESUME:
{raw_text}

JOB TITLE: {job['title']}
COMPANY: {job['company']}
JOB DESCRIPTION:
{job.get('description', 'No description available')}

Return only JSON, no markdown:
{{"match": 45, "reason": "One honest sentence explaining why that score was given."}}"""
                }]
            )

            import json
            raw = response.content[0].text.replace("```json", "").replace("```", "").strip()
            result = json.loads(raw)
            scored.append({
                **job,
                "match": result.get("match", 50),
                "reason": result.get("reason", "")
            })

        except Exception as e:
            print(f"Matching error for {job.get('title')}: {e}")
            scored.append({**job, "match": 50, "reason": "AI scoring unavailable"})

        # Prevent rate limiting
        await asyncio.sleep(0.5)

    return sorted(scored, key=lambda x: x["match"], reverse=True)

async def run_scheduled_scan():
    users = await db.get_all_active_users()
    for user in users:
        await run_scan_for_user(user["id"])


# ─── JOBS ──────────────────────────────────────────────────────────────────

@app.get("/api/jobs/{user_id}")
async def get_jobs(user_id: str, status: Optional[str] = None, board: Optional[str] = None, limit: int = 200):
    jobs = await db.get_jobs(user_id, status=status, board=board, limit=limit)
    return {"jobs": jobs, "total": len(jobs)}

@app.post("/api/jobs/add-manual")
async def add_manual_job(payload: ManualJobAdd):
    job_id = await db.add_manual_job(payload.user_id, {
        "url": payload.job_url,
        "title": payload.job_title or "Unknown",
        "company": payload.company or "Unknown",
        "status": "queued"
    })
    return {"success": True, "job_id": job_id}

@app.patch("/api/jobs/{job_id}/status")
async def update_job_status(job_id: str, status: str, notes: Optional[str] = None):
    await db.update_job_status(job_id, status, notes)
    return {"success": True}


# ─── APPLICATIONS ──────────────────────────────────────────────────────────

@app.post("/api/apply")
async def apply_to_job(payload: ApplyRequest, background_tasks: BackgroundTasks):
    job = await db.get_job(payload.job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return {"success": True, "message": "Application queued"}

@app.get("/api/applications/{user_id}")
async def get_applications(user_id: str):
    apps = await db.get_applications(user_id)
    return {"applications": apps, "total": len(apps)}


# ─── COVER LETTER ──────────────────────────────────────────────────────────

@app.post("/api/cover-letter/generate")
async def generate_cover_letter(user_id: str, job_id: str):
    job = await db.get_job(job_id)
    resume = await db.get_resume(user_id)
    if not job or not resume:
        raise HTTPException(404, "Job or resume not found")
    profile = resume["profile"]
    skills = sum(profile.get("skills", {}).values(), [])
    raw_text = resume.get("raw_text", "")
    response = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=800,
        messages=[{"role": "user", "content": f"""Write a professional cover letter according to the candidate resume and Job Description. It should be specific, professional, natural with NO AI VIBE, for this exact job. Sound like the candidate is writing it themselves as a professional with their specific experience and knowledge. 3 paragraphs, under 250 words. Sound genuine not generic. Reference specific things from the job description that match the candidate actual experience. No placeholders. Do not use phrases like I am passionate about, I am excited to, I would love to, or any generic cover letter cliches. Sign with candidate name.

CANDIDATE RESUME:
{raw_text}

JOB TITLE: {job["title"]}
COMPANY: {job["company"]}
JOB DESCRIPTION:
{job.get("description", "")}"""}]
    )
    return {"cover_letter": response.content[0].text}


# ─── DASHBOARD ─────────────────────────────────────────────────────────────

@app.get("/api/dashboard/{user_id}")
async def get_dashboard(user_id: str):
    stats = await db.get_dashboard_stats(user_id)
    activity = await db.get_recent_activity(user_id, limit=10)
    return {
        "stats": stats,
        "activity": activity,
        "scan_status": await db.get_scan_status(user_id)
    }


# ─── HEALTH ────────────────────────────────────────────────────────────────

@app.delete("/api/admin/clear-jobs/{user_id}")
async def clear_jobs(user_id: str):
    await db.pool.execute("DELETE FROM jobs WHERE user_id = $1", user_id)
    return {"success": True, "message": "Jobs cleared"}

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}
