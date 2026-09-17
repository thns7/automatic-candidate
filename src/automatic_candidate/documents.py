"""Curriculo e carta de apresentacao.

Curriculo: PDF em data/resumes/, escolhido por empresa (campo 'resume' em
config/companies.yaml aponta para uma chave de documents.resumes no perfil).
Carta: renderizada do template Jinja2 em templates/cover_letter.md.j2 com os
dados da vaga, salva em data/reports/cover_letters/ para anexo ou colagem.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path

from jinja2 import Environment, StrictUndefined, TemplateError

from automatic_candidate.config import CompanyConfig, Profile, RoleProfile, Settings
from automatic_candidate.models import JobPosting

logger = logging.getLogger(__name__)


class DocumentError(RuntimeError):
    pass


def resolve_resume(
    profile: Profile, company: CompanyConfig, role: RoleProfile | None = None
) -> Path:
    """PDF do curriculo a usar.

    Precedencia: variante pedida pela empresa (quando ela pede algo diferente
    de 'default') > variante do cargo ativo > 'default'. Assim a NVIDIA continua
    recebendo o curriculo de ML, e todo o resto recebe o do cargo da vez.
    """
    resumes = profile.get("documents.resumes", {}) or {}
    variant = company.resume or "default"
    if variant == "default" and role and role.resume:
        variant = role.resume
    raw = resumes.get(variant)
    if not raw:
        if variant != "default":
            logger.info(
                "variante de curriculo %r nao existe para %s; usando 'default'",
                variant,
                company.key,
            )
        raw = resumes.get("default")
    if not raw:
        raise DocumentError(
            "Nenhum curriculo configurado. Em config/profile.yaml defina "
            "documents.resumes.default apontando para o PDF (ex: data/resumes/curriculo.pdf)."
        )
    path = Path(str(raw))
    if not path.exists():
        raise DocumentError(
            f"Curriculo nao encontrado: {path}\n"
            "Coloque o arquivo nesse caminho ou corrija documents.resumes em config/profile.yaml."
        )
    return path


def extra_attachments(profile: Profile) -> list[Path]:
    paths: list[Path] = []
    for raw in profile.get("documents.extra_attachments", []) or []:
        path = Path(str(raw))
        if path.exists():
            paths.append(path)
        else:
            logger.warning("anexo extra nao encontrado, ignorando: %s", path)
    return paths


def render_cover_letter(
    profile: Profile, job: JobPosting, template_path: Path | None = None
) -> str:
    """Texto da carta para esta vaga."""
    path = template_path or Path(
        str(profile.get("documents.cover_letter_template", "templates/cover_letter.md.j2"))
    )
    if not path.exists():
        raise DocumentError(
            f"Template de carta nao encontrado: {path}. "
            "Crie o arquivo ou desative cover_letter.enabled em config/settings.yaml."
        )
    env = Environment(undefined=StrictUndefined, autoescape=False, trim_blocks=True, lstrip_blocks=True)
    try:
        template = env.from_string(path.read_text(encoding="utf-8"))
        # O template recebe o dict cru: assim 'profile.experience[0].company'
        # funciona igual ao que esta escrito no config/profile.yaml.
        return template.render(
            profile=profile.data,
            job=job,
            company=job.company_name,
            today=date.today().strftime("%d/%m/%Y"),
        ).strip()
    except TemplateError as exc:
        raise DocumentError(f"erro ao renderizar {path}: {exc}") from exc


def write_cover_letter(
    profile: Profile, settings: Settings, job: JobPosting
) -> Path:
    """Salva a carta em disco e devolve o caminho (para anexar no formulario)."""
    text = render_cover_letter(profile, job)
    out_dir = settings.reports_dir / "cover_letters"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{job.company_key}-{_slug(job.title)}-{job.fingerprint[:8]}.txt"
    path.write_text(text, encoding="utf-8")
    return path


def _slug(text: str, max_len: int = 48) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug[:max_len] or "vaga"
