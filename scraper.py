"""
Job Scraper — Playwright-based scraper for all 10 job boards
Searches for recently posted jobs matching the user's target roles
"""

from playwright.async_api import async_playwright
from typing import List, Dict
import asyncio
import hashlib
import re
from datetime import datetime


BOARDS = [
    "linkedin",
    "indeed",
    "glassdoor",
    "ziprecruiter",
    "dice",
    "monster",
    "angellist",
    "naukri",
    "careerbuilder",
    "simplyhired",
]


async def scrape_all_boards(roles: List[str], location: str, days_back: int = 2) -> List[Dict]:
    """Scrape all job boards and return combined, deduplicated job list"""
    all_jobs = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )

        for role in roles:
            tasks = [
                scrape_linkedin(context, role, location, days_back),
                scrape_indeed(context, role, location, days_back),
                scrape_glassdoor(context, role, location, days_back),
                scrape_ziprecruiter(context, role, location, days_back),
                scrape_dice(context, role, location, days_back),
                scrape_monster(context, role, location, days_back),
                scrape_angellist(context, role, location, days_back),
                scrape_simplyhired(context, role, location, days_back),
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, list):
                    all_jobs.extend(r)

        await browser.close()

    # Deduplicate by title+company
    seen = set()
    unique = []
    for j in all_jobs:
        key = f"{j['title'].lower()}_{j['company'].lower()}"
        if key not in seen:
            seen.add(key)
            unique.append(j)

    return unique


def make_id(title: str, company: str, board: str) -> str:
    return hashlib.md5(f"{title}{company}{board}".encode()).hexdigest()


# ─── LINKEDIN ───────────────────────────────────────────────────────────────

async def scrape_linkedin(ctx, role: str, location: str, days_back: int) -> List[Dict]:
    jobs = []
    try:
        page = await ctx.new_page()
        loc = "Remote" if "remote" in location.lower() else location
        url = f"https://www.linkedin.com/jobs/search/?keywords={role.replace(' ', '%20')}&location={loc}&f_TPR=r{days_back * 86400}&f_E=1,2"
        await page.goto(url, timeout=20000)
        await page.wait_for_selector(".job-search-card", timeout=8000)

        cards = await page.query_selector_all(".job-search-card")
        for card in cards[:15]:
            try:
                title = await card.query_selector(".base-search-card__title")
                company = await card.query_selector(".base-search-card__subtitle")
                loc_el = await card.query_selector(".job-search-card__location")
                link = await card.query_selector("a.base-card__full-link")

                t = (await title.inner_text()).strip() if title else ""
                c = (await company.inner_text()).strip() if company else ""
                l = (await loc_el.inner_text()).strip() if loc_el else ""
                href = await link.get_attribute("href") if link else ""

                if t and c:
                    jobs.append({
                        "external_id": make_id(t, c, "linkedin"),
                        "title": t, "company": c, "location": l,
                        "board": "LinkedIn", "url": href,
                        "salary": "", "description": "", "skills": [],
                        "posted": "Recent"
                    })
            except Exception:
                continue

        await page.close()
    except Exception as e:
        print(f"LinkedIn scrape error: {e}")
    return jobs


# ─── INDEED ─────────────────────────────────────────────────────────────────

async def scrape_indeed(ctx, role: str, location: str, days_back: int) -> List[Dict]:
    jobs = []
    try:
        page = await ctx.new_page()
        loc = "remote" if "remote" in location.lower() else location.replace(" ", "+")
        url = f"https://www.indeed.com/jobs?q={role.replace(' ', '+')}&l={loc}&fromage={days_back}"
        await page.goto(url, timeout=20000)
        await page.wait_for_selector(".job_seen_beacon", timeout=8000)

        cards = await page.query_selector_all(".job_seen_beacon")
        for card in cards[:15]:
            try:
                title = await card.query_selector("h2.jobTitle span")
                company = await card.query_selector("[data-testid='company-name']")
                loc_el = await card.query_selector("[data-testid='text-location']")
                salary_el = await card.query_selector(".salary-snippet-container")
                link = await card.query_selector("a.jcs-JobTitle")

                t = (await title.inner_text()).strip() if title else ""
                c = (await company.inner_text()).strip() if company else ""
                l = (await loc_el.inner_text()).strip() if loc_el else ""
                s = (await salary_el.inner_text()).strip() if salary_el else ""
                href = "https://indeed.com" + (await link.get_attribute("href") if link else "")

                if t and c:
                    jobs.append({
                        "external_id": make_id(t, c, "indeed"),
                        "title": t, "company": c, "location": l, "salary": s,
                        "board": "Indeed", "url": href,
                        "description": "", "skills": [], "posted": "Recent"
                    })
            except Exception:
                continue

        await page.close()
    except Exception as e:
        print(f"Indeed scrape error: {e}")
    return jobs


