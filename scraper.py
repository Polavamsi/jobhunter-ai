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


def is_us_or_remote_location(location: str) -> bool:
    if not location:
        return True
    
    loc = location.lower().strip()
    
    US_INDICATORS = {
        "united states", "usa", "u.s.",
        "alabama", "alaska", "arizona", "arkansas",
        "california", "colorado", "connecticut", "delaware",
        "florida", "georgia", "hawaii", "idaho", "illinois",
        "indiana", "iowa", "kansas", "kentucky", "louisiana",
        "maine", "maryland", "massachusetts", "michigan",
        "minnesota", "mississippi", "missouri", "montana",
        "nebraska", "nevada", "new hampshire", "new jersey",
        "new mexico", "new york", "north carolina", "north dakota",
        "ohio", "oklahoma", "oregon", "pennsylvania",
        "rhode island", "south carolina", "south dakota",
        "tennessee", "texas", "utah", "vermont", "virginia",
        "washington", "west virginia", "wisconsin", "wyoming",
        ", al", ", ak", ", az", ", ar", ", ca", ", co",
        ", ct", ", de", ", fl", ", ga", ", hi", ", id",
        ", il", ", in", ", ia", ", ks", ", ky", ", la",
        ", me", ", md", ", ma", ", mi", ", mn", ", ms",
        ", mo", ", mt", ", ne", ", nv", ", nh", ", nj",
        ", nm", ", ny", ", nc", ", nd", ", oh", ", ok",
        ", or", ", pa", ", ri", ", sc", ", sd", ", tn",
        ", tx", ", ut", ", vt", ", va", ", wa", ", wv",
        ", wi", ", wy",
    }
    
    # Check US state/city indicators first
    if any(indicator in loc for indicator in US_INDICATORS):
        return True
    
    # Handle remote — check what comes after
    if "remote" in loc:
        remainder = loc.replace("remote", "").strip(" ()-,–")
        # Empty remainder = pure remote = allow
        if not remainder:
            return True
        # Remainder is a US indicator = allow
        if any(indicator in remainder for indicator in US_INDICATORS):
            return True
        # Remainder is something else = foreign remote = reject
        return False
    
    # No US indicator, no remote = reject
    return False

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

# Companies using Ashby ATS
ASHBY_COMPANIES = [
    # US AI/Tech companies
    "openai", "notion", "ramp", "rippling", "retool",
    "perplexity", "cursor", "glean", "harvey", "cohere",
    "mistral", "scale-ai", "weights-biases", "huggingface",
    "replit", "coreweave", "together-ai", "anyscale",
    # Indian product companies (high paying)
    "zepto", "razorpay-software", "groww", "browserstack",
    "postman", "hasura", "setu"
]

# Companies using Ashby ATS - US focused
ASHBY_COMPANIES_US = [
    "openai", "notion", "ramp", "rippling", "retool",
    "perplexity", "cursor", "glean", "harvey", "cohere",
    "replit", "coreweave", "anyscale", "together-ai",
    "weights-biases", "huggingface",
]

# Indian companies on Ashby - only high paying (25LPA+)
ASHBY_COMPANIES_INDIA = [
    "zepto", "groww", "browserstack", "postman", "hasura",
]

# Indian companies on Lever - only high paying
LEVER_COMPANIES_INDIA = [
    "razorpay", "swiggy", "cred",
]

# Indian companies on Greenhouse - only high paying
GREENHOUSE_COMPANIES_INDIA = [
    "freshworks", "meesho",
]

# Minimum salary for India roles in INR (25 LPA)
INDIA_MIN_SALARY_INR = 2500000

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


def is_india_location(location: str, secondary_locations: list = []) -> bool:
    india_keywords = ["india", "bangalore", "bengaluru", "mumbai", "hyderabad",
                      "delhi", "pune", "chennai", "noida", "gurgaon", "gurugram"]
    all_locs = [location.lower()] + [s.get("location", "").lower() for s in secondary_locations]
    return any(kw in loc for loc in all_locs for kw in india_keywords)

