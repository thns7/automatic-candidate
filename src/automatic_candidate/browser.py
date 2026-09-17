"""Sessao de navegador (Playwright).

Usa um contexto persistente: os cookies de login dos portais (Workday, Gupy,
Microsoft, Google) ficam em browser-profile/, entao voce loga uma vez por
portal e as execucoes seguintes ja entram autenticadas. E o unico jeito
sensato de lidar com 2FA e captcha sem tentar burlar nada.

Playwright e opcional: 'candidate discover' funciona sem ele. Instale so
quando for preencher formularios:
    pip install "automatic-candidate[browser]"
    python -m playwright install chromium
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from automatic_candidate.config import BrowserSettings

if TYPE_CHECKING:  # pragma: no cover
    from playwright.sync_api import BrowserContext, Page

logger = logging.getLogger(__name__)

PLAYWRIGHT_HINT = (
    "Playwright nao esta instalado. Para preencher formularios rode:\n"
    '    pip install "automatic-candidate[browser]"\n'
    "    python -m playwright install chromium"
)


class BrowserUnavailableError(RuntimeError):
    pass


def playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return False
    return True


class BrowserSession:
    """Contexto persistente do Chromium, com screenshots datados."""

    def __init__(self, settings: BrowserSettings) -> None:
        self.settings = settings
        self._playwright: Any = None
        self._context: BrowserContext | None = None

    # ------------------------------------------------------------- ciclo vida
    def start(self) -> BrowserContext:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - depende do ambiente
            raise BrowserUnavailableError(PLAYWRIGHT_HINT) from exc

        user_data_dir = Path(self.settings.user_data_dir).resolve()
        user_data_dir.mkdir(parents=True, exist_ok=True)
        Path(self.settings.screenshot_dir).mkdir(parents=True, exist_ok=True)

        launch_kwargs: dict[str, Any] = {}
        if self.settings.executable_path:
            launch_kwargs["executable_path"] = self.settings.executable_path

        self._playwright = sync_playwright().start()
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            headless=self.settings.headless,
            slow_mo=self.settings.slow_mo_ms,
            locale=self.settings.locale,
            viewport=self.settings.viewport,
            args=["--disable-blink-features=AutomationControlled"],
            **launch_kwargs,
        )
        self._context.set_default_timeout(self.settings.timeout_ms)
        logger.debug("navegador iniciado (perfil: %s)", user_data_dir)
        return self._context

    def close(self) -> None:
        if self._context is not None:
            try:
                self._context.close()
            finally:
                self._context = None
        if self._playwright is not None:
            try:
                self._playwright.stop()
            finally:
                self._playwright = None

    def __enter__(self) -> BrowserSession:
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ---------------------------------------------------------------- paginas
    @property
    def context(self) -> BrowserContext:
        if self._context is None:
            raise BrowserUnavailableError("sessao de navegador nao iniciada (chame start())")
        return self._context

    @contextmanager
    def page(self, url: str | None = None) -> Iterator[Page]:
        page = self.context.new_page()
        try:
            if url:
                page.goto(url, wait_until="domcontentloaded")
            yield page
        finally:
            if not page.is_closed():
                page.close()

    def screenshot(self, page: Page, tag: str) -> str:
        """Salva um PNG da pagina inteira e devolve o caminho."""
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_tag = re.sub(r"[^a-zA-Z0-9_-]+", "-", tag).strip("-")[:60] or "page"
        path = Path(self.settings.screenshot_dir) / f"{stamp}-{safe_tag}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            page.screenshot(path=str(path), full_page=True)
        except Exception as exc:  # noqa: BLE001 - screenshot nunca derruba o fluxo
            logger.warning("nao foi possivel tirar screenshot: %s", exc)
            return ""
        return str(path)