# ─── GLASSDOOR ──────────────────────────────────────────────────────────────

async def scrape_glassdoor(ctx, role: str, location: str, days_back: int) -> List[Dict]:
    jobs = []
    try:
        page = await ctx.new_page()
        url = f"https://www.glassdoor.com/Job/jobs.htm?sc.keyword={role.replace(' ', '+')}&locT=C&locId=1&fromAge={days_back}"
        await page.goto(url, timeout=20000)
        await page.wait_for_selector("[data-test='jobListing']", timeout=8000)

        cards = await page.query_selector_all("[data-test='jobListing']")
        for card in cards[:12]:
            try:
                title = await card.query_selector("[data-test='job-title']")
                company = await card.query_selector("[data-test='employer-name']")
                loc_el = await card.query_selector("[data-test='emp-location']")
                salary_el = await card.query_selector("[data-test='detailSalary']")

                t = (await title.inner_text()).strip() if title else ""
                c = (await company.inner_text()).strip() if company else ""
                l = (await loc_el.inner_text()).strip() if loc_el else ""
                s = (await salary_el.inner_text()).strip() if salary_el else ""

                if t and c:
                    jobs.append({
                        "external_id": make_id(t, c, "glassdoor"),
                        "title": t, "company": c, "location": l, "salary": s,
                        "board": "Glassdoor", "url": "",
                        "description": "", "skills": [], "posted": "Recent"
                    })
            except Exception:
                continue

        await page.close()
    except Exception as e:
        print(f"Glassdoor scrape error: {e}")
    return jobs


# ─── ZIPRECRUITER ────────────────────────────────────────────────────────────

async def scrape_ziprecruiter(ctx, role: str, location: str, days_back: int) -> List[Dict]:
    jobs = []
    try:
        page = await ctx.new_page()
        url = f"https://www.ziprecruiter.com/Jobs/{role.replace(' ', '-')}?days={days_back}"
        await page.goto(url, timeout=20000)
        await page.wait_for_selector(".job_content", timeout=8000)

        cards = await page.query_selector_all(".job_content")
        for card in cards[:12]:
            try:
                title = await card.query_selector(".job_title")
                company = await card.query_selector(".hiring_company_text")
                loc_el = await card.query_selector(".location")
                salary_el = await card.query_selector(".salary")
                link = await card.query_selector("a.job_link")

                t = (await title.inner_text()).strip() if title else ""
                c = (await company.inner_text()).strip() if company else ""
                l = (await loc_el.inner_text()).strip() if loc_el else ""
                s = (await salary_el.inner_text()).strip() if salary_el else ""
                href = await link.get_attribute("href") if link else ""

                if t and c:
                    jobs.append({
                        "external_id": make_id(t, c, "ziprecruiter"),
                        "title": t, "company": c, "location": l, "salary": s,
                        "board": "ZipRecruiter", "url": href,
                        "description": "", "skills": [], "posted": "Recent"
                    })
            except Exception:
                continue

        await page.close()
    except Exception as e:
        print(f"ZipRecruiter scrape error: {e}")
    return jobs


# ─── DICE ───────────────────────────────────────────────────────────────────

async def scrape_dice(ctx, role: str, location: str, days_back: int) -> List[Dict]:
    jobs = []
    try:
        page = await ctx.new_page()
        url = f"https://www.dice.com/jobs?q={role.replace(' ', '+')}&location=Remote&datePosted={days_back}d"
        await page.goto(url, timeout=20000)
        await page.wait_for_selector("dhi-search-card", timeout=8000)

        cards = await page.query_selector_all("dhi-search-card")
        for card in cards[:12]:
            try:
                title = await card.query_selector("a.card-title-link")
                company = await card.query_selector(".card-company")
                loc_el = await card.query_selector(".search-result-location")

                t = (await title.inner_text()).strip() if title else ""
                c = (await company.inner_text()).strip() if company else ""
                l = (await loc_el.inner_text()).strip() if loc_el else ""
                href = await title.get_attribute("href") if title else ""

                if t and c:
                    jobs.append({
                        "external_id": make_id(t, c, "dice"),
                        "title": t, "company": c, "location": l, "salary": "",
                        "board": "Dice", "url": href,
                        "description": "", "skills": [], "posted": "Recent"
                    })
            except Exception:
                continue

        await page.close()
    except Exception as e:
        print(f"Dice scrape error: {e}")
    return jobs