def passes_india_salary_filter(description: str) -> bool:
    lpa_match = re.search(r"(\d+)\s*[-–]\s*(\d+)\s*LPA", description, re.IGNORECASE)
    if lpa_match:
        max_lpa = max(int(lpa_match.group(1)), int(lpa_match.group(2)))
        return max_lpa * 100000 >= INDIA_MIN_SALARY_INR
    single_lpa = re.search(r"(\d+)\s*LPA", description, re.IGNORECASE)
    if single_lpa:
        lpa = int(single_lpa.group(1))
        return lpa * 100000 >= INDIA_MIN_SALARY_INR
    inr_match = re.search(r"[₹][\d,]+\s*[-–]\s*[₹][\d,]+", description)
    if inr_match:
        numbers = re.findall(r"\d+", inr_match.group(0).replace(",", ""))
        if numbers:
            return max(int(n) for n in numbers) >= INDIA_MIN_SALARY_INR
    return True  # No salary mentioned - pass through, company whitelist is primary filter

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
            if not is_us_or_remote_location(location):
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
            if not is_us_or_remote_location(location):
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


async def scrape_ashby(
    client: httpx.AsyncClient,
    company: str,
    target_roles: List[str],
    location_filter: str = "remote",
    experience_level: str = "Entry Level",
    india_mode: bool = False
) -> List[Dict]:
    """Fetch jobs from Ashby public API"""
    jobs = []
    try:
        url = f"https://api.ashbyhq.com/posting-api/job-board/{company}"
        response = await client.get(url, timeout=10)

        if response.status_code != 200:
            return []

        data = response.json()
        all_jobs = data.get("jobs", [])

        for job in all_jobs:
            title = job.get("title", "").strip()
            location = job.get("location", "")
            employment_type = job.get("employmentType", "")
            secondary = job.get("secondaryLocations", [])

            if not matches_roles(title, target_roles):
                continue

            if employment_type and "fulltime" not in employment_type.lower().replace("-", "").replace(" ", ""):
                continue

            if not is_appropriate_level(title, experience_level):
                continue

            job_is_india = is_india_location(location, secondary)

            if india_mode:
                if not job_is_india:
                    continue
            else:
                if job_is_india:
                    continue
                if not is_us_or_remote_location(location):
                    continue

            description = job.get("descriptionPlain", "")
            if not description:
                description = re.sub("<[^>]+>", " ", job.get("descriptionHtml", ""))
                description = re.sub(r"&[a-zA-Z#0-9]+;", " ", description)
                description = " ".join(description.split())
            description = description[:3000]

            if india_mode and not passes_india_salary_filter(description):
                continue

            salary = ""
            sal_match = re.search(r"\$[\d,]+\s*[-]\s*\$[\d,]+", description)
            if not sal_match:
                sal_match = re.search(r"(\d+)\s*[-]\s*(\d+)\s*LPA", description, re.IGNORECASE)
            if sal_match:
                salary = sal_match.group(0)

            jobs.append({
                "external_id": make_id(title, company, "ashby"),
                "title": title,
                "company": company.replace("-", " ").title(),
                "location": location or "Remote",
                "salary": salary,
                "description": description,
                "skills": [],
                "board": "Ashby",
                "url": job.get("jobUrl", ""),
                "posted": job.get("publishedAt", ""),
                "is_easy_apply": False,
                "ats": "ashby"
            })

    except Exception as e:
        print(f"Ashby error for {company}: {e}")

    return jobs

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

        # Ashby - US companies
        ashby_us_tasks = [
            scrape_ashby(client, company, roles, location_filter, experience_level, india_mode=False)
            for company in ASHBY_COMPANIES_US
        ]
        ashby_us_results = await asyncio.gather(*ashby_us_tasks, return_exceptions=True)
        for result in ashby_us_results:
            if isinstance(result, list):
                all_jobs.extend(result)

        # Ashby - India companies (high paying only)
        ashby_india_tasks = [
            scrape_ashby(client, company, roles, location_filter, experience_level, india_mode=True)
            for company in ASHBY_COMPANIES_INDIA
        ]
        ashby_india_results = await asyncio.gather(*ashby_india_tasks, return_exceptions=True)
        for result in ashby_india_results:
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
