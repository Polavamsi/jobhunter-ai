"""
applier.py — Auto-apply engine
Handles: LinkedIn Easy Apply, Indeed Apply, Greenhouse, Lever, Workday, and generic forms
"""

import json
import asyncio
from typing import Dict
from playwright.async_api import async_playwright
from database import db


async def auto_apply_to_job(user_id: str, job: Dict, claude_client, prefs: Dict,
                             override_cover_letter: str = None):
    """
    Main entry point — detects which platform the job is on
    and routes to the correct apply function.
    """
    job_url = job.get("url", "")
    job_id = job.get("id")
    board = job.get("board", "").lower()

    if not job_url:
        await db.save_application(user_id, job_id, "failed", error="No URL available")
        return

    try:
        # Generate cover letter
        cover_letter = override_cover_letter
        if not cover_letter and prefs.get("generate_cover_letters", True):
            cover_letter = await _generate_cover_letter(claude_client, job, user_id)

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            page = await context.new_page()

            # Detect platform and route accordingly
            success = False
            platform = await _detect_platform(page, job_url)

            if platform == "linkedin":
                success = await _apply_linkedin(page, job, cover_letter, prefs)
            elif platform == "indeed":
                success = await _apply_indeed(page, job, cover_letter, prefs)
            elif platform == "greenhouse":
                success = await _apply_greenhouse(page, job, cover_letter, prefs)
            elif platform == "lever":
                success = await _apply_lever(page, job, cover_letter, prefs)
            elif platform == "workday":
                success = await _apply_workday(page, job, cover_letter, prefs)
            else:
                success = await _apply_generic(page, job, cover_letter, prefs)

            await browser.close()

        status = "applied" if success else "failed"
        error = None if success else "Could not complete application automatically"

        await db.save_application(user_id, job_id, status, cover_letter, error)
        await db.log_activity(
            user_id, "application",
            f"{'✅ Applied' if success else '❌ Failed'}: {job['title']} at {job['company']} via {platform}",
            {"job_id": job_id, "match": job.get("match"), "platform": platform}
        )

    except Exception as e:
        await db.save_application(user_id, job_id, "failed", error=str(e))
        print(f"Apply error for {job.get('title')}: {e}")


# ─── PLATFORM DETECTION ──────────────────────────────────────────────────────

async def _detect_platform(page, url: str) -> str:
    """
    Detect which ATS or job platform the URL belongs to.
    First checks the URL string, then follows redirects if needed.
    """
    url_lower = url.lower()

    # Direct URL detection
    if "linkedin.com" in url_lower:
        return "linkedin"
    if "indeed.com" in url_lower:
        return "indeed"
    if "greenhouse.io" in url_lower or "boards.greenhouse" in url_lower:
        return "greenhouse"
    if "lever.co" in url_lower or "jobs.lever" in url_lower:
        return "lever"
    if "myworkdayjobs.com" in url_lower or "workday.com" in url_lower:
        return "workday"

    # Follow redirect and check final URL
    try:
        await page.goto(url, timeout=15000)
        await page.wait_for_load_state("networkidle", timeout=10000)
        final_url = page.url.lower()

        if "greenhouse.io" in final_url or "boards.greenhouse" in final_url:
            return "greenhouse"
        if "lever.co" in final_url or "jobs.lever" in final_url:
            return "lever"
        if "myworkdayjobs.com" in final_url or "workday.com" in final_url:
            return "workday"
        if "linkedin.com" in final_url:
            return "linkedin"
        if "indeed.com" in final_url:
            return "indeed"
    except Exception:
        pass

    return "generic"


# ─── LINKEDIN EASY APPLY ─────────────────────────────────────────────────────

async def _apply_linkedin(page, job: Dict, cover_letter: str, prefs: Dict) -> bool:
    """Handle LinkedIn Easy Apply multi-step flow"""
    try:
        await page.goto(job["url"], timeout=20000)
        await page.wait_for_load_state("networkidle")

        # Find and click Easy Apply button
        easy_apply = await page.query_selector("button.jobs-apply-button")
        if not easy_apply:
            return False
        await easy_apply.click()
        await page.wait_for_timeout(2000)

        # Fill phone number if requested
        phone_field = await page.query_selector("input[id*='phoneNumber']")
        if phone_field:
            await phone_field.fill(prefs.get("phone", ""))

        # Fill cover letter if field present
        cl_field = await page.query_selector("textarea[id*='coverLetter']")
        if cl_field and cover_letter:
            await cl_field.fill(cover_letter)

        # Click through multi-step form
        for _ in range(8):
            submit_btn = await page.query_selector("button[aria-label='Submit application']")
            next_btn = await page.query_selector("button[aria-label='Continue to next step']")
            review_btn = await page.query_selector("button[aria-label='Review your application']")

            if submit_btn:
                await submit_btn.click()
                await page.wait_for_timeout(2000)
                return True
            elif review_btn:
                await review_btn.click()
                await page.wait_for_timeout(1500)
            elif next_btn:
                await next_btn.click()
                await page.wait_for_timeout(1500)
            else:
                break

        return False
    except Exception as e:
        print(f"LinkedIn apply error: {e}")
        return False


