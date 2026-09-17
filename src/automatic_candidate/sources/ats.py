"""Fontes para os ATS mais comuns com API publica de vagas.

Greenhouse, Lever, Ashby e SmartRecruiters expoem o quadro de vagas em JSON
sem autenticacao. Sao os mais estaveis — a maior parte das empresas de
tecnologia usa um destes.
"""

from __future__ import annotations

from typing import Any

from automatic_candidate.httpclient import pluck
from automatic_candidate.models import JobPosting
from automatic_candidate.sources.base import JobSource, parse_date, strip_html


class GreenhouseSource(JobSource):
    """https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"""

    name = "greenhouse"
    docs = "https://developers.greenhouse.io/job-board.html"

    def endpoint(self) -> str:
        return f"https://boards-api.greenhouse.io/v1/boards/{self.board}/jobs"

    def fetch(self, limit: int = 200) -> list[JobPosting]:
        payload = self.http.get_json(self.endpoint(), params={"content": "true"})
        jobs: list[JobPosting] = []
        for item in (payload.get("jobs") or [])[:limit]:
            jobs.append(
                self.make_job(
                    external_id=str(item.get("id", "")),
                    title=str(item.get("title", "")).strip(),
                    url=str(item.get("absolute_url", "")),
                    apply_url=str(item.get("absolute_url", "")),
                    location=str(pluck(item, "location.name", "offices.0.name")),
                    department=str(pluck(item, "departments.0.name")),
                    description=strip_html(item.get("content")),
                    posted_at=parse_date(item.get("updated_at") or item.get("first_published")),
                    raw=item,
                )
            )
        return jobs


class LeverSource(JobSource):
    """https://api.lever.co/v0/postings/{board}?mode=json"""

    name = "lever"
    docs = "https://github.com/lever/postings-api"

    def endpoint(self) -> str:
        return f"https://api.lever.co/v0/postings/{self.board}"

    def fetch(self, limit: int = 200) -> list[JobPosting]:
        payload = self.http.get_json(self.endpoint(), params={"mode": "json"})
        items: list[dict[str, Any]] = payload if isinstance(payload, list) else []
        jobs: list[JobPosting] = []
        for item in items[:limit]:
            jobs.append(
                self.make_job(
                    external_id=str(item.get("id", "")),
                    title=str(item.get("text", "")).strip(),
                    url=str(item.get("hostedUrl", "")),
                    apply_url=str(item.get("applyUrl") or item.get("hostedUrl", "")),
                    location=str(pluck(item, "categories.location", "workplaceType")),
                    department=str(pluck(item, "categories.team", "categories.department")),
                    employment_type=str(pluck(item, "categories.commitment")),
                    description=strip_html(
                        item.get("descriptionPlain") or item.get("description")
                    ),
                    posted_at=parse_date(item.get("createdAt")),
                    raw=item,
                )
            )
        return jobs


class AshbySource(JobSource):
    """https://api.ashbyhq.com/posting-api/job-board/{board}"""

    name = "ashby"
    docs = "https://developers.ashbyhq.com/docs/public-job-posting-api"

    def endpoint(self) -> str:
        return f"https://api.ashbyhq.com/posting-api/job-board/{self.board}"

    def fetch(self, limit: int = 200) -> list[JobPosting]:
        payload = self.http.get_json(
            self.endpoint(), params={"includeCompensation": "true"}
        )
        jobs: list[JobPosting] = []
        for item in (payload.get("jobs") or [])[:limit]:
            url = str(item.get("jobUrl") or item.get("applyUrl") or "")
            jobs.append(
                self.make_job(
                    external_id=str(item.get("id", "")),
                    title=str(item.get("title", "")).strip(),
                    url=url,
                    apply_url=str(item.get("applyUrl") or url),
                    location=str(pluck(item, "location", "address.postalAddress.addressLocality")),
                    department=str(item.get("department", "")),
                    employment_type=str(item.get("employmentType", "")),
                    description=strip_html(
                        item.get("descriptionPlain") or item.get("descriptionHtml")
                    ),
                    posted_at=parse_date(item.get("publishedAt") or item.get("updatedAt")),
                    raw=item,
                )
            )
        return jobs


class SmartRecruitersSource(JobSource):
    """https://api.smartrecruiters.com/v1/companies/{board}/postings"""

    name = "smartrecruiters"
    docs = "https://dev.smartrecruiters.com/customer-api/posting-api/"

    PAGE_SIZE = 100

    def endpoint(self) -> str:
        return f"https://api.smartrecruiters.com/v1/companies/{self.board}/postings"

    def fetch(self, limit: int = 200) -> list[JobPosting]:
        jobs: list[JobPosting] = []
        offset = 0
        while len(jobs) < limit:
            payload = self.http.get_json(
                self.endpoint(),
                params={
                    "limit": min(self.PAGE_SIZE, limit - len(jobs)),
                    "offset": offset,
                    "q": self.option("query", ""),
                },
            )
            content = payload.get("content") or []
            if not content:
                break
            for item in content:
                city = str(pluck(item, "location.city"))
                country = str(pluck(item, "location.country"))
                location = ", ".join(part for part in (city, country) if part)
                if pluck(item, "location.remote", default=False):
                    location = f"{location} (remote)".strip()
                job_id = str(item.get("id", ""))
                url = str(
                    pluck(item, "applyUrl", "ref")
                    or f"https://jobs.smartrecruiters.com/{self.board}/{job_id}"
                )
                jobs.append(
                    self.make_job(
                        external_id=job_id,
                        title=str(item.get("name", "")).strip(),
                        url=url,
                        apply_url=url,
                        location=location,
                        department=str(pluck(item, "department.label", "function.label")),
                        employment_type=str(pluck(item, "typeOfEmployment.label")),
                        posted_at=parse_date(item.get("releasedDate")),
                        raw=item,
                    )
                )
            offset += len(content)
            if offset >= int(payload.get("totalFound", offset)):
                break
        return jobs[:limit]
