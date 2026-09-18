"""Cliente HTTP compartilhado pelas fontes de vagas.

Politica de uso: uma sessao reaproveitada, retry com backoff em erros
transitorios, intervalo minimo entre requisicoes ao mesmo host e um
User-Agent honesto. Nada de forcar portais que respondem 403.
"""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

USER_AGENT = (
    "automatic-candidate/0.1 (+https://github.com/thns7/automatic-candidate)"
)
RETRY_STATUS = {429, 500, 502, 503, 504}


class HttpError(RuntimeError):
    """Falha de rede/HTTP apos os retries."""


class HttpClient:
    def __init__(
        self,
        timeout: int = 25,
        max_retries: int = 3,
        min_interval: float = 1.0,
        user_agent: str = USER_AGENT,
    ) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self.min_interval = min_interval
        self._last_call: dict[str, float] = {}
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            }
        )

    # ------------------------------------------------------------------ core
    def _throttle(self, url: str) -> None:
        host = urlparse(url).netloc
        last = self._last_call.get(host)
        if last is not None:
            elapsed = time.monotonic() - last
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
        self._last_call[host] = time.monotonic()

    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            self._throttle(url)
            try:
                response = self.session.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers=headers,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                last_error = exc
                logger.debug("tentativa %s/%s falhou em %s: %s", attempt, self.max_retries, url, exc)
            else:
                if response.status_code in RETRY_STATUS and attempt < self.max_retries:
                    wait = 2 ** attempt
                    logger.debug(
                        "HTTP %s em %s; nova tentativa em %ss", response.status_code, url, wait
                    )
                    time.sleep(wait)
                    continue
                return response
            if attempt < self.max_retries:
                time.sleep(2 ** attempt)
        raise HttpError(f"nao foi possivel acessar {url}: {last_error}")

    # ---------------------------------------------------------------- helpers
    def get_json(self, url: str, **kwargs: Any) -> Any:
        response = self.request("GET", url, **kwargs)
        return _as_json(response, url)

    def post_json(self, url: str, json_body: dict[str, Any], **kwargs: Any) -> Any:
        response = self.request("POST", url, json_body=json_body, **kwargs)
        return _as_json(response, url)


def _as_json(response: requests.Response, url: str) -> Any:
    if response.status_code >= 400:
        raise HttpError(
            f"HTTP {response.status_code} em {url}. "
            "O slug/tenant pode ter mudado — rode 'candidate sources verify'."
        )
    try:
        return response.json()
    except ValueError as exc:
        snippet = response.text[:160].replace("\n", " ")
        raise HttpError(f"resposta nao-JSON de {url}: {snippet!r}") from exc


def pluck(data: Any, *paths: str, default: Any = "") -> Any:
    """Le o primeiro caminho existente em um dict aninhado.

    Portais mudam nomes de campo entre versoes; em vez de quebrar, tentamos
    varias grafias:  pluck(job, "location.name", "locationsText", "city")
    """
    for path in paths:
        node: Any = data
        found = True
        for part in path.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
                node = node[int(part)]
            else:
                found = False
                break
        if found and node not in (None, "", [], {}):
            return node
    return default
