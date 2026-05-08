"""
scraper.py — Real job scraper using Greenhouse and Lever public APIs
No bot detection, no Playwright needed for finding jobs.
"""

import httpx
import re
import asyncio
import hashlib
from typing import List, Dict
from datetime import datetime, timezone


# ─── COMPANY LISTS ───────────────────────────────────────────────────────────

# Companies using Greenhouse ATS
GREENHOUSE_COMPANIES = [
    "airbnb", "stripe", "notion", "figma", "dropbox", "coinbase",
    "robinhood", "brex", "plaid", "retool", "airtable", "lattice",
    "scale-ai", "anthropic", "openai", "datadog", "hashicorp",
    "mongodb", "elastic", "confluent", "dbt-labs", "hex",
    "benchling", "carta", "gusto", "rippling", "deel", "remote",
    "checkr", "gem", "greenhouse", "lever", "workday", "zendesk",
    "twilio", "sendgrid", "segment", "amplitude", "mixpanel",
    "looker", "periscope", "mode", "sigma", "preset", "metabase",
    "hightouch", "census", "fivetran", "airbyte", "dagster",
    "prefect", "astronomer", "great-expectations", "monte-carlo"
]

# Companies using Lever ATS
LEVER_COMPANIES = [
    "netflix", "shopify", "reddit", "spotify", "discord", "canva",
    "figma", "linear", "vercel", "supabase", "planetscale", "railway",
    "fly", "render", "cloudflare", "fastly", "netlify", "heroku",
    "twitch", "roblox", "unity", "epic-games", "riot-games",
    "duolingo", "coursera", "udemy", "masterclass", "kahoot",
    "hubspot", "intercom", "drift", "calendly", "loom", "miro",
    "asana", "monday", "clickup", "notion", "coda", "quip",
    "salesforce", "servicenow", "workday", "oracle", "sap"
]

# Keywords to match against user's target roles
ROLE_KEYWORDS = {
    "data scientist": ["data scientist", "data science", "ml scientist", "research scientist"],
    "data analyst": ["data analyst", "analytics engineer", "business analyst", "bi analyst"],
    "software engineer": ["software engineer", "software developer", "swe", "backend engineer", "frontend engineer", "full stack", "fullstack"],
    "ml engineer": ["machine learning engineer", "ml engineer", "mlops", "ai engineer"],
    "data engineer": ["data engineer", "etl engineer", "analytics engineer", "pipeline engineer"],
    "full stack developer": ["full stack", "fullstack", "full-stack", "web developer"],
}


def make_id(title: str, company: str, board: str) -> str:
    return hashlib.md5(f"{title.lower()}{company.lower()}{board}".encode()).hexdigest()


def matches_roles(job_title: str, target_roles: List[str]) -> bool:
    """Check if job title matches any of the user's target roles"""
    title_lower = job_title.lower()
    for role in target_roles:
        role_lower = role.lower()
        keywords = ROLE_KEYWORDS.get(role_lower, [role_lower])
        if any(kw in title_lower for kw in keywords):
            return True
    return False


def is_full_time(job: Dict) -> bool:
    """Check if job is full-time"""
    # Check employment type fields
    employment = str(job.get("employment_type", "")).lower()
    title = str(job.get("title", "")).lower()
    
    # Skip obvious non-full-time
    skip_words = ["intern", "internship", "contract", "contractor", "part-time", 
                  "part time", "temporary", "temp ", "freelance", "c2c", "corp-to-corp"]
    
    for word in skip_words:
        if word in title or word in employment:
            return False
    return True


def is_appropriate_level(title: str, exp_level: str) -> bool:
    title_lower = title.lower()
    senior_words = ['senior', 'staff', 'principal', 'lead', 'director', 'manager', 'head of', 'vp ', 'vice president']
    mid_words = ['staff', 'principal', 'director', 'manager', 'head of', 'vp ', 'vice president']
    if exp_level == 'Entry Level':
        return not any(w in title_lower for w in senior_words)
    elif exp_level == 'Mid Level':
        return not any(w in title_lower for w in mid_words)
    else:
        return True

# ─── GREENHOUSE API ───────────────────────────────────────────────────────────

