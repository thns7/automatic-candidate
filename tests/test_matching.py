from __future__ import annotations

from datetime import date, timedelta

from automatic_candidate.config import Filters
from automatic_candidate.matching import evaluate, normalize, rank
from automatic_candidate.models import JobPosting


def job(title="Engenheiro de Software", location="Sao Paulo, Brasil", description="", posted=None):
    return JobPosting(
        company_key="x", company_name="X", title=title, url="http://x",
        source="teste", location=location, description=description, posted_at=posted,
    )


BASE = Filters(
    title_include=["engenheir", "engineer", "developer"],
    title_exclude=["estagi", "intern", "manager"],
    locations_include=["brasil", "remote"],
    keywords_boost={"python": 3, "kubernetes": 2},
    min_score=1,
)


def test_normalize_remove_acentos():
    assert normalize("Engenheiro de Software Sênior") == "engenheiro de software senior"


def test_titulo_incluido_passa():
    assert evaluate(job(), BASE).keep is True


def test_titulo_excluido_reprova():
    decision = evaluate(job(title="Estagiario de Engenharia"), BASE)
    assert decision.keep is False and "excluido" in decision.reason


def test_local_fora_da_lista_reprova():
    assert evaluate(job(location="Tokyo, Japan"), BASE).keep is False


def test_vaga_remota_passa():
    assert evaluate(job(location="Remote - LATAM"), BASE).keep is True


def test_keyword_no_titulo_vale_o_dobro():
    no_titulo = evaluate(job(title="Engenheiro de Software Python"), BASE).score
    na_descricao = evaluate(job(description="stack em Python"), BASE).score
    assert no_titulo > na_descricao > 1


def test_vaga_antiga_reprova():
    filters = Filters(title_include=["engenheir"], posted_within_days=30, min_score=1)
    velha = job(posted=date.today() - timedelta(days=90))
    nova = job(posted=date.today() - timedelta(days=2))
    assert evaluate(velha, filters).keep is False
    assert evaluate(nova, filters).keep is True


def test_skills_do_perfil_somam_pontos(example_profile):
    com_perfil = evaluate(job(description="usamos Docker e AWS"), BASE, example_profile).score
    sem_perfil = evaluate(job(description="usamos Docker e AWS"), BASE).score
    assert com_perfil > sem_perfil


def test_rank_ordena_por_score():
    a, b = job(), job()
    a.score, b.score = 3, 9
    assert rank([a, b])[0] is b


def test_sem_filtro_de_titulo_aceita_tudo():
    assert evaluate(job(title="Qualquer Coisa"), Filters(min_score=1)).keep is True