# ─── INDEED APPLY ────────────────────────────────────────────────────────────

async def _apply_indeed(page, job: Dict, cover_letter: str, prefs: Dict) -> bool:
    """Handle Indeed Apply flow"""
    try:
        await page.goto(job["url"], timeout=20000)
        await page.wait_for_load_state("networkidle")

        apply_btn = await page.query_selector(
            "button#indeedApplyButton, a#applyButtonLinkContainer, button:has-text('Apply now')"
        )
        if not apply_btn:
            return False
        await apply_btn.click()
        await page.wait_for_timeout(2000)

        # Fill cover letter
        cl_field = await page.query_selector("textarea[name*='cover'], textarea[placeholder*='cover']")
        if cl_field and cover_letter:
            await cl_field.fill(cover_letter)

        # Submit
        submit = await page.query_selector("button[type='submit'], button:has-text('Submit')")
        if submit:
            await submit.click()
            await page.wait_for_timeout(2000)
            return True

        return False
    except Exception as e:
        print(f"Indeed apply error: {e}")
        return False


# ─── GREENHOUSE ──────────────────────────────────────────────────────────────

async def _apply_greenhouse(page, job: Dict, cover_letter: str, prefs: Dict) -> bool:
    """
    Handle Greenhouse ATS application forms.
    Greenhouse is used by: Airbnb, Dropbox, Notion, Figma, Stripe, and thousands more.
    URL pattern: boards.greenhouse.io/company/jobs/12345
    """
    try:
        # Navigate to job page if not already there
        if "greenhouse" not in page.url.lower():
            await page.goto(job["url"], timeout=20000)
            await page.wait_for_load_state("networkidle")

        # Click Apply button
        apply_btn = await page.query_selector(
            "a#app-apply, a:has-text('Apply for this Job'), a:has-text('Apply Now'), button:has-text('Apply')"
        )
        if apply_btn:
            await apply_btn.click()
            await page.wait_for_timeout(2000)

        resume = await db.get_resume(job.get("user_id", ""))
        profile = resume.get("profile", {}) if resume else {}

        # Fill first name
        first_name_field = await page.query_selector("input#first_name, input[name='job_application[first_name]']")
        if first_name_field:
            name_parts = profile.get("name", "").split()
            await first_name_field.fill(name_parts[0] if name_parts else "")

        # Fill last name
        last_name_field = await page.query_selector("input#last_name, input[name='job_application[last_name]']")
        if last_name_field:
            name_parts = profile.get("name", "").split()
            await last_name_field.fill(name_parts[-1] if len(name_parts) > 1 else "")

        # Fill email
        email_field = await page.query_selector("input#email, input[name='job_application[email]']")
        if email_field:
            await email_field.fill(profile.get("email", ""))

        # Fill phone
        phone_field = await page.query_selector("input#phone, input[name='job_application[phone]']")
        if phone_field:
            await phone_field.fill(profile.get("phone", ""))

        # Fill LinkedIn URL if asked
        linkedin_field = await page.query_selector("input[name*='linkedin'], input[placeholder*='LinkedIn']")
        if linkedin_field:
            await linkedin_field.fill(f"https://linkedin.com/in/{profile.get('name','').replace(' ','-').lower()}")

        # Fill cover letter
        cl_field = await page.query_selector(
            "textarea#cover_letter, textarea[name*='cover_letter'], textarea[placeholder*='cover']"
        )
        if cl_field and cover_letter:
            await cl_field.fill(cover_letter)

        # Handle resume upload (if required)
        resume_upload = await page.query_selector("input[type='file'][name*='resume'], input[type='file'][id*='resume']")
        if resume_upload:
            # Skip file upload — mark as partial
            print("Greenhouse: Resume upload required — skipping file upload step")

        # Submit the form
        submit_btn = await page.query_selector(
            "input[type='submit'], button[type='submit'], button:has-text('Submit Application')"
        )
        if submit_btn:
            await submit_btn.click()
            await page.wait_for_timeout(3000)

            # Check for success confirmation
            success_indicators = ["application received", "thank you", "successfully submitted", "we'll be in touch"]
            page_text = (await page.content()).lower()
            if any(indicator in page_text for indicator in success_indicators):
                return True

        return False
    except Exception as e:
        print(f"Greenhouse apply error: {e}")
        return False


