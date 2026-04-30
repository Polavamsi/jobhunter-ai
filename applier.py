"""
matcher.py — AI-powered job matching using Claude
applier.py — Playwright-based auto-apply engine
"""

# ════════════════════════════════════════════════════════
# MATCHER
# ════════════════════════════════════════════════════════

import json
import asyncio
from typing import List, Dict
from playwright.async_api import async_playwright
from database import db


async def match_jobs_to_profile(claude_client, jobs: List[Dict], profile: Dict) -> List[Dict]:
    """Score each job against the user's profile using Claude AI"""

    if not jobs:
        return []

    # Batch jobs into groups of 10 to stay within token limits
    batches = [jobs[i:i+10] for i in range(0, len(jobs), 10)]
    scored = []

    for batch in batches:
        jobs_text = "\n\n".join([
            f"Job {i+1} (id={j['external_id']}):\nTitle: {j['title']}\nCompany: {j['company']}\nDescription: {j.get('description','N/A')[:300]}\nSkills: {', '.join(j.get('skills', []))}"
            for i, j in enumerate(batch)
        ])

        skills = sum(profile.get("skills", {}).values(), [])
        experience = profile.get("experience", [])

        try:
            response = claude_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1000,
                messages=[{
                    "role": "user",
                    "content": f"""Score these jobs against this candidate. Return ONLY a JSON array, no markdown.

Candidate:
- Title: {profile.get('title')}
- Skills: {', '.join(skills)}
- Experience: {json.dumps(experience)}
- Certifications: {', '.join(profile.get('certifications', []))}

Jobs:
{jobs_text}

Return: [{{"external_id":"...","match":85,"reason":"Short 1-sentence reason"}}]
Score 0-100 based on skill overlap and role fit. Be realistic for entry-level."""
                }]
            )

            raw = response.content[0].text.replace("```json","").replace("```","").strip()
            scores = json.loads(raw)
            score_map = {s["external_id"]: s for s in scores}

            for j in batch:
                score_data = score_map.get(j["external_id"], {})
                scored.append({
                    **j,
                    "match": score_data.get("match", 50),
                    "reason": score_data.get("reason", ""),
                })

        except Exception as e:
            print(f"Matching error: {e}")
            for j in batch:
                scored.append({**j, "match": 50, "reason": "AI scoring unavailable"})

    return sorted(scored, key=lambda x: x["match"], reverse=True)


# ════════════════════════════════════════════════════════
# AUTO-APPLIER
# ════════════════════════════════════════════════════════

async def auto_apply_to_job(user_id: str, job: Dict, claude_client, prefs: Dict,
                             override_cover_letter: str = None):
    """
    Attempt to auto-apply to a job using Playwright browser automation.
    Handles LinkedIn Easy Apply, Indeed Apply, and generic form filling.
    """
    board = job.get("board", "").lower()
    job_url = job.get("url", "")
    job_id = job.get("id")

    if not job_url:
        await db.save_application(user_id, job_id, "failed", error="No URL available")
        return

    try:
        # Generate cover letter if enabled
        cover_letter = override_cover_letter
        if not cover_letter and prefs.get("generate_cover_letters"):
            cover_letter = await _generate_cover_letter(claude_client, job, user_id)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = await browser.new_context()
            page = await context.new_page()

            success = False

            if "linkedin" in board:
                success = await _apply_linkedin(page, job, cover_letter, prefs)
            elif "indeed" in board:
                success = await _apply_indeed(page, job, cover_letter, prefs)
            else:
                # Generic: open page and fill what we can
                success = await _apply_generic(page, job, cover_letter, prefs)

            await browser.close()

        status = "applied" if success else "failed"
        error = None if success else "Could not complete application automatically"

        await db.save_application(user_id, job_id, status, cover_letter, error)
        await db.log_activity(user_id, "application",
            f"{'✅ Applied' if success else '❌ Failed'}: {job['title']} at {job['company']} via {job.get('board')}",
            {"job_id": job_id, "match": job.get("match")}
        )

    except Exception as e:
        await db.save_application(user_id, job_id, "failed", error=str(e))
        print(f"Apply error for {job.get('title')}: {e}")


