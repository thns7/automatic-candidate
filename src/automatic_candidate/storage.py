"""Historico de candidaturas em SQLite.

Serve para tres coisas:
  1. nao aplicar duas vezes na mesma vaga (dedupe por fingerprint);
  2. respeitar os limites diarios configurados;
  3. te dar um relatorio do que foi enviado, quando e para quem.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from automatic_candidate.models import ApplyResult, ApplyStatus, JobPosting

SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
    fingerprint   TEXT PRIMARY KEY,
    company_key   TEXT NOT NULL,
    company_name  TEXT NOT NULL,
    title         TEXT NOT NULL,
    location      TEXT,
    url           TEXT,
    source        TEXT,
    external_id   TEXT,
    score         INTEGER DEFAULT 0,
    status        TEXT NOT NULL,
    message       TEXT,
    screenshot    TEXT,
    filled_fields TEXT,
    unanswered    TEXT,
    discovered_at TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    submitted_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_app_company ON applications(company_key);
CREATE INDEX IF NOT EXISTS idx_app_status ON applications(status);
CREATE INDEX IF NOT EXISTS idx_app_submitted ON applications(submitted_at);
"""

# Status que contam como "ja trabalhei nessa vaga, nao repetir".
TERMINAL_STATUSES = (ApplyStatus.SUBMITTED.value, ApplyStatus.FILLED.value)


@dataclass(slots=True)
class ApplicationRow:
    fingerprint: str
    company_key: str
    company_name: str
    title: str
    location: str
    url: str
    status: str
    message: str
    screenshot: str
    discovered_at: str
    updated_at: str
    submitted_at: str | None

    @classmethod
    def from_sqlite(cls, row: sqlite3.Row) -> ApplicationRow:
        return cls(
            fingerprint=row["fingerprint"],
            company_key=row["company_key"],
            company_name=row["company_name"],
            title=row["title"],
            location=row["location"] or "",
            url=row["url"] or "",
            status=row["status"],
            message=row["message"] or "",
            screenshot=row["screenshot"] or "",
            discovered_at=row["discovered_at"],
            updated_at=row["updated_at"],
            submitted_at=row["submitted_at"],
        )


class ApplicationStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ----------------------------------------------------------------- writes
    def record_discovery(self, job: JobPosting) -> bool:
        """Registra a vaga como descoberta. True se for nova."""
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO applications (
                    fingerprint, company_key, company_name, title, location, url,
                    source, external_id, score, status, discovered_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(fingerprint) DO NOTHING
                """,
                (
                    job.fingerprint,
                    job.company_key,
                    job.company_name,
                    job.title,
                    job.location,
                    job.target_url,
                    job.source,
                    job.external_id,
                    job.score,
                    ApplyStatus.DISCOVERED.value,
                    now,
                    now,
                ),
            )
            return cursor.rowcount > 0

    def record_result(self, result: ApplyResult) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        submitted = now if result.status is ApplyStatus.SUBMITTED else None
        job = result.job
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO applications (
                    fingerprint, company_key, company_name, title, location, url,
                    source, external_id, score, status, message, screenshot,
                    filled_fields, unanswered, discovered_at, updated_at, submitted_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(fingerprint) DO UPDATE SET
                    status        = excluded.status,
                    message       = excluded.message,
                    screenshot    = excluded.screenshot,
                    filled_fields = excluded.filled_fields,
                    unanswered    = excluded.unanswered,
                    updated_at    = excluded.updated_at,
                    submitted_at  = COALESCE(excluded.submitted_at, applications.submitted_at)
                """,
                (
                    job.fingerprint,
                    job.company_key,
                    job.company_name,
                    job.title,
                    job.location,
                    job.target_url,
                    job.source,
                    job.external_id,
                    job.score,
                    result.status.value,
                    result.message,
                    result.screenshot,
                    json.dumps(result.filled_fields, ensure_ascii=False),
                    json.dumps(result.unanswered_fields, ensure_ascii=False),
                    now,
                    now,
                    submitted,
                ),
            )

    # ------------------------------------------------------------------ reads
    def already_handled(self, fingerprint: str) -> str | None:
        """Retorna o status se a vaga ja foi preenchida/enviada."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM applications WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone()
        if row and row["status"] in TERMINAL_STATUSES:
            return str(row["status"])
        return None

    def count_submitted_today(self, company_key: str | None = None) -> int:
        today = date.today().isoformat()
        query = (
            "SELECT COUNT(*) AS n FROM applications "
            "WHERE submitted_at IS NOT NULL AND substr(submitted_at, 1, 10) = ?"
        )
        params: list[Any] = [today]
        if company_key:
            query += " AND company_key = ?"
            params.append(company_key)
        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
        return int(row["n"]) if row else 0

    def list_applications(
        self, status: str | None = None, limit: int = 100
    ) -> list[ApplicationRow]:
        query = "SELECT * FROM applications"
        params: list[Any] = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [ApplicationRow.from_sqlite(row) for row in rows]

    def stats_by_status(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM applications GROUP BY status"
            ).fetchall()
        return {row["status"]: int(row["n"]) for row in rows}

    def iter_all(self) -> Iterable[sqlite3.Row]:
        with self._connect() as conn:
            yield from conn.execute(
                "SELECT * FROM applications ORDER BY updated_at DESC"
            ).fetchall()
