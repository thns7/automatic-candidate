"""Teste de integracao: preenche um formulario real de candidatura.

Usa tests/fixtures_form.html, que reproduz os padroes dos portais
(label/for, aria-label, legenda de fieldset, select, radio, checkbox de
consentimento e dois inputs de arquivo). Pula se o Playwright/Chromium
nao estiverem instalados.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from automatic_candidate.answers import AnswerBook
from automatic_candidate.appliers import ApplyContext, GenericFormApplier
from automatic_candidate.browser import BrowserSession, playwright_available
from automatic_candidate.config import CompanyConfig
from automatic_candidate.models import ApplyStatus, JobPosting, SubmitMode

pytestmark = pytest.mark.skipif(
    not playwright_available(), reason="Playwright nao instalado (pip install playwright)"
)


@pytest.fixture
def applier(tmp_path, example_profile, example_settings, chromium_path, monkeypatch):
    if not chromium_path:
        pytest.skip("nenhum Chromium disponivel")

    settings = example_settings
    settings.submit_mode = SubmitMode.DRY_RUN
    settings.browser.headless = True
    settings.browser.executable_path = chromium_path
    settings.browser.user_data_dir = tmp_path / "perfil"
    settings.browser.screenshot_dir = tmp_path / "shots"

    resume = tmp_path / "curriculo.pdf"
    resume.write_bytes(b"%PDF-1.4 curriculo de teste")
    cover = tmp_path / "carta.txt"
    cover.write_text("carta de teste", encoding="utf-8")

    company = CompanyConfig(key="teste", name="Empresa Teste", apply={"applier": "generic"})
    session = BrowserSession(settings.browser)
    session.start()
    context = ApplyContext(
        profile=example_profile, settings=settings, company=company,
        answers=AnswerBook(example_profile), browser=session,
        resume=resume, cover_letter=cover,
    )
    try:
        yield GenericFormApplier(context)
    finally:
        session.close()


def _job(form_url: str) -> JobPosting:
    return JobPosting(
        company_key="teste", company_name="Empresa Teste",
        title="Engenheiro de Software Backend", url=form_url, source="manual",
    )


def test_preenche_o_formulario_inteiro(applier, form_url):
    result = applier.apply(_job(form_url))
    assert result.status is ApplyStatus.FILLED
    preenchidos = " | ".join(result.filled_fields)
    for esperado in ("Nome completo", "E-mail", "Telefone", "Cidade", "salarial"):
        assert esperado in preenchidos


def test_select_radio_e_checkbox_sao_tratados(applier, form_url):
    filled = applier.apply(_job(form_url)).filled_fields
    valores = {k: v for k, v in filled.items()}
    assert any("inglês" in k or "ingles" in k for k in valores)
    assert any("mudança" in k or "mudanca" in k for k in valores)
    termos = [v for k, v in valores.items() if "termos" in k]
    marketing = [v for k, v in valores.items() if "novidades" in k]
    assert termos == ["true"] and marketing == ["false"]


def test_curriculo_e_carta_vao_para_campos_diferentes(applier, form_url):
    filled = applier.apply(_job(form_url)).filled_fields
    anexos = [v for v in filled.values() if v.startswith(("curriculo:", "carta de apresentacao:"))]
    assert any(v.startswith("curriculo:") for v in anexos)
    assert any(v.startswith("carta de apresentacao:") for v in anexos)


def test_campo_desconhecido_vira_pendencia_em_vez_de_chute(applier, form_url):
    result = applier.apply(_job(form_url))
    assert any("indicador" in campo for campo in result.unanswered_fields)


def test_dry_run_nao_envia(applier, form_url):
    result = applier.apply(_job(form_url))
    assert result.status is ApplyStatus.FILLED
    assert "nao foi enviado" in result.message


def test_gera_screenshot(applier, form_url):
    result = applier.apply(_job(form_url))
    assert result.screenshot and Path(result.screenshot).exists()


def test_modo_auto_envia_e_detecta_confirmacao(applier, form_url):
    applier.ctx.settings.submit_mode = SubmitMode.AUTO
    applier.ctx.company.apply["allow_auto_submit"] = True
    result = applier.apply(_job(form_url))
    assert result.status is ApplyStatus.SUBMITTED
    assert "enviada" in result.message


def test_auto_sem_opt_in_da_empresa_nao_envia(applier, form_url, monkeypatch):
    applier.ctx.settings.submit_mode = SubmitMode.AUTO
    applier.ctx.company.apply["allow_auto_submit"] = False
    monkeypatch.setattr(GenericFormApplier, "confirm_submit", lambda *a, **k: False)
    result = applier.apply(_job(form_url))
    assert result.status is ApplyStatus.FILLED
