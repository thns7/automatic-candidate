"""Fontes dos portais proprietarios das empresas grandes.

Workday (NVIDIA e a maior parte das multinacionais), o portal proprio da
Microsoft, a Gupy (Itau, Zamp e quase todo o mercado BR) e o modo 'manual'
para sites sem API estavel, como o Google.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

from automatic_candidate.httpclient import pluck
from automatic_candidate.models import JobPosting
from automatic_candidate.sources.base import JobSource, parse_date, strip_html

logger = logging.getLogger(__name__)


class WorkdaySource(JobSource):
    """API CxS do Workday.

    POST https://{host}/wday/cxs/{tenant}/{site}/jobs
    body: {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "..."}

    Para descobrir host/tenant/site, abra o portal de carreiras da empresa:
        https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite
                ^tenant ^host                ^site
    """

    name = "workday"
    docs = "portal Workday da empresa (wday/cxs)"
    PAGE_SIZE = 20

    @property
    def host(self) -> str:
        host = str(self.option("host", "")).strip()
        if not host:
            raise ValueError(
                f"empresa '{self.company.key}': defina source.host "
                "(ex: nvidia.wd5.myworkdayjobs.com)"
            )
        return host.replace("https://", "").strip("/")

    @property
    def tenant(self) -> str:
        return str(self.option("tenant", "")).strip() or self.host.split(".")[0]

    @property
    def site(self) -> str:
        site = str(self.option("site", "")).strip()
        if not site:
            raise ValueError(
                f"empresa '{self.company.key}': defina source.site "
                "(ex: NVIDIAExternalCareerSite)"
            )
        return site

    def endpoint(self) -> str:
        return f"https://{self.host}/wday/cxs/{self.tenant}/{self.site}/jobs"

    def fetch(self, limit: int = 200) -> list[JobPosting]:
        locale = str(self.option("locale", "en-US"))
        search_text = str(self.option("search_text", ""))
        facets = dict(self.option("applied_facets", {}) or {})

        jobs: list[JobPosting] = []
        offset = 0
        while len(jobs) < limit:
            payload = self.http.post_json(
                self.endpoint(),
                {
                    "appliedFacets": facets,
                    "limit": self.PAGE_SIZE,
                    "offset": offset,
                    "searchText": search_text,
                },
                headers={"Content-Type": "application/json"},
            )
            postings = payload.get("jobPostings") or []
            if not postings:
                break
            for item in postings:
                external_path = str(item.get("externalPath", ""))
                url = f"https://{self.host}/{locale}/{self.site}{external_path}"
                jobs.append(
                    self.make_job(
                        external_id=str(
                            item.get("bulletFields", [""])[0] if item.get("bulletFields") else ""
                        )
                        or external_path,
                        title=str(item.get("title", "")).strip(),
                        url=url,
                        apply_url=url,
                        location=str(item.get("locationsText", "")),
                        description=strip_html(item.get("shortDescription")),
                        posted_at=parse_date(item.get("postedOn") or item.get("startDate")),
                        raw=item,
                    )
                )
            offset += len(postings)
            if offset >= int(payload.get("total", offset)):
                break
        return jobs[:limit]


class MicrosoftSource(JobSource):
    """Portal proprio da Microsoft (jobs.careers.microsoft.com).

    GET https://gcsservices.careers.microsoft.com/search/api/v1/search
    """

    name = "microsoft"
    docs = "https://jobs.careers.microsoft.com"
    ENDPOINT = "https://gcsservices.careers.microsoft.com/search/api/v1/search"
    PAGE_SIZE = 20

    def fetch(self, limit: int = 200) -> list[JobPosting]:
        params: dict[str, Any] = {
            "q": str(self.option("query", "software engineer")),
            "l": "en_us",
            "pg": 1,
            "pgSz": self.PAGE_SIZE,
            "o": "Recent",
            "flt": "true",
        }
        country = str(self.option("country", ""))
        if country:
            params["lc"] = country

        jobs: list[JobPosting] = []
        page = 1
        while len(jobs) < limit:
            params["pg"] = page
            payload = self.http.get_json(self.ENDPOINT, params=params)
            result = pluck(payload, "operationResult.result", default={}) or {}
            items = result.get("jobs") or []
            if not items:
                break
            for item in items:
                job_id = str(item.get("jobId") or item.get("id", ""))
                locations = pluck(item, "properties.locations", default=[]) or []
                location = ", ".join(str(loc) for loc in locations[:2]) or str(
                    pluck(item, "properties.primaryLocation", "properties.primaryWorkLocation")
                )
                jobs.append(
                    self.make_job(
                        external_id=job_id,
                        title=str(item.get("title", "")).strip(),
                        url=f"https://jobs.careers.microsoft.com/global/en/job/{job_id}",
                        apply_url=f"https://jobs.careers.microsoft.com/global/en/job/{job_id}",
                        location=location,
                        department=str(pluck(item, "properties.profession", "properties.discipline")),
                        employment_type=str(pluck(item, "properties.employmentType")),
                        description=strip_html(
                            pluck(item, "properties.description", "properties.jobSummary")
                        ),
                        posted_at=parse_date(item.get("postingDate") or item.get("postedDate")),
                        raw=item,
                    )
                )
            total = int(result.get("totalJobs", 0) or 0)
            page += 1
            if len(jobs) >= total or page > 25:
                break
        return jobs[:limit]


class GupySource(JobSource):
    """Gupy — usada por Itau, Zamp e a maior parte das empresas brasileiras.

    Cada empresa tem um portal em https://{board}.gupy.io e a listagem publica
    fica em https://{board}.gupy.io/api/job. O portal agregador
    (portal.api.gupy.io) serve de fallback quando o board nao responde.
    """

    name = "gupy"
    docs = "https://{board}.gupy.io"
    PAGE_SIZE = 100

    def endpoint(self) -> str:
        custom = str(self.option("api_url", "")).strip()
        if custom:
            return custom
        return f"https://{self.board}.gupy.io/api/job"

    def fallback_endpoint(self) -> str:
        return "https://portal.api.gupy.io/api/job"

    def fetch(self, limit: int = 200) -> list[JobPosting]:
        query = str(self.option("query", ""))
        try:
            payload = self.http.get_json(
                self.endpoint(), params={"limit": self.PAGE_SIZE, "offset": 0, "name": query}
            )
            items = self._items(payload)
        except Exception as exc:  # noqa: BLE001 - fallback e proposital
            logger.info(
                "board '%s' nao respondeu (%s); tentando o portal agregador da Gupy",
                self.board,
                exc,
            )
            payload = self.http.get_json(
                self.fallback_endpoint(),
                params={"name": query or self.company.name, "limit": self.PAGE_SIZE, "offset": 0},
            )
            items = [
                item
                for item in self._items(payload)
                if self._belongs_to_company(item)
            ]

        jobs: list[JobPosting] = []
        for item in items[:limit]:
            city = str(pluck(item, "city", "addressCity"))
            state = str(pluck(item, "state", "addressState"))
            location = ", ".join(part for part in (city, state) if part)
            if str(pluck(item, "workplaceType", "type")).lower() in {"remote", "remoto"}:
                location = f"{location} (remoto)".strip(", ").strip()
            url = str(
                pluck(item, "jobUrl", "careerPageUrl", "url")
                or f"https://{self.board}.gupy.io/job/{item.get('id', '')}"
            )
            jobs.append(
                self.make_job(
                    external_id=str(item.get("id", "")),
                    title=str(pluck(item, "name", "title")).strip(),
                    url=url,
                    apply_url=url,
                    location=location,
                    department=str(pluck(item, "department.name", "careerPageName")),
                    employment_type=str(pluck(item, "type", "contractType")),
                    description=strip_html(pluck(item, "description", "jobDescription")),
                    posted_at=parse_date(pluck(item, "publishedDate", "createdAt")),
                    raw=item,
                )
            )
        return jobs

    @staticmethod
    def _items(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            for key in ("data", "jobs", "content", "results"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        return []

    def _belongs_to_company(self, item: dict[str, Any]) -> bool:
        needle = self.board.lower()
        haystack = " ".join(
            str(pluck(item, key, default=""))
            for key in ("careerPageName", "companyName", "careerPageUrl", "jobUrl")
        ).lower()
        return needle in haystack or self.company.name.lower() in haystack


class ManualSource(JobSource):
    """Sites sem API publica estavel (ex.: Google).

    Nao raspa HTML: apenas transforma as 'search_urls' do companies.yaml em
    entradas de trabalho, para o fluxo assistido abrir a busca no navegador
    (`candidate open google`) e voce escolher a vaga. A automacao entao
    preenche o formulario normalmente.
    """

    name = "manual"
    docs = "definido por search_urls em config/companies.yaml"

    def fetch(self, limit: int = 200) -> list[JobPosting]:
        urls = [str(u) for u in (self.option("search_urls", []) or [])]
        jobs: list[JobPosting] = []
        for index, url in enumerate(urls[:limit], start=1):
            jobs.append(
                self.make_job(
                    external_id=f"manual-{index}",
                    title=str(self.option("title", f"Busca manual #{index}")),
                    url=url,
                    apply_url=url,
                    location=str(self.option("location", "")),
                    description=(
                        "Fonte manual: abra com 'candidate open "
                        f"{self.company.key}' e escolha a vaga no site."
                    ),
                    raw={"search_url": url},
                )
            )
        return jobs

    def describe(self) -> str:
        count = len(self.option("search_urls", []) or [])
        return f"{self.company.name} via manual ({count} URLs de busca)"


def build_search_url(base: str, query: str) -> str:
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}q={quote(query)}"
