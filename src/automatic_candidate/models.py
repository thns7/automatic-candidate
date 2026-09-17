"""Estruturas de dados centrais."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any


class SubmitMode(str, Enum):
    """Como a automacao trata o envio final do formulario."""

    DRY_RUN = "dry_run"   # apenas descobre e reporta
    REVIEW = "review"     # preenche, tira screenshot, pede confirmacao
    AUTO = "auto"         # preenche e envia (exige opt-in por empresa)

    @classmethod
    def parse(cls, value: str) -> SubmitMode:
        normalized = str(value).strip().lower().replace("-", "_")
        for mode in cls:
            if mode.value == normalized:
                return mode
        raise ValueError(
            f"submit_mode invalido: {value!r}. Use dry_run, review ou auto."
        )


class ApplyStatus(str, Enum):
    DISCOVERED = "discovered"        # encontrada, ainda nao trabalhada
    FILLED = "filled"                # formulario preenchido, aguardando voce
    SUBMITTED = "submitted"          # enviada
    SKIPPED = "skipped"              # filtrada ou ignorada por voce
    FAILED = "failed"                # erro na automacao
    NEEDS_MANUAL = "needs_manual"    # exige acao humana (2FA, captcha, upload)


@dataclass(slots=True)
class JobPosting:
    """Uma vaga descoberta em algum portal."""

    company_key: str
    company_name: str
    title: str
    url: str
    source: str
    external_id: str = ""
    location: str = ""
    department: str = ""
    employment_type: str = ""
    description: str = ""
    posted_at: date | None = None
    apply_url: str = ""
    score: int = 0
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def fingerprint(self) -> str:
        """Identidade estavel da vaga, usada para nao aplicar duas vezes.

        Usa o id externo quando existe; cai para empresa+titulo+local
        normalizados, porque alguns portais trocam a URL entre coletas.
        """
        if self.external_id:
            base = f"{self.company_key}:{self.source}:{self.external_id}"
        else:
            base = ":".join(
                (
                    self.company_key,
                    _normalize(self.title),
                    _normalize(self.location),
                )
            )
        return hashlib.sha256(base.encode("utf-8")).hexdigest()[:20]

    @property
    def target_url(self) -> str:
        return self.apply_url or self.url

    def summary_line(self) -> str:
        loc = self.location or "local n/d"
        return f"[{self.score:>2}] {self.company_name} — {self.title} ({loc})"


@dataclass(slots=True)
class ApplyResult:
    """Resultado de uma tentativa de candidatura."""

    job: JobPosting
    status: ApplyStatus
    message: str = ""
    screenshot: str = ""
    filled_fields: dict[str, str] = field(default_factory=dict)
    unanswered_fields: list[str] = field(default_factory=list)
    finished_at: datetime = field(default_factory=datetime.now)

    @property
    def ok(self) -> bool:
        return self.status in (ApplyStatus.SUBMITTED, ApplyStatus.FILLED)


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
