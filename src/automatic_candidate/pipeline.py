"""Orquestracao: descobrir -> filtrar -> ranquear -> candidatar -> registrar."""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field

from automatic_candidate.answers import AnswerBook
from automatic_candidate.appliers import ApplyContext, build_applier
from automatic_candidate.browser import BrowserSession
from automatic_candidate.config import AppConfig, CompanyConfig
from automatic_candidate.documents import (
    DocumentError,
    extra_attachments,
    resolve_resume,
    write_cover_letter,
)
from automatic_candidate.httpclient import HttpClient
from automatic_candidate.matching import evaluate, rank
from automatic_candidate.models import ApplyResult, ApplyStatus, JobPosting, SubmitMode
from automatic_candidate.sources import build_source
from automatic_candidate.storage import ApplicationStore

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DiscoveryReport:
    jobs: list[JobPosting] = field(default_factory=list)
    rejected: list[tuple[JobPosting, str]] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    seen: int = 0

    @property
    def kept(self) -> int:
        return len(self.jobs)


def discover(
    config: AppConfig,
    company_keys: list[str] | None = None,
    per_company_limit: int = 200,
    store: ApplicationStore | None = None,
) -> DiscoveryReport:
    """Busca vagas nos portais das empresas habilitadas e aplica os filtros."""
    http = HttpClient()
    report = DiscoveryReport()

    for company in config.enabled_companies(company_keys):
        try:
            source = build_source(company, http)
            postings = source.fetch(limit=per_company_limit)
        except Exception as exc:  # noqa: BLE001 - uma empresa fora nao para o resto
            logger.warning("[%s] falha na busca: %s", company.key, exc)
            report.errors[company.key] = str(exc)
            continue

        report.seen += len(postings)
        kept_here = 0
        for job in postings:
            decision = evaluate(job, config.settings.filters, config.profile)
            job.score = decision.score
            if not decision.keep:
                report.rejected.append((job, decision.reason))
                continue
            report.jobs.append(job)
            kept_here += 1
            if store is not None:
                store.record_discovery(job)
        logger.info(
            "[%s] %d vagas encontradas, %d passaram nos filtros", company.key, len(postings), kept_here
        )

    report.jobs = rank(report.jobs)
    return report


@dataclass(slots=True)
class RunReport:
    results: list[ApplyResult] = field(default_factory=list)
    skipped: list[tuple[JobPosting, str]] = field(default_factory=list)

    def count(self, status: ApplyStatus) -> int:
        return sum(1 for r in self.results if r.status is status)


def run_applications(
    config: AppConfig,
    jobs: list[JobPosting],
    store: ApplicationStore,
    limit: int | None = None,
    force: bool = False,
) -> RunReport:
    """Percorre a fila de vagas preenchendo (e opcionalmente enviando)."""
    settings = config.settings
    limits = settings.limits
    report = RunReport()

    max_this_run = limit if limit is not None else limits.max_applications_per_run
    remaining_today = limits.max_applications_per_day - store.count_submitted_today()
    if remaining_today <= 0 and not force:
        logger.warning(
            "limite diario atingido (%d candidaturas hoje). Ajuste limits.max_applications_per_day "
            "em config/settings.yaml ou rode amanha.",
            limits.max_applications_per_day,
        )
        return report

    queue = _filter_queue(jobs, store, config, report, force)
    if not queue:
        logger.info("nenhuma vaga nova para trabalhar.")
        return report

    answers = AnswerBook(config.profile)
    attachments = tuple(extra_attachments(config.profile))
    browser = BrowserSession(settings.browser)
    per_company_done: dict[str, int] = {}

    with browser:
        for index, job in enumerate(queue):
            if len(report.results) >= max_this_run:
                logger.info("limite da execucao atingido (%d).", max_this_run)
                break
            if not force and per_company_done.get(job.company_key, 0) >= limits.max_per_company_per_day:
                report.skipped.append((job, "limite diario por empresa atingido"))
                continue

            company = config.company(job.company_key)
            try:
                context = _build_context(config, company, job, answers, browser, attachments)
            except DocumentError as exc:
                logger.error("%s", exc)
                report.skipped.append((job, str(exc)))
                continue

            logger.info("[%d/%d] %s", index + 1, len(queue), job.summary_line())
            applier = build_applier(company.applier, context)
            try:
                result = applier.apply(job)
            except KeyboardInterrupt:
                logger.info("interrompido por voce; salvando o que ja foi feito.")
                break
            except Exception as exc:  # noqa: BLE001 - erro numa vaga nao derruba a fila
                logger.exception("erro ao trabalhar a vaga %s", job.title)
                result = ApplyResult(job=job, status=ApplyStatus.FAILED, message=str(exc))

            store.record_result(result)
            report.results.append(result)
            per_company_done[job.company_key] = per_company_done.get(job.company_key, 0) + 1
            logger.info("    -> %s: %s", result.status.value, result.message)

            if index < len(queue) - 1 and settings.submit_mode is not SubmitMode.DRY_RUN:
                _pause(limits.min_seconds_between_applications, limits.max_seconds_between_applications)

    return report


def _filter_queue(
    jobs: list[JobPosting],
    store: ApplicationStore,
    config: AppConfig,
    report: RunReport,
    force: bool,
) -> list[JobPosting]:
    queue: list[JobPosting] = []
    for job in jobs:
        if not force:
            handled = store.already_handled(job.fingerprint)
            if handled:
                report.skipped.append((job, f"ja trabalhada antes (status: {handled})"))
                continue
        try:
            config.company(job.company_key)
        except Exception as exc:  # noqa: BLE001
            report.skipped.append((job, str(exc)))
            continue
        queue.append(job)
    return queue


def _build_context(
    config: AppConfig,
    company: CompanyConfig,
    job: JobPosting,
    answers: AnswerBook,
    browser: BrowserSession,
    attachments: tuple,
) -> ApplyContext:
    resume = resolve_resume(config.profile, company)
    cover = None
    if config.settings.cover_letter_enabled:
        try:
            cover = write_cover_letter(config.profile, config.settings, job)
        except DocumentError as exc:
            logger.warning("carta de apresentacao nao gerada: %s", exc)
    return ApplyContext(
        profile=config.profile,
        settings=config.settings,
        company=company,
        answers=answers,
        browser=browser,
        resume=resume,
        cover_letter=cover,
        attachments=attachments,
    )


def _pause(minimum: int, maximum: int) -> None:
    """Intervalo aleatorio entre candidaturas — evita rajadas e bloqueios."""
    if maximum <= 0:
        return
    delay = random.uniform(max(0, minimum), max(minimum, maximum))
    logger.info("    aguardando %.0fs antes da proxima...", delay)
    time.sleep(delay)
