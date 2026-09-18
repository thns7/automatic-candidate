from __future__ import annotations

from automatic_candidate.answers import AnswerBook, FormField, redact


def test_campos_basicos_vem_do_perfil(example_profile):
    book = AnswerBook(example_profile)
    assert book.resolve(FormField(label="Nome completo")).value == "Seu Nome Completo"
    assert "@" in book.resolve(FormField(label="E-mail *", kind="email")).value
    assert book.resolve(FormField(label="Telefone celular", kind="tel")).value.startswith("+55")
    assert book.resolve(FormField(label="Cidade")).value == "Sao Paulo"


def test_screening_answer_tem_prioridade_sobre_o_builtin(example_profile):
    book = AnswerBook(example_profile)
    answer = book.resolve(FormField(label="Qual sua pretensao salarial?"))
    assert answer.source == "screening_answers"


def test_select_casa_opcao_mesmo_com_acento(example_profile):
    book = AnswerBook(example_profile)
    field = FormField(
        label="Nivel de ingles", kind="select",
        options=["Basico", "Intermediario", "Avancado", "Fluente"],
    )
    assert book.resolve(field).value == "Avancado"


def test_sim_nao_casa_com_yes_no(example_profile):
    book = AnswerBook(example_profile)
    field = FormField(
        label="Are you legally authorized to work?", kind="select", options=["Yes", "No"]
    )
    assert book.resolve(field).value == "Yes"


def test_consentimento_de_termos_e_aceito(example_profile):
    book = AnswerBook(example_profile)
    field = FormField(label="Aceito os termos de uso e a politica de privacidade", kind="checkbox")
    assert book.resolve(field).value == "true"


def test_marketing_e_recusado_por_padrao(example_profile):
    book = AnswerBook(example_profile)
    field = FormField(label="Quero receber novidades e promocoes", kind="checkbox")
    assert book.resolve(field).value == "false"


def test_campo_desconhecido_nao_inventa_resposta(example_profile):
    book = AnswerBook(example_profile)
    assert book.resolve(FormField(label="Codigo interno do indicador")) is None


def test_select_obrigatorio_desconhecido_usa_opcao_neutra(example_profile):
    book = AnswerBook(example_profile)
    field = FormField(
        label="Pergunta esquisita e obrigatoria", kind="select", required=True,
        options=["Opcao A", "Opcao B", "Prefiro nao informar"],
    )
    assert book.resolve(field).value == "Prefiro nao informar"


def test_match_option_por_sobreposicao_de_palavras():
    escolha = AnswerBook.match_option(
        "trabalho remoto integral", ["Presencial", "Hibrido", "Remoto integral"]
    )
    assert escolha == "Remoto integral"


def test_coverage_report_separa_respondidos_de_pendentes(example_profile):
    book = AnswerBook(example_profile)
    fields = [FormField(label="E-mail"), FormField(label="Codigo secreto da matriz")]
    answered, missing = book.coverage_report(fields)
    assert "E-mail" in answered and missing == ["Codigo secreto da matriz"]


def test_redact_esconde_dados_sensiveis():
    assert redact("thiago@exemplo.com").startswith("th***@")
    assert redact("+55 11 99999-1234") == "***1234"