async def _generate_cover_letter(claude_client, job: Dict, user_id: str) -> str:
    """Generate a personalized cover letter using Claude"""
    resume = await db.get_resume(user_id)
    profile = resume.get("profile", {}) if resume else {}
    skills = sum(profile.get("skills", {}).values(), [])

    try:
        response = claude_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{
                "role": "user",
                "content": f"""Write a professional cover letter. 3 paragraphs, under 200 words. No placeholders.

Candidate: {profile.get('name', 'Vamsi Krishna Pola')}
Skills: {', '.join(skills[:12])}
Experience: {json.dumps(profile.get('experience', [])[:2])}

Job: {job['title']} at {job['company']}
Description: {job.get('description', '')[:300]}"""
            }]
        )
        return response.content[0].text
    except Exception:
        return f"Dear Hiring Team,\n\nI am excited to apply for the {job['title']} position at {job['company']}. My background in data science and Python development aligns well with your requirements.\n\nThank you for your consideration.\n\nSincerely,\n{profile.get('name', 'Vamsi Krishna Pola')}"


async def _apply_linkedin(page, job: Dict, cover_letter: str, prefs: Dict) -> bool:
    """Handle LinkedIn Easy Apply flow"""
    try:
        await page.goto(job["url"], timeout=20000)
        await page.wait_for_load_state("networkidle")

        # Click Easy Apply button
        easy_apply = await page.query_selector("button.jobs-apply-button")
        if not easy_apply:
            return False
        await easy_apply.click()
        await page.wait_for_timeout(2000)

        # Fill phone if requested
        phone_field = await page.query_selector("input[id*='phoneNumber']")
        if phone_field:
            await phone_field.fill(prefs.get("phone", ""))

        # Fill cover letter if text area present
        cl_field = await page.query_selector("textarea[id*='coverLetter']")
        if cl_field and cover_letter:
            await cl_field.fill(cover_letter)

        # Click through multi-step form (Next → Next → Submit)
        for _ in range(5):
            next_btn = await page.query_selector("button[aria-label='Continue to next step']")
            submit_btn = await page.query_selector("button[aria-label='Submit application']")

            if submit_btn:
                await submit_btn.click()
                await page.wait_for_timeout(2000)
                return True
            elif next_btn:
                await next_btn.click()
                await page.wait_for_timeout(1500)
            else:
                break

        return False
    except Exception as e:
        print(f"LinkedIn apply error: {e}")
        return False


async def _apply_indeed(page, job: Dict, cover_letter: str, prefs: Dict) -> bool:
    """Handle Indeed Apply flow"""
    try:
        await page.goto(job["url"], timeout=20000)
        await page.wait_for_load_state("networkidle")

        apply_btn = await page.query_selector("button#indeedApplyButton, a#applyButtonLinkContainer")
        if not apply_btn:
            return False
        await apply_btn.click()
        await page.wait_for_timeout(2000)

        # Fill cover letter
        cl_field = await page.query_selector("textarea[name*='cover']")
        if cl_field and cover_letter:
            await cl_field.fill(cover_letter)

        # Submit
        submit = await page.query_selector("button[type='submit']")
        if submit:
            await submit.click()
            await page.wait_for_timeout(2000)
            return True

        return False
    except Exception as e:
        print(f"Indeed apply error: {e}")
        return False


async def _apply_generic(page, job: Dict, cover_letter: str, prefs: Dict) -> bool:
    """
    Generic fallback: open the job URL, try to find and fill standard form fields.
    Works for many company career portals.
    """
    try:
        await page.goto(job["url"], timeout=20000)
        await page.wait_for_load_state("networkidle")

        # Look for common apply buttons
        selectors = [
            "a[href*='apply']", "button:has-text('Apply')",
            "a:has-text('Apply Now')", "button:has-text('Apply Now')",
            "a:has-text('Apply for this job')"
        ]
        for sel in selectors:
            btn = await page.query_selector(sel)
            if btn:
                await btn.click()
                await page.wait_for_timeout(2000)
                break

        # Fill cover letter if field found
        cl_field = await page.query_selector("textarea[name*='cover'], textarea[placeholder*='cover']")
        if cl_field and cover_letter:
            await cl_field.fill(cover_letter)

        # This is a best-effort — log it as "pending review" rather than auto-submitted
        return False  # Mark as pending, not fully applied
    except Exception as e:
        print(f"Generic apply error: {e}")
        return False
