"""Preenchedor generico de formularios de candidatura.

Funciona em qualquer formulario HTML: detecta os campos visiveis, descobre o
rotulo de cada um (label, aria-label, legenda do fieldset, texto anterior),
pergunta a resposta ao AnswerBook e preenche. Anexa curriculo e carta.

Por padrao NAO envia: para no modo review, tira screenshot e espera sua
confirmacao no terminal. Envio automatico exige opt-in em settings.yaml
(submit_mode: auto) E na empresa (allow_auto_submit: true).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from automatic_candidate.answers import Answer, FormField
from automatic_candidate.appliers.base import Applier
from automatic_candidate.models import ApplyResult, ApplyStatus, JobPosting, SubmitMode

if TYPE_CHECKING:  # pragma: no cover
    from playwright.sync_api import Locator, Page

logger = logging.getLogger(__name__)

_DOM_SCRIPT = (Path(__file__).parent / "_dom.js").read_text(encoding="utf-8")

# Botoes que levam do anuncio ao formulario
APPLY_BUTTON_RE = re.compile(
    r"(candidatar|candidate-se|inscrever|aplicar|quero me candidatar"
    r"|apply now|apply for|submit application|start your application)",
    re.IGNORECASE,
)
# Botao que efetivamente envia
SUBMIT_BUTTON_RE = re.compile(
    r"^(enviar|enviar candidatura|finalizar|concluir|submit|submit application|send application)\b",
    re.IGNORECASE,
)
# Avancar em formularios multi-etapa
NEXT_BUTTON_RE = re.compile(r"^(proximo|próximo|continuar|avancar|avançar|next|continue)\b", re.IGNORECASE)

RESUME_HINT_RE = re.compile(r"(curric|resume|\bcv\b|attach.*resume)", re.IGNORECASE)
COVER_HINT_RE = re.compile(r"(carta|cover.?letter|apresentacao|apresentação|motivation)", re.IGNORECASE)
CONFIRMATION_RE = re.compile(
    r"(candidatura (enviada|realizada|recebida)|inscricao realizada"
    r"|application (submitted|received|complete)"
    r"|obrigado por se candidatar|thank you for applying)",
    re.IGNORECASE,
)
# Sinais de que a automacao nao deve seguir sozinha
MANUAL_STEP_RE = re.compile(
    r"(captcha|recaptcha|hcaptcha|verifique que voce|verify you are human"
    r"|two-?factor|autenticacao em duas etapas"
    r"|codigo de verificacao|verification code)",
    re.IGNORECASE,
)


class GenericFormApplier(Applier):
    name = "generic"

    # ------------------------------------------------------------------ fluxo
    def apply(self, job: JobPosting) -> ApplyResult:
        ctx = self.ctx
        with ctx.browser.page(job.target_url) as page:
            page.wait_for_timeout(1200)

            if self._needs_human(page):
                shot = ctx.browser.screenshot(page, f"{job.company_key}-manual")
                self.wait_for_manual_step(page, "a pagina pediu captcha/2FA ou login")
                if self._needs_human(page):
                    return self.result(
                        job,
                        ApplyStatus.NEEDS_MANUAL,
                        "pagina exige acao humana (captcha/2FA/login)",
                        screenshot=shot,
                    )

            self.open_application_form(page)
            self.before_fill(page, job)

            filled, missing = self.fill_form(page)
            uploaded = self.upload_documents(page)
            filled.update(uploaded)

            self.advance_multi_step(page)

            screenshot = ctx.browser.screenshot(page, f"{job.company_key}-{job.title}")

            if ctx.submit_mode is SubmitMode.DRY_RUN:
                return self.result(
                    job, ApplyStatus.FILLED, "dry-run: formulario nao foi enviado",
                    screenshot=screenshot, filled_fields=filled, unanswered_fields=missing,
                )

            should_submit = ctx.may_auto_submit()
            if not should_submit and ctx.submit_mode is SubmitMode.REVIEW:
                should_submit = self.confirm_submit(job, missing, screenshot)

            if not should_submit:
                return self.result(
                    job, ApplyStatus.FILLED,
                    "preenchido; envio nao confirmado (revise no navegador)",
                    screenshot=screenshot, filled_fields=filled, unanswered_fields=missing,
                )

            if missing and ctx.may_auto_submit():
                logger.warning(
                    "%s: enviando com %d campo(s) sem resposta automatica", job.title, len(missing)
                )

            submitted = self.submit(page)
            final_shot = ctx.browser.screenshot(page, f"{job.company_key}-apos-envio")
            if not submitted:
                return self.result(
                    job, ApplyStatus.NEEDS_MANUAL,
                    "nao encontrei o botao de envio — finalize manualmente",
                    screenshot=final_shot, filled_fields=filled, unanswered_fields=missing,
                )
            confirmed = self.confirm_submission(page)
            return self.result(
                job,
                ApplyStatus.SUBMITTED if confirmed else ApplyStatus.NEEDS_MANUAL,
                "candidatura enviada" if confirmed else "enviei o formulario mas nao vi confirmacao — confira",
                screenshot=final_shot,
                filled_fields=filled,
                unanswered_fields=missing,
            )

    # ------------------------------------------------- pontos de extensao
    def before_fill(self, page: Page, job: JobPosting) -> None:
        """Gancho para os appliers especificos (login, aceitar cookies, etc.)."""

    # ----------------------------------------------------------- navegacao
    def open_application_form(self, page: Page) -> None:
        """Clica no botao 'Candidatar-se' quando o formulario nao esta na pagina."""
        if self.count_fields(page) >= 3:
            return
        for _ in range(2):
            button = self.find_button(page, APPLY_BUTTON_RE)
            if button is None:
                break
            try:
                button.click(timeout=self.ctx.settings.browser.timeout_ms)
                page.wait_for_load_state("domcontentloaded")
                page.wait_for_timeout(1500)
            except Exception as exc:  # noqa: BLE001
                logger.debug("clique em 'candidatar' falhou: %s", exc)
                break
            if self.count_fields(page) >= 3:
                return

    def advance_multi_step(self, page: Page, max_steps: int = 4) -> None:
        """Formularios em etapas: preenche, clica em 'Proximo', preenche de novo."""
        for step in range(max_steps):
            button = self.find_button(page, NEXT_BUTTON_RE)
            if button is None:
                return
            before = self.count_fields(page)
            try:
                button.click(timeout=self.ctx.settings.browser.timeout_ms)
                page.wait_for_timeout(1800)
            except Exception as exc:  # noqa: BLE001
                logger.debug("etapa %s: clique em 'proximo' falhou: %s", step + 1, exc)
                return
            filled, _ = self.fill_form(page)
            self.upload_documents(page)
            if not filled and self.count_fields(page) == before:
                return

    def submit(self, page: Page) -> bool:
        button = self.find_button(page, SUBMIT_BUTTON_RE)
        if button is None:
            return False
        try:
            button.click(timeout=self.ctx.settings.browser.timeout_ms)
            page.wait_for_timeout(4000)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("clique no botao de envio falhou: %s", exc)
            return False

    def confirm_submission(self, page: Page) -> bool:
        try:
            body = page.inner_text("body")[:6000]
        except Exception:  # noqa: BLE001
            return False
        return bool(CONFIRMATION_RE.search(body))

    # ----------------------------------------------------- deteccao de campos
    def describe_fields(self, page: Page) -> list[dict[str, Any]]:
        try:
            return list(page.evaluate(_DOM_SCRIPT) or [])
        except Exception as exc:  # noqa: BLE001
            logger.warning("nao consegui ler os campos da pagina: %s", exc)
            return []

    def count_fields(self, page: Page) -> int:
        return len([d for d in self.describe_fields(page) if d.get("kind") != "file"])

    @staticmethod
    def group_radios(descriptors: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Junta os radios do mesmo 'name' num unico campo com opcoes."""
        grouped: list[dict[str, Any]] = []
        radios: dict[str, dict[str, Any]] = {}
        for descriptor in descriptors:
            if descriptor.get("kind") != "radio":
                grouped.append(descriptor)
                continue
            key = descriptor.get("name") or descriptor.get("groupLabel") or str(descriptor["idx"])
            entry = radios.get(key)
            if entry is None:
                entry = {
                    "kind": "radio",
                    "name": descriptor.get("name", ""),
                    "label": descriptor.get("groupLabel") or descriptor.get("name", ""),
                    "placeholder": "",
                    "required": False,
                    "options": [],
                    "members": [],
                    "idx": descriptor["idx"],
                }
                radios[key] = entry
                grouped.append(entry)   # uma entrada por grupo de radios
            option = descriptor.get("optionLabel") or descriptor.get("value") or ""
            entry["options"].append(option)
            entry["members"].append({"idx": descriptor["idx"], "option": option})
            entry["required"] = entry["required"] or bool(descriptor.get("required"))
        return grouped

    def locator(self, page: Page, idx: int) -> Locator:
        return page.locator(f'[data-ac-idx="{idx}"]').first

    # ------------------------------------------------------------ preenchimento
    def fill_form(self, page: Page) -> tuple[dict[str, str], list[str]]:
        """Preenche tudo que souber. Retorna (preenchidos, rotulos pendentes)."""
        descriptors = self.group_radios(self.describe_fields(page))
        filled: dict[str, str] = {}
        missing: list[str] = []

        for descriptor in descriptors:
            kind = str(descriptor.get("kind", "text"))
            if kind == "file":
                continue  # tratado em upload_documents
            label = str(descriptor.get("label") or descriptor.get("name") or "")
            form_field = FormField(
                label=label,
                kind=kind,
                name=str(descriptor.get("name", "")),
                placeholder=str(descriptor.get("placeholder", "")),
                required=bool(descriptor.get("required")),
                options=[str(o) for o in (descriptor.get("options") or [])],
            )
            answer = self.ctx.answers.resolve(form_field)
            if answer is None or not answer.value:
                if form_field.required or kind != "checkbox":
                    missing.append(label or f"campo #{descriptor.get('idx')}")
                continue
            if self.write_field(page, descriptor, form_field, answer):
                filled[label or form_field.name] = answer.value
            else:
                missing.append(label or f"campo #{descriptor.get('idx')}")
        return filled, missing

    def write_field(
        self, page: Page, descriptor: dict[str, Any], form_field: FormField, answer: Answer
    ) -> bool:
        kind = form_field.kind
        timeout = self.ctx.settings.browser.timeout_ms
        try:
            if kind == "radio":
                target = answer.option or answer.value
                for member in descriptor.get("members", []):
                    if self.ctx.answers.match_option(target, [member["option"]]):
                        self.locator(page, member["idx"]).check(timeout=timeout, force=True)
                        return True
                return False

            element = self.locator(page, int(descriptor["idx"]))

            if kind == "checkbox":
                if answer.value.lower() in {"true", "sim", "yes", "1"}:
                    element.check(timeout=timeout, force=True)
                else:
                    element.uncheck(timeout=timeout, force=True)
                return True

            if kind == "select":
                option = answer.option or answer.value
                try:
                    element.select_option(label=option, timeout=timeout)
                except Exception:  # noqa: BLE001 - alguns selects usam value
                    element.select_option(value=option, timeout=timeout)
                return True

            if kind == "combobox":
                element.click(timeout=timeout)
                element.fill(answer.value, timeout=timeout)
                page.wait_for_timeout(800)
                option = page.locator(
                    f'[role="option"]:has-text("{answer.value[:30]}")'
                ).first
                if option.count() > 0:
                    option.click(timeout=timeout)
                else:
                    element.press("Enter")
                return True

            element.fill(answer.value, timeout=timeout)
            return True
        except Exception as exc:  # noqa: BLE001 - um campo ruim nao derruba a vaga
            logger.debug("nao consegui preencher %r: %s", form_field.label, exc)
            return False

    # ------------------------------------------------------------- documentos
    def upload_documents(self, page: Page) -> dict[str, str]:
        """Anexa curriculo (e carta, quando existe campo para isso)."""
        uploaded: dict[str, str] = {}
        descriptors = [d for d in self.describe_fields(page) if d.get("kind") == "file"]
        if not descriptors:
            return uploaded

        cover = self.ctx.cover_letter
        extras = list(self.ctx.attachments)
        resume_done = False

        for descriptor in descriptors:
            label = str(descriptor.get("label") or descriptor.get("name") or "arquivo")
            haystack = " ".join(
                str(descriptor.get(key, "")) for key in ("label", "name", "placeholder")
            )
            if COVER_HINT_RE.search(haystack) and cover is not None:
                path, tag = cover, "carta de apresentacao"
            elif RESUME_HINT_RE.search(haystack) or not resume_done:
                path, tag = self.ctx.resume, "curriculo"
            elif extras:
                path, tag = extras.pop(0), "anexo"
            else:
                continue

            try:
                self.locator(page, int(descriptor["idx"])).set_input_files(
                    str(path), timeout=self.ctx.settings.browser.timeout_ms
                )
                page.wait_for_timeout(1200)
                uploaded[label] = f"{tag}: {path.name}"
                if tag == "curriculo":
                    resume_done = True
            except Exception as exc:  # noqa: BLE001
                logger.warning("falha ao anexar %s em %r: %s", path, label, exc)
        return uploaded

    # ------------------------------------------------------------- utilidades
    def find_button(self, page: Page, pattern: re.Pattern[str]) -> Locator | None:
        """Primeiro botao/link visivel cujo texto casa com o padrao."""
        candidates = page.locator(
            "button, a[role='button'], input[type='submit'], [role='button']"
        )
        try:
            total = min(candidates.count(), 60)
        except Exception:  # noqa: BLE001
            return None
        for index in range(total):
            element = candidates.nth(index)
            try:
                if not element.is_visible():
                    continue
                text = (element.inner_text(timeout=2000) or "").strip()
                if not text:
                    text = (element.get_attribute("value") or "").strip()
            except Exception:  # noqa: BLE001
                continue
            if text and pattern.search(text):
                return element
        return None

    def _needs_human(self, page: Page) -> bool:
        try:
            body = page.inner_text("body")[:4000]
        except Exception:  # noqa: BLE001
            return False
        return bool(MANUAL_STEP_RE.search(body))
