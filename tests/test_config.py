from __future__ import annotations

from pathlib import Path

import pytest

from automatic_candidate.config import ConfigError, load_companies, load_settings
from automatic_candidate.models import SubmitMode

EXAMPLES = Path(__file__).resolve().parents[1] / "config"


def test_settings_example_carrega(example_settings):
    assert example_settings.submit_mode is SubmitMode.REVIEW
    assert example_settings.limits.max_applications_per_run > 0
    assert "python" in example_settings.filters.keywords_boost


def test_companies_example_tem_as_empresas_alvo():
    companies = load_companies(EXAMPLES / "companies.example.yaml")
    keys = {c.key for c in companies}
    assert {"itau", "nvidia", "google", "microsoft", "zamp"} <= keys


def test_auto_submit_e_desligado_por_padrao():
    for company in load_companies(EXAMPLES / "companies.example.yaml"):
        assert company.allow_auto_submit is False


def test_credenciais_vem_do_ambiente(monkeypatch):
    companies = {c.key: c for c in load_companies(EXAMPLES / "companies.example.yaml")}
    monkeypatch.setenv("NVIDIA_EMAIL", "eu@exemplo.com")
    monkeypatch.setenv("NVIDIA_PASSWORD", "segredo")
    assert companies["nvidia"].credentials() == ("eu@exemplo.com", "segredo")


def test_expansao_de_variavel_de_ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("CPF", "123.456.789-00")
    path = tmp_path / "profile.yaml"
    path.write_text("personal:\n  cpf: '${CPF}'\n", encoding="utf-8")
    from automatic_candidate.config import load_profile

    assert load_profile(path).get("personal.cpf") == "123.456.789-00"


def test_arquivo_faltando_da_mensagem_util(tmp_path):
    with pytest.raises(ConfigError, match="cp config/settings.example.yaml"):
        load_settings(tmp_path / "settings.yaml")


def test_submit_mode_invalido():
    with pytest.raises(ValueError, match="submit_mode invalido"):
        SubmitMode.parse("enviar-tudo")


def test_perfil_exemplo_acusa_pendencias(example_profile):
    problems = example_profile.validate()
    assert any("email" in p for p in problems)
