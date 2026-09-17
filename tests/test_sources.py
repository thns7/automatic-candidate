"""Testa o parsing das fontes com payloads gravados (sem rede)."""

from __future__ import annotations

from typing import Any

import pytest

from automatic_candidate.config import CompanyConfig
from automatic_candidate.sources import UnknownSourceError, build_source
from automatic_candidate.sources.base import parse_date, strip_html


class FakeHttp:
    """Substitui o HttpClient devolvendo payloads fixos."""

    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str]] = []

    def get_json(self, url: str, **kwargs: Any) -> Any:
        self.calls.append(("GET", url))
        return self.payload

    def post_json(self, url: str, json_body: dict, **kwargs: Any) -> Any:
        self.calls.append(("POST", url))
        return self.payload


def company(source: dict, key: str = "acme") -> CompanyConfig:
    return CompanyConfig(key=key, name="Acme", source=source)


def test_greenhouse():
    payload = {
        "jobs": [
            {
                "id": 123,
                "title": "Software Engineer, Backend",
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/123",
                "location": {"name": "Sao Paulo, Brazil"},
                "updated_at": "2026-09-01T12:00:00-03:00",
                "content": "<p>Python e <b>Kubernetes</b></p>",
            }
        ]
    }
    source = build_source(company({"type": "greenhouse", "board": "acme"}), FakeHttp(payload))
    job = source.fetch()[0]
    assert job.external_id == "123"
    assert job.location == "Sao Paulo, Brazil"
    assert "Kubernetes" in job.description
    assert job.posted_at.isoformat() == "2026-09-01"


def test_lever():
    payload = [
        {
            "id": "abc",
            "text": "Backend Engineer",
            "hostedUrl": "https://jobs.lever.co/acme/abc",
            "applyUrl": "https://jobs.lever.co/acme/abc/apply",
            "categories": {"location": "Remote", "team": "Platform", "commitment": "Full-time"},
            "createdAt": 1756000000000,
            "descriptionPlain": "Trabalhe com Go",
        }
    ]
    job = build_source(company({"type": "lever", "board": "acme"}), FakeHttp(payload)).fetch()[0]
    assert job.apply_url.endswith("/apply")
    assert job.department == "Platform"
    assert job.posted_at is not None


def test_ashby():
    payload = {
        "jobs": [
            {
                "id": "u-1",
                "title": "Platform Engineer",
                "location": "Remote - Brazil",
                "jobUrl": "https://jobs.ashbyhq.com/acme/u-1",
                "department": "Infra",
                "publishedAt": "2026-08-20T00:00:00Z",
            }
        ]
    }
    job = build_source(company({"type": "ashby", "board": "acme"}), FakeHttp(payload)).fetch()[0]
    assert job.title == "Platform Engineer" and job.department == "Infra"


def test_smartrecruiters_monta_url_quando_falta():
    payload = {
        "totalFound": 1,
        "content": [
            {
                "id": "7788",
                "name": "Engenheiro de Dados",
                "location": {"city": "Sao Paulo", "country": "br"},
                "releasedDate": "2026-09-10T10:00:00.000Z",
            }
        ],
    }
    source = build_source(company({"type": "smartrecruiters", "board": "Acme"}), FakeHttp(payload))
    job = source.fetch()[0]
    assert job.url == "https://jobs.smartrecruiters.com/Acme/7788"
    assert job.location == "Sao Paulo, br"


def test_workday_monta_url_com_external_path():
    payload = {
        "total": 1,
        "jobPostings": [
            {
                "title": "Senior Software Engineer",
                "externalPath": "/job/Santa-Clara/Senior-SWE_JR123",
                "locationsText": "Santa Clara, CA",
                "postedOn": "Posted 5 Days Ago",
                "bulletFields": ["JR123"],
            }
        ],
    }
    source = build_source(
        company(
            {
                "type": "workday",
                "host": "nvidia.wd5.myworkdayjobs.com",
                "tenant": "nvidia",
                "site": "NVIDIAExternalCareerSite",
            },
            key="nvidia",
        ),
        FakeHttp(payload),
    )
    job = source.fetch()[0]
    assert job.external_id == "JR123"
    assert job.url == (
        "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite"
        "/job/Santa-Clara/Senior-SWE_JR123"
    )
    assert job.posted_at is not None


def test_workday_exige_host_e_site():
    source = build_source(company({"type": "workday"}), FakeHttp({}))
    with pytest.raises(ValueError, match="source.host"):
        source.fetch()


def test_microsoft():
    payload = {
        "operationResult": {
            "result": {
                "totalJobs": 1,
                "jobs": [
                    {
                        "jobId": "1800123",
                        "title": "Software Engineer II",
                        "postingDate": "2026-09-05T00:00:00+00:00",
                        "properties": {
                            "locations": ["Sao Paulo, Brazil"],
                            "profession": "Software Engineering",
                        },
                    }
                ],
            }
        }
    }
    source = build_source(company({"type": "microsoft"}, key="microsoft"), FakeHttp(payload))
    job = source.fetch()[0]
    assert job.url.endswith("/job/1800123")
    assert job.location == "Sao Paulo, Brazil"


def test_gupy_aceita_lista_ou_envelope():
    item = {
        "id": 55,
        "name": "Pessoa Engenheira de Software",
        "city": "Sao Paulo",
        "state": "SP",
        "jobUrl": "https://vemproitau.gupy.io/job/55",
        "publishedDate": "2026-09-12T00:00:00.000Z",
        "workplaceType": "remote",
    }
    for payload in ({"data": [item]}, [item]):
        source = build_source(
            company({"type": "gupy", "board": "vemproitau"}, key="itau"), FakeHttp(payload)
        )
        job = source.fetch()[0]
        assert job.external_id == "55"
        assert "remoto" in job.location
        assert job.url == "https://vemproitau.gupy.io/job/55"


def test_manual_gera_uma_entrada_por_url():
    source = build_source(
        company(
            {"type": "manual", "search_urls": ["https://careers.google.com/a", "https://b"]},
            key="google",
        ),
        FakeHttp({}),
    )
    assert len(source.fetch()) == 2


def test_source_desconhecida_explica_as_opcoes():
    with pytest.raises(UnknownSourceError, match="greenhouse"):
        build_source(company({"type": "inexistente"}), FakeHttp({}))


def test_parse_date_formatos():
    assert parse_date("2026-09-01T10:00:00Z").isoformat() == "2026-09-01"
    assert parse_date("01/09/2026").isoformat() == "2026-09-01"
    assert parse_date("") is None
    assert parse_date("texto qualquer") is None


def test_strip_html_limpa_entidades():
    assert strip_html("<p>Python &amp; Go</p>") == "Python & Go"