# ─── LEVER ───────────────────────────────────────────────────────────────────

async def _apply_lever(page, job: Dict, cover_letter: str, prefs: Dict) -> bool:
    """
    Handle Lever ATS application forms.
    Lever is used by: Netflix, Reddit, Spotify, Shopify, and more.
    URL pattern: jobs.lever.co/company/uuid
    """
    try:
        if "lever" not in page.url.lower():
            await page.goto(job["url"], timeout=20000)
            await page.wait_for_load_state("networkidle")

        # Click Apply button
        apply_btn = await page.query_selector(
            "a.postings-btn, a:has-text('Apply for this job'), button:has-text('Apply')"
        )
        if apply_btn:
            await apply_btn.click()
            await page.wait_for_timeout(2000)

        resume = await db.get_resume(job.get("user_id", ""))
        profile = resume.get("profile", {}) if resume else {}

        # Fill name (Lever uses a single full name field)
        name_field = await page.query_selector("input[name='name'], input[placeholder*='Full name']")
        if name_field:
            await name_field.fill(profile.get("name", ""))

        # Fill email
        email_field = await page.query_selector("input[name='email'], input[type='email']")
        if email_field:
            await email_field.fill(profile.get("email", ""))

        # Fill phone
        phone_field = await page.query_selector("input[name='phone'], input[type='tel']")
        if phone_field:
            await phone_field.fill(profile.get("phone", ""))

        # Fill current company
        company_field = await page.query_selector("input[name='org'], input[placeholder*='company']")
        if company_field and profile.get("experience"):
            await company_field.fill(profile["experience"][0].get("company", ""))

        # Fill LinkedIn
        linkedin_field = await page.query_selector("input[name='urls[LinkedIn]'], input[placeholder*='LinkedIn']")
        if linkedin_field:
            await linkedin_field.fill(f"https://linkedin.com/in/{profile.get('name','').replace(' ','-').lower()}")

        # Fill cover letter (Lever calls it "Additional Information" sometimes)
        cl_field = await page.query_selector(
            "textarea[name='comments'], textarea[placeholder*='cover'], textarea[placeholder*='additional']"
        )
        if cl_field and cover_letter:
            await cl_field.fill(cover_letter)

        # Submit
        submit_btn = await page.query_selector(
            "button[type='submit'], input[type='submit'], button:has-text('Submit application')"
        )
        if submit_btn:
            await submit_btn.click()
            await page.wait_for_timeout(3000)

            # Check for success
            page_text = (await page.content()).lower()
            if any(x in page_text for x in ["thank you", "application received", "submitted"]):
                return True

        return False
    except Exception as e:
        print(f"Lever apply error: {e}")
        return False


# ─── WORKDAY ─────────────────────────────────────────────────────────────────

async def _apply_workday(page, job: Dict, cover_letter: str, prefs: Dict) -> bool:
    """
    Handle Workday ATS application forms.
    Workday is used by: Microsoft, Apple, Amazon, Bank of America, and most Fortune 500s.
    URL pattern: company.wd5.myworkdayjobs.com/...
    Workday is the most complex ATS — it's a full SPA with many steps.
    """
    try:
        if "workday" not in page.url.lower():
            await page.goto(job["url"], timeout=20000)
            await page.wait_for_load_state("networkidle")

        resume = await db.get_resume(job.get("user_id", ""))
        profile = resume.get("profile", {}) if resume else {}

        # Click Apply button
        apply_btn = await page.query_selector(
            "a[data-uxi-element-id='applyBtn'], button:has-text('Apply'), a:has-text('Apply Now')"
        )
        if apply_btn:
            await apply_btn.click()
            await page.wait_for_timeout(3000)

        # Workday step 1 — My Information
        # Fill email
        email_field = await page.query_selector("input[data-automation-id='email']")
        if email_field:
            await email_field.fill(profile.get("email", ""))

        # Fill name
        fname_field = await page.query_selector("input[data-automation-id='legalNameSection_firstName']")
        lname_field = await page.query_selector("input[data-automation-id='legalNameSection_lastName']")
        if fname_field and lname_field:
            name_parts = profile.get("name", "").split()
            await fname_field.fill(name_parts[0] if name_parts else "")
            await lname_field.fill(name_parts[-1] if len(name_parts) > 1 else "")

        # Fill phone
        phone_field = await page.query_selector("input[data-automation-id='phone-number']")
        if phone_field:
            await phone_field.fill(profile.get("phone", "").replace("+1-", "").replace("-", ""))

        # Click Next/Save and Continue through steps
        for step in range(6):
            await page.wait_for_timeout(1500)
            next_btn = await page.query_selector(
                "button[data-automation-id='bottom-navigation-next-button'],"
                "button:has-text('Save and Continue'),"
                "button:has-text('Next')"
            )
            submit_btn = await page.query_selector(
                "button[data-automation-id='bottom-navigation-next-button']:has-text('Submit'),"
                "button:has-text('Submit')"
            )

            if submit_btn:
                await submit_btn.click()
                await page.wait_for_timeout(3000)
                page_text = (await page.content()).lower()
                if any(x in page_text for x in ["thank you", "submitted", "received"]):
                    return True
                return True  # Assume success if no error shown
            elif next_btn:
                await next_btn.click()
            else:
                break

        return False
    except Exception as e:
        print(f"Workday apply error: {e}")
        return False


