"""Ajustes especificos por portal.

Todos herdam do GenericFormApplier: mudam so o que o portal faz de diferente
(login, banner de cookies, botao que abre o formulario).
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from automatic_candidate.appliers.generic_form import GenericFormApplier
from automatic_candidate.models import JobPosting

if TYPE_CHECKING:  # pragma: no cover
    from playwright.sync_api import Page

logger = logging.getLogger(__name__)

COOKIE_RE = re.compile(
    r"(aceitar|aceito|concordo|permitir todos|accept all|accept cookies|allow all|got it|entendi)",
    re.IGNORECASE,
)
LOGIN_FORM_RE = re.compile(
    r"(entrar|fazer login|sign in|log in|acessar minha conta)", re.IGNORECASE
)


class _PortalApplier(GenericFormApplier):
    """Base com utilidades de cookie e login por e-mail/senha."""

    def before_fill(self, page: Page, job: JobPosting) -> None:
        self.dismiss_cookies(page)

    def dismiss_cookies(self, page: Page) -> None:
        button = self.find_button(page, COOKIE_RE)
        if button is None:
            return
        try:
            button.click(timeout=5000)
            page.wait_for_timeout(600)
        except Exception as exc:  # noqa: BLE001
            logger.debug("banner de cookies: %s", exc)

    def login_if_needed(self, page: Page) -> None:
        """Faz login com as credenciais do .env quando a pagina pedir.

        Se houver 2FA/captcha, a automacao para e devolve o controle para voce —
        e o comportamento correto, ninguem burla verificacao aqui.
        """
        email, password = self.ctx.company.credentials()
        prefix = self.ctx.company.login_env_prefix or self.ctx.company.key.upper()
        email_field = page.locator(
            "input[type='email'], input[name*='email' i], input[id*='email' i]"
        ).first
        password_field = page.locator("input[type='password']").first

        try:
            if password_field.count() == 0 or not password_field.is_visible():
                return
        except Exception:  # noqa: BLE001
            return

        if not email or not password:
            self.wait_for_manual_step(
                page,
                f"o portal pediu login e nao achei {prefix}_EMAIL/{prefix}_PASSWORD no .env",
            )
            return

        try:
            if email_field.count() > 0 and email_field.is_visible():
                email_field.fill(email, timeout=10000)
            password_field.fill(password, timeout=10000)
            button = self.find_button(page, LOGIN_FORM_RE)
            if button is not None:
                button.click(timeout=10000)
            else:
                password_field.press("Enter")
            page.wait_for_timeout(4000)
        except Exception as exc:  # noqa: BLE001
            logger.warning("login automatico falhou: %s", exc)
            self.wait_for_manual_step(page, "nao consegui logar automaticamente")


class GreenhouseApplier(_PortalApplier):
    """Greenhouse: formulario embutido no proprio anuncio, sem login."""

    name = "greenhouse"


class LeverApplier(_PortalApplier):
    """Lever: o formulario fica em <url-da-vaga>/apply."""

    name = "lever"

    def apply(self, job: JobPosting):  # type: ignore[override]
        if job.target_url and not job.target_url.rstrip("/").endswith("apply"):
            job.apply_url = job.target_url.rstrip("/") + "/apply"
        return super().apply(job)


class WorkdayApplier(_PortalApplier):
    """Workday (NVIDIA e a maioria das multinacionais).

    Exige conta no tenant. O perfil persistente do navegador guarda a sessao;
    na primeira vez rode 'candidate login <empresa>' e entre na mao.
    """

    name = "workday"

    def before_fill(self, page: Page, job: JobPosting) -> None:
        self.dismiss_cookies(page)
        self.login_if_needed(page)
        # O Workday reaproveita os dados do perfil: quando oferece,
        # 'Autofill with Resume' economiza a maior parte do formulario.
        autofill = self.find_button(page, re.compile(r"(autofill with resume|preencher com curriculo)", re.I))
        if autofill is not None:
            try:
                autofill.click(timeout=8000)
                page.wait_for_timeout(2500)
            except Exception as exc:  # noqa: BLE001
                logger.debug("autofill do Workday: %s", exc)


class GupyApplier(_PortalApplier):
    """Gupy (Itau, Zamp e a maior parte do mercado BR).

    Uma conta Gupy vale para todos os portais. Depois do login, a maioria dos
    campos ja vem do seu perfil Gupy — a automacao completa o resto.
    """

    name = "gupy"

    def before_fill(self, page: Page, job: JobPosting) -> None:
        self.dismiss_cookies(page)
        self.login_if_needed(page)
