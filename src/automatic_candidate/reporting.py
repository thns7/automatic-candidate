"""Saida no terminal e exportacao de relatorios."""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

from automatic_candidate.models import ApplyStatus
from automatic_candidate.pipeline import DiscoveryReport, RunReport
from automatic_candidate.storage import ApplicationStore

STATUS_LABEL = {
    ApplyStatus.DISCOVERED.value: "descoberta",
    ApplyStatus.FILLED.value: "preenchida (aguarda voce)",
    ApplyStatus.SUBMITTED.value: "ENVIADA",
    ApplyStatus.SKIPPED.value: "ignorada",
    ApplyStatus.FAILED.value: "erro",
    ApplyStatus.NEEDS_MANUAL.value: "requer acao manual",
}


def _width() -> int:
    return max(60, min(shutil.get_terminal_size((100, 24)).columns, 120))


def header(title: str) -> None:
    line = "=" * _width()
    print(f"\n{line}\n {title}\n{line}")


def print_discovery(report: DiscoveryReport, show_rejected: int = 0) -> None:
    header(f"{report.kept} vagas selecionadas de {report.seen} encontradas")
    if not report.jobs:
        print(" Nenhuma vaga passou nos filtros.")
        print(" Dica: afrouxe filters.title_include / locations_include em config/settings.yaml")
    for job in report.jobs:
        print(f" {job.summary_line()}")
        print(f"      {job.target_url}")
    if show_rejected and report.rejected:
        header(f"descartadas ({len(report.rejected)}) — mostrando {show_rejected}")
        for job, reason in report.rejected[:show_rejected]:
            print(f" - {job.company_name}: {job.title} :: {reason}")
    if report.errors:
        header("portais que falharam")
        for key, error in report.errors.items():
            print(f" ! {key}: {error}")
        print("\n Rode 'candidate sources verify' para checar os slugs em config/companies.yaml")


def print_run(report: RunReport) -> None:
    header("resultado da execucao")
    if not report.results and not report.skipped:
        print(" nada a fazer.")
        return
    for result in report.results:
        label = STATUS_LABEL.get(result.status.value, result.status.value)
        print(f" [{label}] {result.job.company_name} — {result.job.title}")
        if result.message:
            print(f"      {result.message}")
        if result.screenshot:
            print(f"      screenshot: {result.screenshot}")
        if result.unanswered_fields:
            preview = ", ".join(result.unanswered_fields[:5])
            extra = "..." if len(result.unanswered_fields) > 5 else ""
            print(f"      campos pendentes: {preview}{extra}")
    if report.skipped:
        print(f"\n {len(report.skipped)} vaga(s) puladas:")
        for job, reason in report.skipped[:10]:
            print(f"   - {job.company_name} — {job.title}: {reason}")


def print_status(store: ApplicationStore, limit: int = 20) -> None:
    stats = store.stats_by_status()
    header("historico de candidaturas")
    if not stats:
        print(" nada registrado ainda. Rode 'candidate discover' e depois 'candidate apply'.")
        return
    for status, count in sorted(stats.items(), key=lambda kv: -kv[1]):
        print(f" {STATUS_LABEL.get(status, status):<28} {count:>4}")
    print(f"\n enviadas hoje: {store.count_submitted_today()}")

    rows = store.list_applications(limit=limit)
    if rows:
        header(f"ultimas {len(rows)} atualizacoes")
        for row in rows:
            label = STATUS_LABEL.get(row.status, row.status)
            print(f" {row.updated_at[:16]}  {label:<26} {row.company_name} — {row.title}")


def export(store: ApplicationStore, out_dir: Path, fmt: str = "csv") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [dict(row) for row in store.iter_all()]
    if fmt == "json":
        path = out_dir / "candidaturas.json"
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    path = out_dir / "candidaturas.csv"
    fields = [
        "company_name", "title", "location", "status", "score",
        "url", "discovered_at", "submitted_at", "message",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path
