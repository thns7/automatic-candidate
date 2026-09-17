"""Cargo alvo com janela de validade: estagio agora, outro cargo mais tarde."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from automatic_candidate.answers import AnswerBook, FormField
from automatic_candidate.config import ConfigError, Profile, load_settings
from automatic_candidate.documents import resolve_resume
from automatic_candidate.matching import evaluate
from automatic_candidate.models import JobPosting

EXEMPLO = Path(__file__).resolve().parents[1] / "config" / "settings.example.yaml"

HOJE = date(2026, 9, 17)
DURANTE_2027 = date(2027, 6, 1)
DEPOIS = date(2028, 3, 1)


@pytest.fixture(scope="module")
def settings():
    return load_settings(EXEMPLO)


def vaga(titulo: str) -> JobPosting:
    return JobPosting(
        company_key="x", company_name="X", title=titulo, url="http://v",
        source="gupy", location="Sao Paulo, Brasil",
    )


def passa(settings, titulo: str, quando: date, profile: Profile | None = None) -> bool:
    role = settings.resolve_role(quando)
    return evaluate(vaga(titulo), settings.effective_filters(role), profile).keep


# --------------------------------------------------------------- janela de datas
def test_estagio_e_o_cargo_ativo_hoje(settings):
    assert settings.resolve_role(HOJE).name == "estagio"


def test_estagio_continua_valendo_durante_2027(settings):
    assert settings.resolve_role(DURANTE_2027).name == "estagio"
    assert settings.resolve_role(date(2027, 12, 31)).name == "estagio"


def test_junior_assume_sozinho_em_2028(settings):
    assert settings.resolve_role(date(2028, 1, 1)).name == "junior"
    assert settings.resolve_role(DEPOIS).name == "junior"


def test_pleno_assume_em_2030(settings):
    assert settings.resolve_role(date(2030, 6, 1)).name == "pleno"


def test_proxima_troca_e_anunciada(settings):
    proximo = settings.next_role_after(HOJE)
    assert proximo.name == "junior" and proximo.valid_from == date(2028, 1, 1)


# ------------------------------------------------------------- efeito nos filtros
def test_estagio_aceita_vaga_de_estagio(settings):
    for titulo in (
        "Estágio em Desenvolvimento de Software",
        "Estagiário de Dados (Python)",
        "Internship - Software Engineering",
    ):
        assert passa(settings, titulo, HOJE), titulo


def test_estagio_barra_vaga_efetiva(settings):
    assert not passa(settings, "Desenvolvedor Backend Júnior", HOJE)
    assert not passa(settings, "Senior Software Engineer", HOJE)


def test_estagio_barra_area_fora_de_tecnologia(settings):
    assert not passa(settings, "Estágio em Vendas", HOJE)


def test_em_2028_a_logica_se_inverte(settings):
    assert passa(settings, "Desenvolvedor Backend Júnior", DEPOIS)
    assert not passa(settings, "Estágio em Desenvolvimento de Software", DEPOIS)


def test_filtro_do_cargo_substitui_a_base_em_vez_de_somar(settings):
    """A base exclui 'estagi'; o cargo de estagio precisa apagar essa exclusao."""
    assert "estagi" in settings.filters.title_exclude
    filtros = settings.effective_filters(settings.resolve_role(HOJE))
    assert "estagi" not in filtros.title_exclude


def test_chave_nao_declarada_pelo_cargo_herda_da_base(settings):
    filtros = settings.effective_filters(settings.resolve_role(HOJE))
    assert filtros.locations_include == settings.filters.locations_include


# ------------------------------------------------------------------- escolha manual
def test_role_forcado_ignora_a_data(settings):
    assert settings.resolve_role(HOJE, override="junior").name == "junior"


def test_role_inexistente_lista_as_opcoes(settings):
    with pytest.raises(ConfigError, match="estagio"):
        settings.resolve_role(HOJE, override="diretor")


def test_active_role_fixo_vence_a_data(settings):
    settings.active_role = "pleno"
    try:
        assert settings.resolve_role(HOJE).name == "pleno"
    finally:
        settings.active_role = "auto"


def test_sem_cargos_configurados_usa_os_filtros_base(settings):
    settings_sem_cargo = load_settings(EXEMPLO)
    settings_sem_cargo.roles = []
    assert settings_sem_cargo.resolve_role(HOJE) is None
    assert settings_sem_cargo.effective_filters(None) is settings_sem_cargo.filters


# ------------------------------------------------ respostas e curriculo por cargo
def test_cargo_traz_respostas_de_triagem_proprias(settings, example_profile):
    role = settings.resolve_role(HOJE)
    book = AnswerBook(example_profile, extra_answers=role.screening_answers)
    resposta = book.resolve(FormField(label="Qual a previsão de formatura?"))
    assert resposta is not None and "2028" in resposta.value


def test_resposta_do_cargo_vence_a_do_perfil(settings, example_profile):
    role = settings.resolve_role(HOJE)
    pergunta = FormField(label="Qual sua pretensão salarial?")
    sem_cargo = AnswerBook(example_profile).resolve(pergunta).value
    com_cargo = AnswerBook(example_profile, extra_answers=role.screening_answers).resolve(pergunta)
    assert "bolsa" in com_cargo.value.lower()
    assert com_cargo.value != sem_cargo


def test_dados_academicos_respondem_sem_regra_extra(example_profile):
    book = AnswerBook(example_profile)
    assert book.resolve(FormField(label="Instituição de ensino")).value == "Universidade Exemplo"
    assert book.resolve(FormField(label="Semestre atual")).value == "5o semestre"


def test_cargo_escolhe_a_variante_do_curriculo(settings, tmp_path, example_profile):
    from automatic_candidate.config import CompanyConfig

    padrao = tmp_path / "curriculo.pdf"
    estagio = tmp_path / "curriculo-estagio.pdf"
    padrao.write_bytes(b"%PDF")
    estagio.write_bytes(b"%PDF")
    perfil = Profile(
        {"documents": {"resumes": {"default": str(padrao), "estagio": str(estagio)}}}
    )
    empresa = CompanyConfig(key="acme", name="Acme")
    role = settings.resolve_role(HOJE)
    assert resolve_resume(perfil, empresa, role) == estagio
    assert resolve_resume(perfil, empresa, None) == padrao


def test_pedido_explicito_da_empresa_vence_o_cargo(settings, tmp_path):
    from automatic_candidate.config import CompanyConfig

    padrao = tmp_path / "curriculo.pdf"
    estagio = tmp_path / "curriculo-estagio.pdf"
    ml = tmp_path / "curriculo-ml.pdf"
    for arquivo in (padrao, estagio, ml):
        arquivo.write_bytes(b"%PDF")
    perfil = Profile(
        {"documents": {"resumes": {"default": str(padrao), "estagio": str(estagio), "ai": str(ml)}}}
    )
    empresa = CompanyConfig(key="nvidia", name="NVIDIA", resume="ai")
    assert resolve_resume(perfil, empresa, settings.resolve_role(HOJE)) == ml


# ------------------------------------------------------------------- validacao
def test_data_invalida_no_cargo(tmp_path):
    arquivo = tmp_path / "settings.yaml"
    arquivo.write_text(
        "roles:\n  - name: estagio\n    valid_until: '31/12/2027'\n", encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="AAAA-MM-DD"):
        load_settings(arquivo)


def test_janela_invertida_e_recusada(tmp_path):
    arquivo = tmp_path / "settings.yaml"
    arquivo.write_text(
        "roles:\n  - name: x\n    valid_from: '2028-01-01'\n    valid_until: '2027-01-01'\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="depois de"):
        load_settings(arquivo)


def test_cargo_sem_nome_e_recusado(tmp_path):
    arquivo = tmp_path / "settings.yaml"
    arquivo.write_text("roles:\n  - description: sem nome\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="sem 'name'"):
        load_settings(arquivo)
