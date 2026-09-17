from __future__ import annotations

from automatic_candidate.models import ApplyResult, ApplyStatus, JobPosting
from automatic_candidate.storage import ApplicationStore


def job(title="Engenheiro de Software", company="itau", external_id="1"):
    return JobPosting(
        company_key=company, company_name=company.title(), title=title,
        url="http://vaga", source="gupy", external_id=external_id,
    )


def store(tmp_path) -> ApplicationStore:
    return ApplicationStore(tmp_path / "apps.sqlite3")


def test_descoberta_e_idempotente(tmp_path):
    db, vaga = store(tmp_path), job()
    assert db.record_discovery(vaga) is True
    assert db.record_discovery(vaga) is False


def test_vaga_enviada_nao_e_retrabalhada(tmp_path):
    db, vaga = store(tmp_path), job()
    db.record_result(ApplyResult(job=vaga, status=ApplyStatus.SUBMITTED, message="ok"))
    assert db.already_handled(vaga.fingerprint) == "submitted"


def test_vaga_apenas_descoberta_continua_disponivel(tmp_path):
    db, vaga = store(tmp_path), job()
    db.record_discovery(vaga)
    assert db.already_handled(vaga.fingerprint) is None


def test_contagem_diaria_por_empresa(tmp_path):
    db = store(tmp_path)
    for i in range(3):
        db.record_result(
            ApplyResult(job=job(title=f"Vaga {i}", external_id=str(i)), status=ApplyStatus.SUBMITTED)
        )
    db.record_result(
        ApplyResult(job=job(company="nvidia", external_id="9"), status=ApplyStatus.SUBMITTED)
    )
    assert db.count_submitted_today() == 4
    assert db.count_submitted_today("itau") == 3


def test_resultado_atualiza_status_existente(tmp_path):
    db, vaga = store(tmp_path), job()
    db.record_discovery(vaga)
    db.record_result(ApplyResult(job=vaga, status=ApplyStatus.FILLED, message="aguardando"))
    db.record_result(ApplyResult(job=vaga, status=ApplyStatus.SUBMITTED, message="enviada"))
    rows = db.list_applications()
    assert len(rows) == 1 and rows[0].status == "submitted"


def test_fingerprint_diferencia_vagas(tmp_path):
    assert job(external_id="1").fingerprint != job(external_id="2").fingerprint


def test_stats_por_status(tmp_path):
    db = store(tmp_path)
    db.record_discovery(job(external_id="a"))
    db.record_result(ApplyResult(job=job(external_id="b"), status=ApplyStatus.SUBMITTED))
    assert db.stats_by_status() == {"discovered": 1, "submitted": 1}
