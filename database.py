"""
Database layer — PostgreSQL via asyncpg
All tables, queries, and CRUD operations live here
"""

import asyncpg
import os
import json
import uuid
import hashlib
from datetime import datetime, date
from typing import Optional, List, Dict


class Database:
    def __init__(self):
        self.pool = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(
            dsn=os.environ.get("DATABASE_URL"),
            min_size=1,
            max_size=10
        )
        print("✅ Database connected")

    async def disconnect(self):
        if self.pool:
            await self.pool.close()

    async def create_tables(self):
        """Create all tables on first run"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
                    name TEXT NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    is_active BOOLEAN DEFAULT TRUE
                );

                CREATE TABLE IF NOT EXISTS resumes (
                    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
                    user_id TEXT REFERENCES users(id) ON DELETE CASCADE UNIQUE,
                    raw_text TEXT,
                    profile JSONB,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS preferences (
                    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    roles TEXT[],
                    location TEXT,
                    experience_level TEXT,
                    min_match_threshold INTEGER DEFAULT 75,
                    max_applies_per_day INTEGER DEFAULT 25,
                    auto_apply_enabled BOOLEAN DEFAULT TRUE,
                    generate_cover_letters BOOLEAN DEFAULT TRUE,
                    scan_frequency_hours INTEGER DEFAULT 3,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
                    user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
                    external_id TEXT,
                    title TEXT NOT NULL,
                    company TEXT NOT NULL,
                    location TEXT,
                    salary TEXT,
                    description TEXT,
                    skills TEXT[],
                    board TEXT,
                    job_url TEXT,
                    match_score INTEGER DEFAULT 0,
                    match_reason TEXT,
                    status TEXT DEFAULT 'found',
                    is_new BOOLEAN DEFAULT TRUE,
                    found_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(user_id, external_id)
                );

                CREATE TABLE IF NOT EXISTS applications (
                    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
                    user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
                    job_id TEXT REFERENCES jobs(id) ON DELETE CASCADE,
                    cover_letter TEXT,
                    status TEXT DEFAULT 'queued',
                    applied_at TIMESTAMPTZ,
                    error_message TEXT,
                    notes TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS activity_log (
                    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
                    user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
                    type TEXT,
                    message TEXT,
                    metadata JSONB,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS scan_status (
                    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    status TEXT DEFAULT 'idle',
                    last_scan TIMESTAMPTZ,
                    jobs_found INTEGER DEFAULT 0
                );
            """)
        print("✅ Tables ready")

    # ── USERS ──────────────────────────────

    def _hash(self, password: str) -> str:
        return hashlib.sha256(password.encode()).hexdigest()

    async def create_user(self, name: str, email: str, password: str) -> str:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO users (name, email, password_hash) VALUES ($1, $2, $3) RETURNING id",
                name, email, self._hash(password)
            )
            await conn.execute(
                "INSERT INTO scan_status (user_id) VALUES ($1) ON CONFLICT DO NOTHING",
                row["id"]
            )
            return row["id"]

    async def get_user_by_email(self, email: str):
        async with self.pool.acquire() as conn:
            return await conn.fetchrow("SELECT * FROM users WHERE email = $1", email)

    async def get_user(self, user_id: str):
        async with self.pool.acquire() as conn:
            return dict(await conn.fetchrow("SELECT id, name, email, created_at FROM users WHERE id = $1", user_id) or {})

    async def verify_user(self, email: str, password: str):
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(
                "SELECT * FROM users WHERE email = $1 AND password_hash = $2",
                email, self._hash(password)
            )

    async def get_all_active_users(self):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT id FROM users WHERE is_active = TRUE")
            return [dict(r) for r in rows]

    # ── RESUME ─────────────────────────────

    async def save_resume(self, user_id: str, raw_text: str, profile: dict):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO resumes (user_id, raw_text, profile)
                VALUES ($1, $2, $3)
                ON CONFLICT (user_id) DO UPDATE SET raw_text=$2, profile=$3, updated_at=NOW()
            """, user_id, raw_text, json.dumps(profile))

    async def get_resume(self, user_id: str):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM resumes WHERE user_id = $1", user_id)
            if not row:
                return None
            r = dict(row)
            r["profile"] = json.loads(r["profile"]) if isinstance(r["profile"], str) else r["profile"]
            return r

    # ── PREFERENCES ────────────────────────

    async def save_preferences(self, user_id: str, prefs: dict):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO preferences (user_id, roles, location, experience_level,
                    min_match_threshold, max_applies_per_day, auto_apply_enabled,
                    generate_cover_letters, scan_frequency_hours)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                ON CONFLICT (user_id) DO UPDATE SET
                    roles=$2, location=$3, experience_level=$4,
                    min_match_threshold=$5, max_applies_per_day=$6,
                    auto_apply_enabled=$7, generate_cover_letters=$8,
                    scan_frequency_hours=$9, updated_at=NOW()
            """, user_id,
                prefs.get("roles", []),
                prefs.get("location", "Remote"),
                prefs.get("experience_level", "Entry Level"),
                prefs.get("min_match_threshold", 75),
                prefs.get("max_applies_per_day", 25),
                prefs.get("auto_apply_enabled", True),
                prefs.get("generate_cover_letters", True),
                prefs.get("scan_frequency_hours", 3)
            )

    async def get_preferences(self, user_id: str):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM preferences WHERE user_id = $1", user_id)
            return dict(row) if row else None

    # ── JOBS ───────────────────────────────

    async def get_seen_job_ids(self, user_id: str) -> set:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT external_id FROM jobs WHERE user_id = $1", user_id)
            return {r["external_id"] for r in rows}

    async def save_jobs(self, user_id: str, jobs: list):
        async with self.pool.acquire() as conn:
            for j in jobs:
                await conn.execute("""
                    INSERT INTO jobs (user_id, external_id, title, company, location,
                        salary, description, skills, board, job_url, match_score, match_reason)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                    ON CONFLICT (user_id, external_id) DO NOTHING
                """, user_id,
                    j.get("external_id"), j.get("title"), j.get("company"),
                    j.get("location"), j.get("salary"), j.get("description"),
                    j.get("skills", []), j.get("board"), j.get("url"),
                    j.get("match", 0), j.get("reason", "")
                )

    async def get_jobs(self, user_id: str, status=None, board=None, limit=200):
        async with self.pool.acquire() as conn:
            query = "SELECT * FROM jobs WHERE user_id = $1"
            params = [user_id]
            if status:
                query += f" AND status = ${len(params)+1}"
                params.append(status)
            if board:
                query += f" AND board = ${len(params)+1}"
                params.append(board)
            query += f" ORDER BY match_score DESC, found_at DESC LIMIT ${len(params)+1}"
            params.append(limit)
            rows = await conn.fetch(query, *params)
            return [dict(r) for r in rows]

    async def get_job(self, job_id: str):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM jobs WHERE id = $1", job_id)
            return dict(row) if row else None

    async def update_job_status(self, job_id: str, status: str, notes=None):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE jobs SET status=$1 WHERE id=$2",
                status, job_id
            )

    async def add_manual_job(self, user_id: str, job: dict) -> str:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO jobs (user_id, external_id, title, company, job_url, status, board)
                VALUES ($1,$2,$3,$4,$5,$6,'manual') RETURNING id
            """, user_id, str(uuid.uuid4()),
                job["title"], job["company"], job["url"], job.get("status","queued")
            )
            return row["id"]

    # ── APPLICATIONS ───────────────────────

    async def get_todays_apply_count(self, user_id: str) -> int:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT COUNT(*) as cnt FROM applications
                WHERE user_id = $1 AND DATE(applied_at) = $2
            """, user_id, date.today())
            return row["cnt"]

    async def save_application(self, user_id: str, job_id: str, status: str,
                                cover_letter: str = None, error: str = None):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO applications (user_id, job_id, cover_letter, status, applied_at, error_message)
                VALUES ($1,$2,$3,$4,$5,$6)
                ON CONFLICT DO NOTHING
            """, user_id, job_id, cover_letter, status,
                datetime.utcnow() if status == "applied" else None, error
            )
            await conn.execute("UPDATE jobs SET status=$1 WHERE id=$2", status, job_id)

    async def get_applications(self, user_id: str):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT a.*, j.title, j.company, j.board, j.match_score
                FROM applications a JOIN jobs j ON a.job_id = j.id
                WHERE a.user_id = $1 ORDER BY a.created_at DESC
            """, user_id)
            return [dict(r) for r in rows]

    # ── ACTIVITY LOG ───────────────────────

    async def log_activity(self, user_id: str, type: str, message: str, metadata: dict = None):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO activity_log (user_id, type, message, metadata)
                VALUES ($1,$2,$3,$4)
            """, user_id, type, message, json.dumps(metadata or {}))

    async def get_recent_activity(self, user_id: str, limit: int = 10):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM activity_log WHERE user_id = $1
                ORDER BY created_at DESC LIMIT $2
            """, user_id, limit)
            return [dict(r) for r in rows]

    # ── SCAN STATUS ────────────────────────

    async def get_scan_status(self, user_id: str):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM scan_status WHERE user_id = $1", user_id)
            return dict(row) if row else None

    async def update_scan_status(self, user_id: str, status: str, jobs_found: int = 0):
        async with self.pool.acquire() as conn:
            if status == "complete":
                # Terminal success: stamp completion time + final count
                await conn.execute("""
                    INSERT INTO scan_status (user_id, status, last_scan, jobs_found)
                    VALUES ($1,$2,NOW(),$3)
                    ON CONFLICT (user_id) DO UPDATE SET status=$2, last_scan=NOW(), jobs_found=$3
                """, user_id, status, jobs_found)
            else:
                # queued / scanning / scoring / error: update status only,
                # preserve the previous last_scan and jobs_found
                await conn.execute("""
                    INSERT INTO scan_status (user_id, status, jobs_found)
                    VALUES ($1,$2,0)
                    ON CONFLICT (user_id) DO UPDATE SET status=$2
                """, user_id, status)

    # ── DASHBOARD ──────────────────────────

    async def get_dashboard_stats(self, user_id: str):
        async with self.pool.acquire() as conn:
            stats = await conn.fetchrow("""
                SELECT
                    COUNT(*) FILTER (WHERE status != 'skipped') as jobs_found,
                    COUNT(*) FILTER (WHERE status = 'applied') as applied,
                    COUNT(*) FILTER (WHERE status = 'queued') as pending,
                    COUNT(*) FILTER (WHERE status = 'skipped') as skipped
                FROM jobs WHERE user_id = $1
            """, user_id)
            return dict(stats) if stats else {}


db = Database()
