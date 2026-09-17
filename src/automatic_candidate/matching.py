"""Filtro e ranking das vagas descobertas.

Regras (config/settings.yaml -> filters):
  - title_include: o titulo precisa conter pelo menos um destes termos;
  - title_exclude: qualquer ocorrencia descarta a vaga;
  - locations_include/exclude: idem para a localidade;
  - posted_within_days: descarta vagas antigas;
  - keywords_boost: soma pontos quando o termo aparece no titulo/descricao.
O score final ordena a fila de candidatura.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta

from automatic_candidate.config import Filters, Profile
from automatic_candidate.models import JobPosting


@dataclass(slots=True)
class MatchDecision:
    keep: bool
    score: int
    reason: str


def normalize(text: str) -> str:
    """Minusculas sem acento — 'Engenheiro de Software' casa com 'engenheiro'."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return without_accents.lower()


def evaluate(job: JobPosting, filters: Filters, profile: Profile | None = None) -> MatchDecision:
    title = normalize(job.title)
    location = normalize(job.location)
    description = normalize(job.description)

    if filters.title_exclude:
        for term in filters.title_exclude:
            if normalize(term) in title:
                return MatchDecision(False, 0, f"titulo contem termo excluido: {term!r}")

    if filters.title_include:
        if not any(normalize(term) in title for term in filters.title_include):
            return MatchDecision(False, 0, "titulo nao bate com filters.title_include")

    if filters.locations_exclude:
        for term in filters.locations_exclude:
            if normalize(term) in location:
                return MatchDecision(False, 0, f"local excluido: {term!r}")

    if filters.locations_include and location:
        if not any(normalize(term) in location for term in filters.locations_include):
            return MatchDecision(False, 0, f"local fora da lista: {job.location!r}")

    if filters.posted_within_days and job.posted_at:
        cutoff = date.today() - timedelta(days=filters.posted_within_days)
        if job.posted_at < cutoff:
            return MatchDecision(
                False, 0, f"publicada em {job.posted_at}, fora da janela de {filters.posted_within_days} dias"
            )

    score = 1
    matched: list[str] = []
    for keyword, weight in filters.keywords_boost.items():
        key = normalize(keyword)
        if key in title:
            score += weight * 2
            matched.append(f"{keyword} (titulo)")
        elif key in description:
            score += weight
            matched.append(keyword)

    if profile is not None:
        for skill in profile.professional.get("skills", []) or []:
            skill_norm = normalize(str(skill))
            if skill_norm and (skill_norm in title or skill_norm in description):
                score += 1
                matched.append(str(skill))

    if score < filters.min_score:
        return MatchDecision(False, score, f"score {score} < min_score {filters.min_score}")

    reason = "match: " + (", ".join(dict.fromkeys(matched)) if matched else "filtros basicos")
    return MatchDecision(True, score, reason)


def rank(jobs: list[JobPosting]) -> list[JobPosting]:
    """Maior score primeiro; empate resolve pela vaga mais recente."""
    return sorted(
        jobs,
        key=lambda j: (j.score, j.posted_at or date.min),
        reverse=True,
    )