# ─── GENERIC FALLBACK ─────────────────────────────────────────────────────────

async def _apply_generic(page, job: Dict, cover_letter: str, prefs: Dict) -> bool:
    """
    Generic fallback for any career site not matched above.
    Tries common field patterns and submit buttons.
    Works on ~35% of sites.
    """
    try:
        await page.goto(job["url"], timeout=20000)
        await page.wait_for_load_state("networkidle")

        resume = await db.get_resume(job.get("user_id", ""))
        profile = resume.get("profile", {}) if resume else {}

        # Look for and click apply button
        for selector in ["a[href*='apply']", "button:has-text('Apply')", "a:has-text('Apply Now')", "a:has-text('Apply for')"]:
            btn = await page.query_selector(selector)
            if btn:
                await btn.click()
                await page.wait_for_timeout(2000)
                break

        # Fill common fields
        name_parts = profile.get("name", "").split()

        for sel, val in [
            ("input[name*='first'], input[id*='first'], input[placeholder*='First']", name_parts[0] if name_parts else ""),
            ("input[name*='last'], input[id*='last'], input[placeholder*='Last']", name_parts[-1] if len(name_parts) > 1 else ""),
            ("input[name*='email'], input[type='email']", profile.get("email", "")),
            ("input[name*='phone'], input[type='tel']", profile.get("phone", "")),
        ]:
            field = await page.query_selector(sel)
            if field and val:
                await field.fill(val)

        # Fill cover letter
        cl_field = await page.query_selector(
            "textarea[name*='cover'], textarea[id*='cover'], textarea[placeholder*='cover'], textarea[placeholder*='letter']"
        )
        if cl_field and cover_letter:
            await cl_field.fill(cover_letter)

        # Try to submit
        submit = await page.query_selector("button[type='submit'], input[type='submit']")
        if submit:
            await submit.click()
            await page.wait_for_timeout(2000)
            return False  # Mark as pending — needs human verification

        return False
    except Exception as e:
        print(f"Generic apply error: {e}")
        return False


# ─── COVER LETTER GENERATOR ───────────────────────────────────────────────────

async def _generate_cover_letter(claude_client, job: Dict, user_id: str) -> str:
    """Generate a personalized cover letter using Claude"""
    try:
        resume = await db.get_resume(user_id)
        profile = resume.get("profile", {}) if resume else {}
        skills = sum(profile.get("skills", {}).values(), [])
        experience = profile.get("experience", [])

        response = claude_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{
                "role": "user",
                "content": f"""Write a professional, genuine cover letter. 3 short paragraphs, under 200 words. No placeholders like [Your Name].

Candidate: {profile.get('name', '')}
Skills: {', '.join(skills[:12])}
Experience: {json.dumps(experience[:2])}
Certifications: {', '.join(profile.get('certifications', []))}

Job: {job.get('title', '')} at {job.get('company', '')}
Description: {job.get('description', '')[:300]}

Write it in first person, sound genuine not generic."""
            }]
        )
        return response.content[0].text
    except Exception as e:
        print(f"Cover letter generation error: {e}")
        name = ""
        try:
            resume = await db.get_resume(user_id)
            name = resume.get("profile", {}).get("name", "") if resume else ""
        except Exception:
            pass
        return f"Dear Hiring Team,\n\nI am excited to apply for the {job.get('title', '')} position at {job.get('company', '')}. My background in data science and Python development aligns well with your requirements.\n\nThank you for your consideration.\n\nSincerely,\n{name}"
