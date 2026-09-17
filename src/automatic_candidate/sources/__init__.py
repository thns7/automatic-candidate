"""Registro das fontes de descoberta de vagas."""

from __future__ import annotations

from automatic_candidate.config import CompanyConfig
from automatic_candidate.httpclient import HttpClient
from automatic_candidate.sources.ats import (
    AshbySource,
    GreenhouseSource,
    LeverSource,
    SmartRecruitersSource,
)
from automatic_candidate.sources.base import JobSource
from automatic_candidate.sources.enterprise import (
    GupySource,
    ManualSource,
    MicrosoftSource,
    WorkdaySource,
)

SOURCES: dict[str, type[JobSource]] = {
    cls.name: cls
    for cls in (
        GreenhouseSource,
        LeverSource,
        AshbySource,
        SmartRecruitersSource,
        WorkdaySource,
        MicrosoftSource,
        GupySource,
        ManualSource,
    )
}


class UnknownSourceError(ValueError):
    pass


def build_source(company: CompanyConfig, http: HttpClient) -> JobSource:
    source_type = company.source_type
    if not source_type:
        raise UnknownSourceError(
            f"empresa '{company.key}': falta 'source.type' em config/companies.yaml. "
            f"Tipos disponiveis: {', '.join(sorted(SOURCES))}"
        )
    try:
        source_cls = SOURCES[source_type]
    except KeyError as exc:
        raise UnknownSourceError(
            f"empresa '{company.key}': source.type {source_type!r} desconhecido. "
            f"Use um destes: {', '.join(sorted(SOURCES))}"
        ) from exc
    return source_cls(company, http)


__all__ = ["SOURCES", "JobSource", "build_source", "UnknownSourceError"]
