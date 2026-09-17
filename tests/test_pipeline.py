"""Orquestracao: filtros, dedupe e limites — sem rede e sem navegador."""

from __future__ import annotations

import pytest

from automatic_candidate import pipeline
from automatic_candidate.config import AppConfig, CompanyConfig
from automatic_candidate.models import ApplyResult, ApplyStatus, JobPosting, SubmitMode
from automatic_candidate.storage import ApplicationStore


class FakeSource:
    def __init__(self, jobs: list[JobPosting]) -> None:
        self._jobs = jobs

    def fetch(self, limit: int = 200) -> list[JobPosting]:
        return self._jobs[:limit]


class FakeBrowser:
    def __init__(self, *args, **kwargs) -> None:
        self.started = False

    def __enter__(self):
        self.started = True
        return self

    def __exit__(self, *exc):
        return None


class FakeApplier:
    def __init__(self, context) -> None:
        self.ctx = context

    def apply(self, job: JobPosting) -> ApplyResult:
        return ApplyResult(job=job, status=ApplyStatus.SUBMITTED, message="fake")


def make_job(title: str, company: str = "acme", external_id: str = "1") -> JobPosting:
    return JobPosting(
        company_key=company, company_name="Acme", title=title, url="http://vaga",
        source="teste", external_id=external_id, location="Sao Paulo, Brasil",
    )


@pytest.fixture
def config(example_profile, example_settings, tmp_path):
    settings = example_settings
    settings.database = tmp_path / "apps.sqlite3"
    settings.reports_dir = tmp_path / "reports"
    settings.submit_mode = SubmitMode.DRY_RUN
    settings.limits.min_seconds_between_applications = 0
    settings.limits.max_seconds_between_applications = 0
    company = CompanyConfig(
        key="acme", name="Acme", source={"type": "greenhouse", "board": "acme"},
        apply={"applier": "generic"},
    )
    return AppConfig(profile=example_profile, settings=settings, companies=[company])


@pytest.fixture
def no_browser(monkeypatch, tmp_path):
    """Troca navegador, applier e documentos por dublês."""
    resume = tmp_path / "curriculo.pdf"
    resume.write_bytes(b"%PDF")
    monkeypatch.setattr(pipeline, "BrowserSession", FakeBrowser)
    monkeypatch.setattr(pipeline, "build_applier", lambda name, ctx: FakeApplier(ctx))
    monkeypatch.setattr(pipeline, "resolve_resume", lambda profile, company: resume)
    monkeypatch.setattr(pipeline, "write_cover_letter", lambda p, s, j: None)
    return resume


def test_discover_aplica_filtros(config, monkeypatch):
    jobs = [make_job("Engenheiro de Software", external_id="1"),
            make_job("Estagiario de Engenharia", external_id="2"),
            make_job("Sales Manager", external_id="3")]
    monkeypatch.setattr(pipeline, "build_source", lambda c, h: FakeSource(jobs))
    report = pipeline.discover(config)
    assert report.seen == 3
    assert [j.title for j in report.jobs] == ["Engenheiro de Software"]
    assert len(report.rejected) == 2


def test_discover_registra_erro_da_empresa_sem_derrubar(config, monkeypatch):
    def explode(company, http):
        raise RuntimeError("slug invalido")

    monkeypatch.setattr(pipeline, "build_source", explode)
    report = pipeline.discover(config)
    assert report.errors["acme"] == "slug invalido"
    assert report.jobs == []


def test_nao_aplica_duas_vezes_na_mesma_vaga(config, no_browser):
    store = ApplicationStore(config.settings.database)
    job = make_job("Engenheiro de Software")
    primeira = pipeline.run_applications(config, [job], store)
    assert primeira.count(ApplyStatus.SUBMITTED) == 1
    segunda = pipeline.run_applications(config, [job], store)
    assert segunda.results == []
    assert "ja trabalhada" in segunda.skipped[0][1]


def test_limite_por_execucao(config, no_browser):
    store = ApplicationStore(config.settings.database)
    jobs = [make_job(f"Engenheiro de Software {i}", external_id=str(i)) for i in range(10)]
    report = pipeline.run_applications(config, jobs, store, limit=3)
    assert len(report.results) == 3


def test_limite_diario_bloqueia_execucao(config, no_browser):
    store = ApplicationStore(config.settings.database)
    config.settings.limits.max_applications_per_day = 2
    jobs = [make_job(f"Engenheiro de Software {i}", external_id=str(i)) for i in range(5)]
    pipeline.run_applications(config, jobs, store, limit=2)
    restante = pipeline.run_applications(
        config, [make_job("Engenheiro de Software novo", external_id="99")], store
    )
    assert restante.results == []


def test_limite_por_empresa_por_dia(config, no_browser):
    store = ApplicationStore(config.settings.database)
    config.settings.limits.max_per_company_per_day = 2
    jobs = [make_job(f"Engenheiro de Software {i}", external_id=str(i)) for i in range(5)]
    report = pipeline.run_applications(config, jobs, store, limit=5)
    assert len(report.results) == 2
    assert any("limite diario por empresa" in reason for _, reason in report.skipped)


def test_force_ignora_o_dedupe(config, no_browser):
    store = ApplicationStore(config.settings.database)
    job = make_job("Engenheiro de Software")
    pipeline.run_applications(config, [job], store)
    de_novo = pipeline.run_applications(config, [job], store, force=True)
    assert de_novo.count(ApplyStatus.SUBMITTED) == 1
