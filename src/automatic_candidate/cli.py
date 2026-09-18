"""Interface de linha de comando.

Fluxo tipico:
    candidate init                 # cria seus arquivos de configuracao
    candidate doctor               # confere se esta tudo preenchido
    candidate discover             # lista as vagas que passam nos filtros
    candidate apply --limit 3      # preenche e pede confirmacao antes de enviar
    candidate status               # o que ja foi enviado
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import webbrowser
from pathlib import Path

from automatic_candidate import __version__
from automatic_candidate.config import (
    CONFIG_DIR,
    AppConfig,
    ConfigError,
    load_config,
    load_dotenv,
)
from automatic_candidate.logging_setup import setup_logging
from automatic_candidate.models import SubmitMode

logger = logging.getLogger("candidate")

INIT_FILES = [
    ("config/profile.example.yaml", "config/profile.yaml", "seus dados pessoais"),
    ("config/settings.example.yaml", "config/settings.yaml", "comportamento da automacao"),
    ("config/companies.example.yaml", "config/companies.yaml", "empresas alvo"),
    (".env.example", ".env", "senhas e dados sensiveis"),
]


# --------------------------------------------------------------------------- #
# comandos
# --------------------------------------------------------------------------- #
def cmd_init(args: argparse.Namespace) -> int:
    print("Criando seus arquivos de configuracao...\n")
    created = 0
    for source, target, description in INIT_FILES:
        src, dst = Path(source), Path(target)
        if not src.exists():
            print(f"  ! modelo ausente: {src}")
            continue
        if dst.exists() and not args.force:
            print(f"  = {dst} ja existe (use --force para sobrescrever)")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        created += 1
        print(f"  + {dst}  ({description})")

    for directory in ("data/resumes", "data/screenshots", "data/reports"):
        Path(directory).mkdir(parents=True, exist_ok=True)

    print(
        f"\n{created} arquivo(s) criados.\n"
        "\nPROXIMOS PASSOS — e aqui que voce coloca as SUAS informacoes:\n"
        "  1. config/profile.yaml   -> nome, e-mail, telefone, links, experiencia,\n"
        "                              respostas de triagem (screening_answers)\n"
        "  2. .env                  -> CPF e senhas dos portais (nunca vai pro git)\n"
        "  3. data/resumes/         -> coloque seu curriculo em PDF aqui e aponte\n"
        "                              o caminho em documents.resumes.default\n"
        "  4. config/companies.yaml -> empresas que voce quer acompanhar\n"
        "  5. config/settings.yaml  -> filtros de vaga e modo de envio\n"
        "\nDepois rode:  candidate doctor"
    )
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    from automatic_candidate.browser import playwright_available

    print("Verificando a instalacao...\n")
    problems: list[str] = []

    missing_files = [target for _, target, _ in INIT_FILES if not Path(target).exists()]
    if missing_files:
        for target in missing_files:
            print(f"  [falta] {target}")
        print("\n  -> rode 'candidate init' para criar os arquivos que faltam.")
        return 1

    try:
        config = load_config()
    except ConfigError as exc:
        print(f"  [erro] {exc}")
        return 1

    print("  [ok] config/profile.yaml, settings.yaml e companies.yaml carregados")
    problems.extend(config.profile.validate())

    enabled = config.enabled_companies()
    print(f"  [ok] {len(enabled)} empresa(s) habilitada(s): {', '.join(c.key for c in enabled)}")

    mode = config.settings.submit_mode
    print(f"  [ok] submit_mode: {mode.value}")
    if mode is SubmitMode.AUTO:
        auto_companies = [c.key for c in enabled if c.allow_auto_submit]
        print(
            f"       envio automatico liberado em: {', '.join(auto_companies) or '(nenhuma empresa)'}"
        )

    if playwright_available():
        print("  [ok] Playwright instalado (preenchimento de formulario disponivel)")
    else:
        print(
            "  [aviso] Playwright ausente — 'discover' funciona, 'apply' nao.\n"
            '          pip install "automatic-candidate[browser]" '
            "&& python -m playwright install chromium"
        )

    env = load_dotenv()
    configured = [k for k, v in env.items() if v and not v.startswith(("sua-", "seu."))]
    print(f"  [ok] .env carregado ({len(configured)} variavel(is) preenchida(s))")

    if problems:
        print("\nPendencias:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print("\nTudo certo. Proximo passo:  candidate discover")
    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    from automatic_candidate.pipeline import discover
    from automatic_candidate.reporting import print_discovery
    from automatic_candidate.storage import ApplicationStore

    config = _load(args)
    role = config.settings.resolve_role(override=getattr(args, "role", None))
    _announce_role(config, role)
    store = ApplicationStore(config.settings.database)
    report = discover(
        config,
        company_keys=args.company or None,
        per_company_limit=args.per_company,
        store=store,
        role=role,
    )
    print_discovery(report, show_rejected=args.show_rejected)

    if args.json:
        payload = [
            {
                "empresa": job.company_name,
                "titulo": job.title,
                "local": job.location,
                "score": job.score,
                "url": job.target_url,
                "publicada_em": job.posted_at.isoformat() if job.posted_at else None,
            }
            for job in report.jobs
        ]
        Path(args.json).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nJSON salvo em {args.json}")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    from automatic_candidate.browser import playwright_available
    from automatic_candidate.pipeline import discover, run_applications
    from automatic_candidate.reporting import print_discovery, print_run
    from automatic_candidate.storage import ApplicationStore

    config = _load(args)
    if args.mode:
        config.settings.submit_mode = SubmitMode.parse(args.mode)

    if config.settings.submit_mode is not SubmitMode.DRY_RUN and not playwright_available():
        print(
            "Playwright nao esta instalado — sem ele nao da para preencher formularios.\n"
            '  pip install "automatic-candidate[browser]"\n'
            "  python -m playwright install chromium"
        )
        return 1

    problems = config.profile.validate()
    if problems and not args.force:
        print("Corrija o perfil antes de se candidatar:")
        for problem in problems:
            print(f"  - {problem}")
        print("\n(use --force para ignorar, por sua conta e risco)")
        return 1

    role = config.settings.resolve_role(override=getattr(args, "role", None))
    _announce_role(config, role)
    store = ApplicationStore(config.settings.database)
    report = discover(
        config,
        company_keys=args.company or None,
        per_company_limit=args.per_company,
        store=store,
        role=role,
    )
    print_discovery(report)
    if not report.jobs:
        return 0

    if config.settings.submit_mode is SubmitMode.AUTO:
        auto_ok = [c.key for c in config.enabled_companies() if c.allow_auto_submit]
        print(
            "\n*** MODO AUTO: as candidaturas serao ENVIADAS sem confirmacao em: "
            f"{', '.join(auto_ok) or '(nenhuma empresa liberou allow_auto_submit)'} ***"
        )
        if not args.yes and input("Confirma? [s/N] ").strip().lower() not in {"s", "sim", "y"}:
            print("cancelado.")
            return 0

    run = run_applications(
        config, report.jobs, store, limit=args.limit, force=args.force, role=role
    )
    print_run(run)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    from automatic_candidate.reporting import print_status
    from automatic_candidate.storage import ApplicationStore

    config = _load(args)
    print_status(ApplicationStore(config.settings.database), limit=args.limit)
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    from automatic_candidate.reporting import export
    from automatic_candidate.storage import ApplicationStore

    config = _load(args)
    path = export(ApplicationStore(config.settings.database), config.settings.reports_dir, args.format)
    print(f"relatorio salvo em {path}")
    return 0


def cmd_sources(args: argparse.Namespace) -> int:
    from automatic_candidate.httpclient import HttpClient
    from automatic_candidate.sources import build_source

    config = _load(args)
    http = HttpClient()
    companies = config.enabled_companies(args.company or None)

    if args.action == "list":
        print(f"{'chave':<16}{'empresa':<24}{'fonte':<18}endpoint")
        print("-" * 100)
        for company in companies:
            try:
                source = build_source(company, http)
                endpoint_fn = getattr(source, "endpoint", None)
                endpoint = endpoint_fn() if callable(endpoint_fn) else source.docs
            except Exception as exc:  # noqa: BLE001
                endpoint = f"(erro: {exc})"
            print(f"{company.key:<16}{company.name:<24}{company.source_type:<18}{endpoint}")
        return 0

    if args.action == "verify":
        failures = 0
        for company in companies:
            try:
                source = build_source(company, http)
                jobs = source.fetch(limit=5)
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"  [FALHA] {company.key:<14} {exc}")
                continue
            example = jobs[0].title if jobs else "(nenhuma vaga publicada)"
            print(f"  [ok]    {company.key:<14} {len(jobs)} vaga(s) — ex: {example}")
        if failures:
            print(
                f"\n{failures} portal(is) com problema. Ajuste 'source' em config/companies.yaml "
                "(slug/tenant/site mudam com o tempo) e rode de novo."
            )
        return 1 if failures else 0

    # raw
    company = config.company(args.company[0]) if args.company else companies[0]
    source = build_source(company, http)
    jobs = source.fetch(limit=args.per_company)
    payload = [job.raw for job in jobs[:3]]
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str)[:8000])
    return 0


def cmd_open(args: argparse.Namespace) -> int:
    """Abre o portal da empresa no navegador (util para o primeiro login)."""
    config = _load(args)
    company = config.company(args.company_key)
    urls = [str(u) for u in (company.source.get("search_urls") or [])]
    if not urls:
        source_type = company.source_type
        board = company.source.get("board") or company.source.get("tenant", "")
        guesses = {
            "gupy": f"https://{board}.gupy.io",
            "greenhouse": f"https://boards.greenhouse.io/{board}",
            "lever": f"https://jobs.lever.co/{board}",
            "ashby": f"https://jobs.ashbyhq.com/{board}",
            "smartrecruiters": f"https://jobs.smartrecruiters.com/{board}",
            "microsoft": "https://jobs.careers.microsoft.com/global/en/search",
            "workday": f"https://{company.source.get('host', '')}/{company.source.get('site', '')}",
        }
        urls = [guesses.get(source_type, "")]
    urls = [u for u in urls if u]
    if not urls:
        print(f"nao sei qual URL abrir para '{company.key}'. Defina source.search_urls.")
        return 1

    if args.browser_profile:
        from automatic_candidate.browser import BrowserSession

        with BrowserSession(config.settings.browser) as session:
            page = session.context.new_page()
            page.goto(urls[0], wait_until="domcontentloaded")
            print(
                f"Portal aberto: {urls[0]}\n"
                "Faca login. A sessao fica salva no perfil do navegador "
                f"({config.settings.browser.user_data_dir}) e sera reaproveitada."
            )
            input("Pressione ENTER quando terminar... ")
        return 0

    for url in urls:
        print(f"abrindo {url}")
        webbrowser.open(url)
    return 0


def cmd_answers(args: argparse.Namespace) -> int:
    """Testa como uma pergunta de formulario seria respondida."""
    from automatic_candidate.answers import AnswerBook, FormField

    config = _load(args)
    role = config.settings.resolve_role(override=getattr(args, "role", None))
    book = AnswerBook(config.profile, extra_answers=role.screening_answers if role else None)
    if role is not None:
        print(f"(cargo ativo: {role.name})")
    for question in args.question:
        field = FormField(label=question, kind=args.kind, options=args.option or [])
        answer = book.resolve(field)
        if answer:
            print(f"  {question!r}\n    -> {answer.value!r}  [fonte: {answer.source}]")
        else:
            print(
                f"  {question!r}\n    -> (sem resposta) — adicione uma regra em "
                "screening_answers no config/profile.yaml"
            )
    return 0


def cmd_roles(args: argparse.Namespace) -> int:
    """Mostra os cargos configurados, qual esta valendo e quando troca."""
    from datetime import date

    config = _load(args)
    settings = config.settings
    if not settings.roles:
        print(
            "Nenhum cargo configurado — a busca usa o bloco 'filters' de "
            "config/settings.yaml para tudo.\n"
            "Para mirar em estagio agora e outro cargo mais tarde, copie o bloco "
            "'roles' de config/settings.example.yaml."
        )
        return 0

    hoje = date.today()
    ativo = settings.resolve_role(hoje)
    print(f"hoje: {hoje.isoformat()}   (active_role: {settings.active_role})\n")
    for role in settings.roles:
        marca = ">>" if ativo is not None and role.name == ativo.name else "  "
        filtros = settings.effective_filters(role)
        titulos = ", ".join(filtros.title_include[:5]) or "(qualquer titulo)"
        print(f"{marca} {role.name:<10} {role.window_label():<26} {role.description}")
        print(f"      titulos: {titulos}")
        if role.resume:
            print(f"      curriculo: documents.resumes.{role.resume}")
        if role.screening_answers:
            print(f"      +{len(role.screening_answers)} resposta(s) de triagem so deste cargo")

    if ativo is None:
        print("\nNenhum cargo cobre a data de hoje — a busca cai no bloco 'filters' base.")
    proximo = settings.next_role_after(hoje)
    if proximo is not None and proximo.valid_from is not None:
        faltam = (proximo.valid_from - hoje).days
        print(
            f"\nproxima troca: {proximo.name} em {proximo.valid_from.isoformat()} "
            f"(em {faltam} dias) — automatica, voce nao precisa fazer nada."
        )
    return 0


# --------------------------------------------------------------------------- #
# infra
# --------------------------------------------------------------------------- #
def _announce_role(config: AppConfig, role) -> None:
    if role is None:
        if config.settings.roles:
            print("(nenhum cargo cobre a data de hoje; usando os filtros base)")
        return
    print(f"(cargo alvo: {role.name} — {role.description or role.window_label()})")



def _load(args: argparse.Namespace) -> AppConfig:
    config = load_config(Path(getattr(args, "config_dir", CONFIG_DIR)))
    if getattr(args, "verbose", False):
        config.settings.log_level = "DEBUG"
    setup_logging(config.settings.log_level, config.settings.log_file)
    return config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="candidate",
        description="Busca vagas nos portais de carreira e preenche as candidaturas.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--version", action="version", version=f"automatic-candidate {__version__}")
    parser.add_argument("--config-dir", default=str(CONFIG_DIR), help="pasta dos YAMLs (padrao: config)")
    parser.add_argument("-v", "--verbose", action="store_true", help="log detalhado (DEBUG)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="cria os arquivos de configuracao a partir dos modelos")
    p_init.add_argument("--force", action="store_true", help="sobrescreve arquivos existentes")
    p_init.set_defaults(func=cmd_init)

    p_doctor = sub.add_parser("doctor", help="confere configuracao, curriculo e dependencias")
    p_doctor.set_defaults(func=cmd_doctor)

    p_discover = sub.add_parser("discover", help="busca vagas e aplica os filtros (nao envia nada)")
    p_discover.add_argument("-c", "--company", action="append", help="limita a estas empresas")
    p_discover.add_argument("--per-company", type=int, default=200, help="maximo de vagas por empresa")
    p_discover.add_argument("--show-rejected", type=int, default=0, help="mostra N vagas descartadas")
    p_discover.add_argument("--json", help="salva o resultado neste arquivo JSON")
    p_discover.add_argument("--role", help="forca um cargo de config/settings.yaml (ex: junior)")
    p_discover.set_defaults(func=cmd_discover)

    p_apply = sub.add_parser("apply", help="preenche (e opcionalmente envia) as candidaturas")
    p_apply.add_argument("-c", "--company", action="append", help="limita a estas empresas")
    p_apply.add_argument("--limit", type=int, help="maximo de vagas nesta execucao")
    p_apply.add_argument("--per-company", type=int, default=200)
    p_apply.add_argument("--mode", choices=[m.value for m in SubmitMode], help="sobrescreve submit_mode")
    p_apply.add_argument("--force", action="store_true", help="ignora dedupe, limites e validacao")
    p_apply.add_argument("--yes", action="store_true", help="nao pergunta ao entrar no modo auto")
    p_apply.add_argument("--role", help="forca um cargo de config/settings.yaml (ex: junior)")
    p_apply.set_defaults(func=cmd_apply)

    p_roles = sub.add_parser("roles", help="mostra os cargos alvo e quando cada um entra em vigor")
    p_roles.set_defaults(func=cmd_roles)

    p_status = sub.add_parser("status", help="mostra o historico de candidaturas")
    p_status.add_argument("--limit", type=int, default=20)
    p_status.set_defaults(func=cmd_status)

    p_export = sub.add_parser("export", help="exporta o historico para CSV/JSON")
    p_export.add_argument("--format", choices=["csv", "json"], default="csv")
    p_export.set_defaults(func=cmd_export)

    p_sources = sub.add_parser("sources", help="lista/verifica os portais configurados")
    p_sources.add_argument("action", choices=["list", "verify", "raw"], nargs="?", default="list")
    p_sources.add_argument("-c", "--company", action="append")
    p_sources.add_argument("--per-company", type=int, default=5)
    p_sources.set_defaults(func=cmd_sources)

    p_open = sub.add_parser("open", help="abre o portal da empresa (util para o primeiro login)")
    p_open.add_argument("company_key")
    p_open.add_argument(
        "--browser-profile",
        action="store_true",
        help="abre no navegador da automacao, para salvar a sessao de login",
    )
    p_open.set_defaults(func=cmd_open)

    p_answers = sub.add_parser("answers", help="testa como uma pergunta seria respondida")
    p_answers.add_argument("question", nargs="+")
    p_answers.add_argument("--kind", default="text", help="text|select|radio|checkbox")
    p_answers.add_argument("--option", action="append", help="opcao do select/radio (repita)")
    p_answers.add_argument("--role", help="testa com as respostas de um cargo especifico")
    p_answers.set_defaults(func=cmd_answers)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except ConfigError as exc:
        print(f"\nErro de configuracao:\n  {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrompido.", file=sys.stderr)
        return 130
    except BrokenPipeError:
        # Saida fechada do outro lado (ex.: `candidate roles | head`).
        # Redireciona para devnull para o interpretador nao reclamar no shutdown.
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except OSError:
            pass
        return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
