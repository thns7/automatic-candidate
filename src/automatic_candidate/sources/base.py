"""Contrato das fontes de descoberta de vagas."""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Any

from automatic_candidate.config import CompanyConfig
from automatic_candidate.httpclient import HttpClient
from automatic_candidate.models import JobPosting

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")


class JobSource(ABC):
    """Uma fonte sabe listar as vagas publicas de uma empresa."""

    #: nome usado no campo source/type do companies.yaml
    name: str = "base"
    #: endpoint humano, mostrado por `candidate sources verify`
    docs: str = ""

    def __init__(self, company: CompanyConfig, http: HttpClient) -> None:
        self.company = company
        self.http = http
        self.config: dict[str, Any] = company.source

    @abstractmethod
    def fetch(self, limit: int = 200) -> list[JobPosting]:
        """Retorna as vagas publicadas. Deve levantar HttpError em falha."""

    # ------------------------------------------------------------- utilidades
    def option(self, key: str, default: Any = "") -> Any:
        value = self.config.get(key, default)
        return default if value is None else value

    @property
    def board(self) -> str:
        board = str(self.option("board") or self.option("tenant") or "").strip()
        if not board:
            raise ValueError(
                f"empresa '{self.company.key}': falta 'board' em source (config/companies.yaml)"
            )
        return board

    def make_job(self, **kwargs: Any) -> JobPosting:
        kwargs.setdefault("company_key", self.company.key)
        kwargs.setdefault("company_name", self.company.name)
        kwargs.setdefault("source", self.name)
        return JobPosting(**kwargs)

    def describe(self) -> str:
        return f"{self.company.name} via {self.name}"


def strip_html(text: Any, max_chars: int = 4000) -> str:
    """Descricoes vem em HTML na maioria dos portais."""
    if not text:
        return ""
    plain = _TAG_RE.sub(" ", str(text))
    plain = (
        plain.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    plain = re.sub(r"\s+", " ", plain).strip()
    return plain[:max_chars]


def parse_date(value: Any) -> date | None:
    """Aceita os formatos de data que os portais usam (ISO, epoch, 'Posted 3 Days Ago')."""
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds > 1e11:  # milissegundos
            seconds /= 1000.0
        try:
            return datetime.fromtimestamp(seconds).date()
        except (OverflowError, OSError, ValueError):
            return None

    text = str(value).strip()
    relative = re.search(r"(\d+)\+?\s*(day|days|dia|dias)", text, re.IGNORECASE)
    if relative:
        from datetime import timedelta

        return date.today() - timedelta(days=int(relative.group(1)))
    if re.search(r"\b(today|hoje)\b", text, re.IGNORECASE):
        return date.today()
    if re.search(r"(30\+|today)", text, re.IGNORECASE):
        return None

    cleaned = text.replace("Z", "+00:00")
    for parser in (
        lambda s: datetime.fromisoformat(s).date(),
        lambda s: datetime.strptime(s[:10], "%Y-%m-%d").date(),
        lambda s: datetime.strptime(s, "%d/%m/%Y").date(),
        lambda s: datetime.strptime(s, "%m/%d/%Y").date(),
    ):
        try:
            return parser(cleaned)
        except (ValueError, TypeError):
            continue
    logger.debug("data nao reconhecida: %r", value)
    return None