async def scrape_greenhouse(
    client: httpx.AsyncClient,
    company: str,
    target_roles: List[str],
    location_filter: str = "remote",
    experience_level: str = "Entry Level"
) -> List[Dict]:
    """Fetch jobs from Greenhouse public API"""
    jobs = []
    try:
        url = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs"
        response = await client.get(url, timeout=10)
        
        if response.status_code != 200:
            return []
        
        data = response.json()
        all_jobs = data.get("jobs", [])
        
        for job in all_jobs:
            title = job.get("title", "")
            location = job.get("location", {}).get("name", "")
            
            # Filter by role match
            if not matches_roles(title, target_roles):
                continue
            
            # Filter by location (remote or US)
            location_lower = location.lower()
            is_remote = "remote" in location_lower
            is_us = any(state in location_lower for state in [
                "new york", "san francisco", "seattle", "austin", "boston",
                "chicago", "los angeles", "denver", "atlanta", ", ny", ", ca",
                ", tx", ", wa", ", ma", ", il", "united states", "usa", "us"
            ])
            
            if location_filter == "remote" and not (is_remote or is_us):
                continue
            
            # Filter full-time
            if not is_full_time({"title": title}):
                continue

            # Filter by experience level
            if not is_appropriate_level(title, experience_level):
                continue
            
            # Fetch full job description from detail endpoint
            full_desc = ""
            salary = ""
            job_id = job.get("id", "")
            try:
                detail_url = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs/{job_id}"
                detail_res = await client.get(detail_url, timeout=10)
                if detail_res.status_code == 200:
                    detail = detail_res.json()
                    raw = detail.get("content", "")
                    full_desc = re.sub(r"<[^>]+>", " ", raw)
                    full_desc = re.sub(r"&[a-zA-Z#0-9]+;", " ", full_desc)
                    full_desc = re.sub(r"\s+", " ", full_desc)
                    full_desc = full_desc.replace("  ", " ").strip()[:3000]
                    salary_match = re.search(r"\$[\d,]+\s*[-–]\s*\$[\d,]+", full_desc)
                    if salary_match:
                        salary = salary_match.group(0)
            except Exception as de:
                print(f"Could not fetch details for {title}: {de}")

            jobs.append({
                "external_id": make_id(title, company, "greenhouse"),
                "title": title,
                "company": company.replace("-", " ").title(),
                "location": location or "Remote",
                "salary": salary,
                "description": full_desc,
                "skills": [],
                "board": "Greenhouse",
                "url": job.get("absolute_url", ""),
                "posted": job.get("updated_at", ""),
                "is_easy_apply": False,
                "ats": "greenhouse"
            })
    
    except Exception as e:
        print(f"Greenhouse error for {company}: {e}")
    
    return jobs


# ─── LEVER API ────────────────────────────────────────────────────────────────

async def scrape_lever(
    client: httpx.AsyncClient,
    company: str,
    target_roles: List[str],
    location_filter: str = "remote",
    experience_level: str = "Entry Level"
) -> List[Dict]:
    """Fetch jobs from Lever public API"""
    jobs = []
    try:
        url = f"https://api.lever.co/v0/postings/{company}"
        response = await client.get(url, timeout=10)
        
        if response.status_code != 200:
            return []
        
        all_jobs = response.json()
        
        for job in all_jobs:
            title = job.get("text", "")
            categories = job.get("categories", {})
            location = categories.get("location", "")
            commitment = categories.get("commitment", "")
            
            # Filter by role match
            if not matches_roles(title, target_roles):
                continue
            
            # Filter full-time
            if commitment and any(word in commitment.lower() for word in 
                                  ["intern", "contract", "part-time", "part time"]):
                continue
            
            # Filter by location
            location_lower = location.lower()
            is_remote = "remote" in location_lower
            is_us = any(state in location_lower for state in [
                "new york", "san francisco", "seattle", "austin", "boston",
                "chicago", "los angeles", "denver", "united states", "usa"
            ])
            
            if location_filter == "remote" and not (is_remote or is_us):
                continue
            
            # Build description from job lists
            description = job.get("descriptionPlain", "")
            # Add lists content (What You'll Do, Who You Are)
            lists = job.get("lists", [])
            for lst in lists:
                content = re.sub("<[^>]+>", " ", lst.get("content", ""))
                description += f"\n{lst.get('text', '')}: {content}"
            description = description[:3000]
            jobs.append({
                "external_id": make_id(title, company, "lever"),
                "title": title,
                "company": company.replace("-", " ").title(),
                "location": location or "Remote",
                "salary": "",
                "description": description,
                "skills": [],
                "board": "Lever",
                "url": job.get("hostedUrl", ""),
                "posted": str(job.get("createdAt", "")),
                "is_easy_apply": False,
                "ats": "lever"
            })
    
    except Exception as e:
        print(f"Lever error for {company}: {e}")
    
    return jobs


# ─── MAIN SCRAPER ─────────────────────────────────────────────────────────────

async def scrape_all_boards(
    roles: List[str],
    location: str = "Remote + USA",
    experience_level: str = "Entry Level",
    days_back: int = 2
) -> List[Dict]:
    """
    Main entry point — scrapes Greenhouse and Lever for all companies.
    Returns deduplicated list of matching jobs.
    """
    all_jobs = []
    location_filter = "remote"  # Default to remote + US

    async with httpx.AsyncClient() as client:
        # Run Greenhouse scrapes concurrently
        greenhouse_tasks = [
            scrape_greenhouse(client, company, roles, location_filter, experience_level)
            for company in GREENHOUSE_COMPANIES
        ]
        greenhouse_results = await asyncio.gather(*greenhouse_tasks, return_exceptions=True)
        for result in greenhouse_results:
            if isinstance(result, list):
                all_jobs.extend(result)

        # Run Lever scrapes concurrently
        lever_tasks = [
            scrape_lever(client, company, roles, location_filter, experience_level)
            for company in LEVER_COMPANIES
        ]
        lever_results = await asyncio.gather(*lever_tasks, return_exceptions=True)
        for result in lever_results:
            if isinstance(result, list):
                all_jobs.extend(result)

    # Deduplicate by external_id
    seen = set()
    unique_jobs = []
    for job in all_jobs:
        if job["external_id"] not in seen:
            seen.add(job["external_id"])
            unique_jobs.append(job)

    print(f"✅ Scraped {len(unique_jobs)} unique jobs matching {roles}")
    return unique_jobs
