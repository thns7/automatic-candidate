"""Carregamento e validacao dos arquivos de configuracao do usuario.

Os tres arquivos que o usuario edita:
    config/profile.yaml    -> dados pessoais, documentos, respostas de triagem
    config/settings.yaml   -> comportamento da automacao (filtros, limites, modo)
    config/companies.yaml  -> empresas alvo e portais
E o .env, para segredos referenciados como ${VAR} dentro dos YAMLs.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from automatic_candidate.models import SubmitMode

CONFIG_DIR = Path("config")
PROFILE_FILE = CONFIG_DIR / "profile.yaml"
SETTINGS_FILE = CONFIG_DIR / "settings.yaml"
COMPANIES_FILE = CONFIG_DIR / "companies.yaml"
ENV_FILE = Path(".env")

_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")

logger = logging.getLogger(__name__)


class ConfigError(RuntimeError):
    """Erro de configuracao com mensagem acionavel para o usuario."""


# --------------------------------------------------------------------------- #
# .env
# --------------------------------------------------------------------------- #
def load_dotenv(path: Path = ENV_FILE) -> dict[str, str]:
    """Le um .env simples (KEY=VALUE) para os.environ sem sobrescrever."""
    loaded: dict[str, str] = {}
    if not path.exists():
        return loaded
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        loaded[key] = value
        os.environ.setdefault(key, value)
    return loaded


def expand_env(value: Any) -> Any:
    """Substitui ${VAR} recursivamente em strings, listas e dicts."""
    if isinstance(value, str):
        def _sub(match: re.Match[str]) -> str:
            return os.environ.get(match.group(1), match.group(0))

        return _ENV_PATTERN.sub(_sub, value)
    if isinstance(value, dict):
        return {k: expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_env(v) for v in value]
    return value


def _read_yaml(path: Path, example_hint: str) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(
            f"Arquivo de configuracao nao encontrado: {path}\n"
            f"  Crie com:  cp {example_hint} {path}\n"
            f"  e edite com as suas informacoes (veja o README)."
        )
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML invalido em {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path} deveria conter um mapeamento no topo.")
    return expand_env(data)


# --------------------------------------------------------------------------- #
# Profile
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class Profile:
    """Dados pessoais do candidato (config/profile.yaml)."""

    data: dict[str, Any]
    path: Path = PROFILE_FILE

    # --- atalhos de leitura ------------------------------------------------ #
    def get(self, dotted: str, default: Any = "") -> Any:
        """Leitura por caminho pontilhado.

        Aceita indice numerico em lista: 'education.0.school' pega a formacao
        mais recente, que e o que os formularios de estagio perguntam.
        """
        node: Any = self.data
        for part in dotted.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
                node = node[int(part)]
            else:
                return default
        return node if node is not None else default

    @property
    def personal(self) -> dict[str, Any]:
        return self.data.get("personal", {}) or {}

    @property
    def location(self) -> dict[str, Any]:
        return self.data.get("location", {}) or {}

    @property
    def links(self) -> dict[str, Any]:
        return self.data.get("links", {}) or {}

    @property
    def professional(self) -> dict[str, Any]:
        return self.data.get("professional", {}) or {}

    @property
    def screening_answers(self) -> list[dict[str, Any]]:
        return self.data.get("screening_answers", []) or []

    @property
    def consents(self) -> dict[str, Any]:
        return self.data.get("consents", {}) or {}

    @property
    def full_name(self) -> str:
        name = self.personal.get("full_name")
        if name:
            return str(name)
        first = self.personal.get("first_name", "")
        last = self.personal.get("last_name", "")
        return f"{first} {last}".strip()

    def resume_path(self, variant: str = "default") -> Path | None:
        resumes = self.get("documents.resumes", {}) or {}
        raw = resumes.get(variant) or resumes.get("default")
        return Path(str(raw)) if raw else None

    def validate(self) -> list[str]:
        """Retorna a lista de problemas encontrados (vazia = tudo certo)."""
        problems: list[str] = []
        required = {
            "personal.first_name": "seu nome",
            "personal.last_name": "seu sobrenome",
            "personal.email": "seu e-mail",
            "personal.phone": "seu telefone",
        }
        for dotted, label in required.items():
            if not str(self.get(dotted)).strip():
                problems.append(f"{self.path}: preencha '{dotted}' ({label})")

        email = str(self.get("personal.email"))
        if email and ("@" not in email or email.startswith("seu.email@")):
            problems.append(
                f"{self.path}: 'personal.email' ainda esta com o valor de exemplo"
            )

        resume = self.resume_path()
        if resume is None:
            problems.append(
                f"{self.path}: defina 'documents.resumes.default' apontando para o PDF "
                "do seu curriculo (ex: data/resumes/curriculo.pdf)"
            )
        elif not resume.exists():
            problems.append(
                f"curriculo nao encontrado em '{resume}' — coloque o PDF nesse caminho"
            )
        return problems


def load_profile(path: Path = PROFILE_FILE) -> Profile:
    return Profile(_read_yaml(path, "config/profile.example.yaml"), path)


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class Filters:
    title_include: list[str] = field(default_factory=list)
    title_exclude: list[str] = field(default_factory=list)
    locations_include: list[str] = field(default_factory=list)
    locations_exclude: list[str] = field(default_factory=list)
    keywords_boost: dict[str, int] = field(default_factory=dict)
    min_score: int = 0
    posted_within_days: int = 0

    def merged_with(self, overrides: dict[str, Any]) -> Filters:
        """Aplica os overrides de um perfil de cargo, campo a campo.

        Cada chave presente SUBSTITUI a do filtro base (nao soma): um perfil de
        estagio precisa poder remover 'estagi' do title_exclude herdado.
        """
        if not overrides:
            return self
        known = {f for f in Filters.__slots__}
        unknown = set(overrides) - known
        if unknown:
            logger.warning(
                "filtros desconhecidos no perfil de cargo, ignorados: %s", ", ".join(sorted(unknown))
            )
        changes: dict[str, Any] = {}
        for key in ("title_include", "title_exclude", "locations_include", "locations_exclude"):
            if key in overrides:
                changes[key] = [str(v).lower() for v in (overrides[key] or [])]
        if "keywords_boost" in overrides:
            changes["keywords_boost"] = {
                str(k).lower(): int(v) for k, v in (overrides["keywords_boost"] or {}).items()
            }
        for key in ("min_score", "posted_within_days"):
            if key in overrides:
                changes[key] = int(overrides[key])
        return replace(self, **changes)


@dataclass(slots=True)
class RoleProfile:
    """Um cargo alvo com janela de validade.

    Serve para a busca mudar sozinha com o tempo: estagio agora, junior a
    partir de 2027. O perfil ativo e o primeiro cuja janela cobre a data de
    hoje (ou o escolhido a mao em active_role / --role).
    """

    name: str
    description: str = ""
    valid_from: date | None = None
    valid_until: date | None = None
    filters: dict[str, Any] = field(default_factory=dict)
    resume: str = ""
    screening_answers: list[dict[str, Any]] = field(default_factory=list)

    def is_active_on(self, today: date) -> bool:
        if self.valid_from and today < self.valid_from:
            return False
        if self.valid_until and today > self.valid_until:
            return False
        return True

    def window_label(self) -> str:
        inicio = self.valid_from.isoformat() if self.valid_from else "sempre"
        fim = self.valid_until.isoformat() if self.valid_until else "sem prazo"
        return f"{inicio} ate {fim}"


@dataclass(slots=True)
class Limits:
    max_applications_per_run: int = 5
    max_applications_per_day: int = 15
    max_per_company_per_day: int = 5
    min_seconds_between_applications: int = 45
    max_seconds_between_applications: int = 120


@dataclass(slots=True)
class BrowserSettings:
    headless: bool = False
    slow_mo_ms: int = 120
    timeout_ms: int = 45000
    user_data_dir: Path = Path("browser-profile")
    screenshot_dir: Path = Path("data/screenshots")
    locale: str = "pt-BR"
    viewport: dict[str, int] = field(default_factory=lambda: {"width": 1440, "height": 900})
    #: caminho para um Chromium/Chrome proprio; vazio = o que o Playwright baixou
    executable_path: str = ""


@dataclass(slots=True)
class Settings:
    submit_mode: SubmitMode = SubmitMode.DRY_RUN
    limits: Limits = field(default_factory=Limits)
    browser: BrowserSettings = field(default_factory=BrowserSettings)
    filters: Filters = field(default_factory=Filters)
    roles: list[RoleProfile] = field(default_factory=list)
    active_role: str = "auto"
    database: Path = Path("data/applications.sqlite3")
    reports_dir: Path = Path("data/reports")
    cover_letter_enabled: bool = True
    cover_letter_when_optional: bool = False
    log_level: str = "INFO"
    log_file: Path | None = Path("data/automatic-candidate.log")
    path: Path = SETTINGS_FILE

    # ------------------------------------------------------------ cargo alvo
    def resolve_role(
        self, today: date | None = None, override: str | None = None
    ) -> RoleProfile | None:
        """Perfil de cargo em vigor: --role > active_role > janela de datas."""
        if not self.roles:
            return None
        chosen = (override or "").strip() or (
            self.active_role if self.active_role not in ("", "auto") else ""
        )
        if chosen:
            for role in self.roles:
                if role.name == chosen:
                    return role
            known = ", ".join(r.name for r in self.roles)
            raise ConfigError(f"cargo desconhecido: {chosen!r}. Disponiveis: {known}")

        today = today or date.today()
        for role in self.roles:
            if role.is_active_on(today):
                return role
        return None

    def effective_filters(self, role: RoleProfile | None) -> Filters:
        return self.filters.merged_with(role.filters) if role else self.filters

    def next_role_after(self, today: date | None = None) -> RoleProfile | None:
        """Proximo cargo a entrar em vigor — usado para avisar sobre a troca."""
        today = today or date.today()
        futuros = [
            role for role in self.roles if role.valid_from and role.valid_from > today
        ]
        return min(futuros, key=lambda r: r.valid_from or date.max) if futuros else None


def _parse_date(value: Any, field_name: str, role_name: str) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise ConfigError(
            f"cargo {role_name!r}: '{field_name}' precisa estar no formato AAAA-MM-DD "
            f"(recebi {value!r})"
        ) from exc


def _parse_roles(raw: Any) -> list[RoleProfile]:
    if not raw:
        return []
    if not isinstance(raw, list):
        raise ConfigError("config/settings.yaml: 'roles' deve ser uma lista de cargos.")

    roles: list[RoleProfile] = []
    seen: set[str] = set()
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ConfigError(f"config/settings.yaml: cargo #{index} deveria ser um mapeamento.")
        name = str(item.get("name") or "").strip()
        if not name:
            raise ConfigError(f"config/settings.yaml: cargo #{index} esta sem 'name'.")
        if name in seen:
            raise ConfigError(f"config/settings.yaml: cargo duplicado: {name!r}")
        seen.add(name)

        valid_from = _parse_date(item.get("valid_from"), "valid_from", name)
        valid_until = _parse_date(item.get("valid_until"), "valid_until", name)
        if valid_from and valid_until and valid_from > valid_until:
            raise ConfigError(
                f"cargo {name!r}: 'valid_from' ({valid_from}) e depois de 'valid_until' ({valid_until})"
            )
        roles.append(
            RoleProfile(
                name=name,
                description=str(item.get("description") or ""),
                valid_from=valid_from,
                valid_until=valid_until,
                filters=dict(item.get("filters") or {}),
                resume=str(item.get("resume") or ""),
                screening_answers=list(item.get("screening_answers") or []),
            )
        )
    return roles


def load_settings(path: Path = SETTINGS_FILE) -> Settings:
    data = _read_yaml(path, "config/settings.example.yaml")
    limits_raw = data.get("limits", {}) or {}
    browser_raw = data.get("browser", {}) or {}
    filters_raw = data.get("filters", {}) or {}
    storage_raw = data.get("storage", {}) or {}
    cover_raw = data.get("cover_letter", {}) or {}
    log_raw = data.get("logging", {}) or {}

    def _lower_list(key: str) -> list[str]:
        return [str(v).lower() for v in (filters_raw.get(key) or [])]

    settings = Settings(
        submit_mode=SubmitMode.parse(data.get("submit_mode", "dry_run")),
        limits=Limits(
            **{k: int(v) for k, v in limits_raw.items() if k in Limits.__slots__}
        ),
        browser=BrowserSettings(
            headless=bool(browser_raw.get("headless", False)),
            slow_mo_ms=int(browser_raw.get("slow_mo_ms", 120)),
            timeout_ms=int(browser_raw.get("timeout_ms", 45000)),
            user_data_dir=Path(str(browser_raw.get("user_data_dir", "browser-profile"))),
            screenshot_dir=Path(str(browser_raw.get("screenshot_dir", "data/screenshots"))),
            locale=str(browser_raw.get("locale", "pt-BR")),
            viewport=dict(browser_raw.get("viewport") or {"width": 1440, "height": 900}),
            executable_path=str(
                browser_raw.get("executable_path")
                or os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE", "")
            ),
        ),
        filters=Filters(
            title_include=_lower_list("title_include"),
            title_exclude=_lower_list("title_exclude"),
            locations_include=_lower_list("locations_include"),
            locations_exclude=_lower_list("locations_exclude"),
            keywords_boost={
                str(k).lower(): int(v) for k, v in (filters_raw.get("keywords_boost") or {}).items()
            },
            min_score=int(filters_raw.get("min_score", 0)),
            posted_within_days=int(filters_raw.get("posted_within_days", 0)),
        ),
        roles=_parse_roles(data.get("roles")),
        active_role=str(data.get("active_role", "auto") or "auto"),
        database=Path(str(storage_raw.get("database", "data/applications.sqlite3"))),
        reports_dir=Path(str(storage_raw.get("reports_dir", "data/reports"))),
        cover_letter_enabled=bool(cover_raw.get("enabled", True)),
        cover_letter_when_optional=bool(cover_raw.get("attach_when_optional", False)),
        log_level=str(log_raw.get("level", "INFO")).upper(),
        log_file=Path(str(log_raw["file"])) if log_raw.get("file") else None,
        path=path,
    )
    return settings


# --------------------------------------------------------------------------- #
# Companies
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class CompanyConfig:
    key: str
    name: str
    enabled: bool = True
    tags: list[str] = field(default_factory=list)
    source: dict[str, Any] = field(default_factory=dict)
    apply: dict[str, Any] = field(default_factory=dict)
    resume: str = "default"

    @property
    def source_type(self) -> str:
        return str(self.source.get("type", "")).lower()

    @property
    def applier(self) -> str:
        return str(self.apply.get("applier", "generic")).lower()

    @property
    def allow_auto_submit(self) -> bool:
        return bool(self.apply.get("allow_auto_submit", False))

    @property
    def login_env_prefix(self) -> str:
        return str(self.apply.get("login_env_prefix", "")).upper()

    def credentials(self) -> tuple[str, str]:
        """(email, senha) lidos do ambiente a partir do login_env_prefix."""
        prefix = self.login_env_prefix
        if not prefix:
            return "", ""
        email = os.environ.get(f"{prefix}_EMAIL", "") or os.environ.get(f"{prefix}_USER", "")
        password = os.environ.get(f"{prefix}_PASSWORD", "")
        return email, password


def load_companies(path: Path = COMPANIES_FILE) -> list[CompanyConfig]:
    data = _read_yaml(path, "config/companies.example.yaml")
    raw_companies = data.get("companies") or []
    if not isinstance(raw_companies, list):
        raise ConfigError(f"{path}: 'companies' deve ser uma lista.")

    companies: list[CompanyConfig] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_companies, start=1):
        if not isinstance(item, dict):
            raise ConfigError(f"{path}: empresa #{index} deveria ser um mapeamento.")
        key = str(item.get("key") or "").strip()
        if not key:
            raise ConfigError(f"{path}: empresa #{index} esta sem 'key'.")
        if key in seen:
            raise ConfigError(f"{path}: 'key' duplicada: {key!r}")
        seen.add(key)
        companies.append(
            CompanyConfig(
                key=key,
                name=str(item.get("name") or key),
                enabled=bool(item.get("enabled", True)),
                tags=[str(t) for t in (item.get("tags") or [])],
                source=dict(item.get("source") or {}),
                apply=dict(item.get("apply") or {}),
                resume=str(item.get("resume") or "default"),
            )
        )
    return companies


# --------------------------------------------------------------------------- #
# Bundle
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class AppConfig:
    profile: Profile
    settings: Settings
    companies: list[CompanyConfig]

    def company(self, key: str) -> CompanyConfig:
        for company in self.companies:
            if company.key == key:
                return company
        known = ", ".join(c.key for c in self.companies) or "(nenhuma)"
        raise ConfigError(f"Empresa desconhecida: {key!r}. Disponiveis: {known}")

    def enabled_companies(self, keys: list[str] | None = None) -> list[CompanyConfig]:
        if keys:
            return [self.company(k) for k in keys]
        return [c for c in self.companies if c.enabled]


def load_config(config_dir: Path = CONFIG_DIR) -> AppConfig:
    load_dotenv()
    return AppConfig(
        profile=load_profile(config_dir / "profile.yaml"),
        settings=load_settings(config_dir / "settings.yaml"),
        companies=load_companies(config_dir / "companies.yaml"),
    )
