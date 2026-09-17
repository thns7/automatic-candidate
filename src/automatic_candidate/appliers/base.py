"""Contrato dos preenchedores de formulario."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from automatic_candidate.answers import AnswerBook
from automatic_candidate.browser import BrowserSession
from automatic_candidate.config import CompanyConfig, Profile, Settings
from automatic_candidate.models import ApplyResult, ApplyStatus, JobPosting, SubmitMode

if TYPE_CHECKING:  # pragma: no cover
    from playwright.sync_api import Page

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ApplyContext:
    """Tudo que um applier precisa para trabalhar uma vaga."""

    profile: Profile
    settings: Settings
    company: CompanyConfig
    answers: AnswerBook
    browser: BrowserSession
    resume: Path
    cover_letter: Path | None = None
    attachments: tuple[Path, ...] = ()

    @property
    def submit_mode(self) -> SubmitMode:
        return self.settings.submit_mode

    def may_auto_submit(self) -> bool:
        """Auto-submit exige opt-in nos DOIS lugares: settings e empresa."""
        return self.submit_mode is SubmitMode.AUTO and self.company.allow_auto_submit


class Applier(ABC):
    """Preenche (e opcionalmente envia) a candidatura de uma vaga."""

    name: str = "base"

    def __init__(self, context: ApplyContext) -> None:
        self.ctx = context

    @abstractmethod
    def apply(self, job: JobPosting) -> ApplyResult:
        """Executa o fluxo para uma vaga."""

    # ------------------------------------------------------------- utilidades
    def result(
        self,
        job: JobPosting,
        status: ApplyStatus,
        message: str = "",
        **kwargs: object,
    ) -> ApplyResult:
        return ApplyResult(job=job, status=status, message=message, **kwargs)  # type: ignore[arg-type]

    def confirm_submit(self, job: JobPosting, missing: list[str], screenshot: str) -> bool:
        """Pergunta ao usuario, no terminal, se pode enviar (modo review)."""
        print()
        print("=" * 72)
        print(f"  {job.company_name} — {job.title}")
        print(f"  {job.target_url}")
        if screenshot:
            print(f"  screenshot: {screenshot}")
        if missing:
            print("  campos SEM resposta automatica (revise no navegador):")
            for label in missing[:15]:
                print(f"    - {label}")
            if len(missing) > 15:
                print(f"    ... e mais {len(missing) - 15}")
        else:
            print("  todos os campos detectados foram preenchidos")
        print("=" * 72)
        try:
            answer = input("Enviar esta candidatura? [s/N/q para sair] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return False
        if answer in {"q", "quit", "sair"}:
            raise KeyboardInterrupt("interrompido pelo usuario")
        return answer in {"s", "sim", "y", "yes"}

    def wait_for_manual_step(self, page: Page, reason: str) -> None:
        """Pausa para voce resolver 2FA/captcha na mao — nada e burlado aqui."""
        print(f"\n[acao manual necessaria] {reason}")
        print("Resolva no navegador aberto e volte aqui.")
        try:
            input("Pressione ENTER quando terminar... ")
        except (EOFError, KeyboardInterrupt):
            print()
