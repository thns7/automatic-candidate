"""Fluxo da CLI: init, doctor, answers e status."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from automatic_candidate.cli import main

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def projeto(tmp_path, monkeypatch):
    """Um diretorio de trabalho limpo com os modelos de configuracao."""
    (tmp_path / "config").mkdir()
    for name in ("profile.example.yaml", "settings.example.yaml", "companies.example.yaml"):
        shutil.copy(REPO_ROOT / "config" / name, tmp_path / "config" / name)
    shutil.copy(REPO_ROOT / ".env.example", tmp_path / ".env.example")
    shutil.copytree(REPO_ROOT / "templates", tmp_path / "templates")
    monkeypatch.chdir(tmp_path)
    for var in ("CPF", "GUPY_EMAIL", "GUPY_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


def test_init_cria_os_arquivos_do_usuario(projeto, capsys):
    assert main(["init"]) == 0
    for arquivo in ("config/profile.yaml", "config/settings.yaml", "config/companies.yaml", ".env"):
        assert (projeto / arquivo).exists(), arquivo
    saida = capsys.readouterr().out
    assert "config/profile.yaml" in saida and "data/resumes/" in saida


def test_init_nao_sobrescreve_sem_force(projeto):
    main(["init"])
    (projeto / "config" / "profile.yaml").write_text("personal:\n  first_name: Eu\n", encoding="utf-8")
    main(["init"])
    assert "first_name: Eu" in (projeto / "config" / "profile.yaml").read_text(encoding="utf-8")
    main(["init", "--force"])
    assert "first_name: Eu" not in (projeto / "config" / "profile.yaml").read_text(encoding="utf-8")


def test_doctor_sem_configuracao_orienta_o_init(projeto, capsys):
    assert main(["doctor"]) == 1
    assert "candidate init" in capsys.readouterr().out


def test_doctor_acusa_perfil_de_exemplo(projeto, capsys):
    main(["init"])
    assert main(["doctor"]) == 1
    saida = capsys.readouterr().out
    assert "Pendencias" in saida and "curriculo nao encontrado" in saida


def test_doctor_passa_com_perfil_completo(projeto, capsys):
    main(["init"])
    perfil = projeto / "config" / "profile.yaml"
    conteudo = perfil.read_text(encoding="utf-8").replace(
        'email: "seu.email@exemplo.com"', 'email: "thiago@dominio.com"'
    )
    perfil.write_text(conteudo, encoding="utf-8")
    (projeto / "data" / "resumes").mkdir(parents=True, exist_ok=True)
    (projeto / "data" / "resumes" / "curriculo.pdf").write_bytes(b"%PDF-1.4")
    assert main(["doctor"]) == 0
    assert "Tudo certo" in capsys.readouterr().out


def test_answers_mostra_a_resposta_e_a_fonte(projeto, capsys):
    main(["init"])
    assert main(["answers", "Qual sua pretensao salarial?"]) == 0
    saida = capsys.readouterr().out
    assert "screening_answers" in saida


def test_answers_avisa_quando_nao_sabe(projeto, capsys):
    main(["init"])
    main(["answers", "Codigo secreto da matriz"])
    assert "sem resposta" in capsys.readouterr().out


def test_status_com_banco_vazio(projeto, capsys):
    main(["init"])
    assert main(["status"]) == 0
    assert "nada registrado ainda" in capsys.readouterr().out


def test_sources_list_mostra_os_endpoints(projeto, capsys):
    main(["init"])
    assert main(["sources", "list"]) == 0
    saida = capsys.readouterr().out
    assert "myworkdayjobs.com" in saida and "gupy.io" in saida


def test_export_csv(projeto):
    main(["init"])
    assert main(["export", "--format", "csv"]) == 0
    assert (projeto / "data" / "reports" / "candidaturas.csv").exists()


def test_roles_mostra_cargo_ativo_e_proxima_troca(projeto, capsys):
    main(["init"])
    assert main(["roles"]) == 0
    saida = capsys.readouterr().out
    assert ">> estagio" in saida
    assert "proxima troca: junior" in saida


def test_answers_usa_as_respostas_do_cargo_ativo(projeto, capsys):
    main(["init"])
    main(["answers", "Qual a previsao de formatura?"])
    saida = capsys.readouterr().out
    assert "cargo ativo: estagio" in saida
    assert "2028" in saida


def test_role_forcado_pela_linha_de_comando(projeto, capsys):
    main(["init"])
    main(["answers", "Qual sua pretensao salarial?", "--role", "junior"])
    saida = capsys.readouterr().out
    assert "cargo ativo: junior" in saida
    assert "bolsa" not in saida.lower()