# ─── MONSTER ────────────────────────────────────────────────────────────────

async def scrape_monster(ctx, role: str, location: str, days_back: int) -> List[Dict]:
    jobs = []
    try:
        page = await ctx.new_page()
        url = f"https://www.monster.com/jobs/search?q={role.replace(' ', '+')}&where=Remote&tm={days_back}"
        await page.goto(url, timeout=20000)
        await page.wait_for_selector(".job-cardstyle__JobCardComponent", timeout=8000)

        cards = await page.query_selector_all(".job-cardstyle__JobCardComponent")
        for card in cards[:12]:
            try:
                title = await card.query_selector("h3.job-cardstyle__JobTitle")
                company = await card.query_selector(".job-cardstyle__CompanyName")
                loc_el = await card.query_selector(".job-cardstyle__Location")
                link = await card.query_selector("a")

                t = (await title.inner_text()).strip() if title else ""
                c = (await company.inner_text()).strip() if company else ""
                l = (await loc_el.inner_text()).strip() if loc_el else ""
                href = await link.get_attribute("href") if link else ""

                if t and c:
                    jobs.append({
                        "external_id": make_id(t, c, "monster"),
                        "title": t, "company": c, "location": l, "salary": "",
                        "board": "Monster", "url": href,
                        "description": "", "skills": [], "posted": "Recent"
                    })
            except Exception:
                continue

        await page.close()
    except Exception as e:
        print(f"Monster scrape error: {e}")
    return jobs


# ─── ANGELLIST / WELLFOUND ──────────────────────────────────────────────────

async def scrape_angellist(ctx, role: str, location: str, days_back: int) -> List[Dict]:
    jobs = []
    try:
        page = await ctx.new_page()
        url = f"https://wellfound.com/jobs?q={role.replace(' ', '+')}&remote=true"
        await page.goto(url, timeout=20000)
        await page.wait_for_selector("[data-test='StartupResult']", timeout=8000)

        cards = await page.query_selector_all("[data-test='JobListing']")
        for card in cards[:12]:
            try:
                title = await card.query_selector("a[data-test='job-title']")
                company = await card.query_selector("[data-test='company-name']")
                loc_el = await card.query_selector("[data-test='location']")
                salary_el = await card.query_selector("[data-test='salary']")

                t = (await title.inner_text()).strip() if title else ""
                c = (await company.inner_text()).strip() if company else ""
                l = (await loc_el.inner_text()).strip() if loc_el else "Remote"
                s = (await salary_el.inner_text()).strip() if salary_el else ""
                href = "https://wellfound.com" + (await title.get_attribute("href") if title else "")

                if t and c:
                    jobs.append({
                        "external_id": make_id(t, c, "angellist"),
                        "title": t, "company": c, "location": l, "salary": s,
                        "board": "AngelList", "url": href,
                        "description": "", "skills": [], "posted": "Recent"
                    })
            except Exception:
                continue

        await page.close()
    except Exception as e:
        print(f"AngelList scrape error: {e}")
    return jobs


# ─── SIMPLYHIRED ─────────────────────────────────────────────────────────────

async def scrape_simplyhired(ctx, role: str, location: str, days_back: int) -> List[Dict]:
    jobs = []
    try:
        page = await ctx.new_page()
        url = f"https://www.simplyhired.com/search?q={role.replace(' ', '+')}&l=remote&date={days_back}d"
        await page.goto(url, timeout=20000)
        await page.wait_for_selector("[data-testid='searchSerpJob']", timeout=8000)

        cards = await page.query_selector_all("[data-testid='searchSerpJob']")
        for card in cards[:12]:
            try:
                title = await card.query_selector("h3 a")
                company = await card.query_selector(".css-1h7lukg")
                loc_el = await card.query_selector(".css-1t92pv")
                salary_el = await card.query_selector(".css-1udmfvc")

                t = (await title.inner_text()).strip() if title else ""
                c = (await company.inner_text()).strip() if company else ""
                l = (await loc_el.inner_text()).strip() if loc_el else ""
                s = (await salary_el.inner_text()).strip() if salary_el else ""
                href = "https://simplyhired.com" + (await title.get_attribute("href") if title else "")

                if t and c:
                    jobs.append({
                        "external_id": make_id(t, c, "simplyhired"),
                        "title": t, "company": c, "location": l, "salary": s,
                        "board": "SimplyHired", "url": href,
                        "description": "", "skills": [], "posted": "Recent"
                    })
            except Exception:
                continue

        await page.close()
    except Exception as e:
        print(f"SimplyHired scrape error: {e}")
    return jobs
