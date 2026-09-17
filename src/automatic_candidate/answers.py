"""Traduz o rotulo de um campo de formulario na resposta certa do seu perfil.

Todo portal inventa um nome diferente para o mesmo campo ("Telefone",
"Phone number", "mobile_phone", "Celular*"). Este modulo resolve isso em
tres camadas, nesta ordem:

  1. screening_answers do config/profile.yaml (regex que VOCE escreveu);
  2. tabela de campos conhecidos (nome, email, links, endereco, salario...);
  3. nada — o campo fica em branco e entra no relatorio como pendente,
     para voce responder na revisao.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from automatic_candidate.config import Profile

logger = logging.getLogger(__name__)

FieldKind = str  # text | textarea | email | tel | url | number | select | radio | checkbox | file


@dataclass(slots=True)
class FormField:
    """Um campo detectado na pagina."""

    label: str
    kind: FieldKind = "text"
    name: str = ""
    placeholder: str = ""
    required: bool = False
    options: list[str] = field(default_factory=list)

    @property
    def haystack(self) -> str:
        return " ".join(p for p in (self.label, self.name, self.placeholder) if p)


@dataclass(slots=True)
class Answer:
    value: str
    source: str          # "screening_answers" | "perfil:<campo>" | "consent"
    confidence: float = 1.0
    option: str | None = None   # opcao escolhida em select/radio


def _norm(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", stripped).strip().lower()


AFFIRMATIVE = ("sim", "yes", "y", "true", "aceito", "concordo", "i agree", "agree")
NEGATIVE = ("nao", "no", "false", "nego")
NEUTRAL = (
    "prefiro nao",
    "prefer not",
    "decline",
    "i don't wish",
    "nao informar",
    "nao desejo",
)


class AnswerBook:
    """Resolve campos de formulario a partir do perfil do usuario."""

    def __init__(
        self, profile: Profile, extra_answers: list[dict[str, Any]] | None = None
    ) -> None:
        """extra_answers vem do cargo ativo (config/settings.yaml -> roles) e
        entra na frente das regras do perfil: perguntas de estagio ganham de
        respostas genericas."""
        self.profile = profile
        self._rules = self._compile_rules(extra_answers or []) + self._compile_screening_rules()
        self._builtin = self._build_builtin_table()

    # ------------------------------------------------------------------ setup
    def _compile_screening_rules(self) -> list[tuple[list[re.Pattern[str]], str]]:
        return self._compile_rules(self.profile.screening_answers)

    @staticmethod
    def _compile_rules(entries: list[dict[str, Any]]) -> list[tuple[list[re.Pattern[str]], str]]:
        rules: list[tuple[list[re.Pattern[str]], str]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            patterns_raw = entry.get("match") or []
            if isinstance(patterns_raw, str):
                patterns_raw = [patterns_raw]
            compiled: list[re.Pattern[str]] = []
            for pattern in patterns_raw:
                try:
                    compiled.append(re.compile(_norm(str(pattern)), re.IGNORECASE))
                except re.error as exc:
                    logger.warning("regex invalida em screening_answers: %r (%s)", pattern, exc)
            if compiled:
                rules.append((compiled, str(entry.get("answer", "")).strip()))
        return rules

    def _build_builtin_table(self) -> list[tuple[re.Pattern[str], Callable[[], str], str]]:
        p = self.profile

        def get(dotted: str) -> Callable[[], str]:
            return lambda: str(p.get(dotted, ""))

        table: list[tuple[str, Callable[[], str], str]] = [
            # nome
            (r"\b(primeiro nome|first[_ ]?name|nome\b(?!.*completo)|given name)",
             get("personal.first_name"), "personal.first_name"),
            (r"\b(sobrenome|last[_ ]?name|surname|family name)", get("personal.last_name"), "personal.last_name"),
            (r"\b(nome completo|full[_ ]?name|nome do candidato)", lambda: p.full_name, "personal.full_name"),
            # contato
            (r"\b(e-?mail|correio eletronico)", get("personal.email"), "personal.email"),
            (r"\b(telefone|phone|celular|mobile|whatsapp|contact number)",
             get("personal.phone"), "personal.phone"),
            (r"\b(ddi|country code|codigo do pais)", get("personal.phone_country_code"), "personal.phone_country_code"),
            # documentos
            (r"\bcpf\b", get("personal.cpf"), "personal.cpf"),
            (r"\b(data de nascimento|birth ?date|date of birth|nascimento)",
             get("personal.birth_date"), "personal.birth_date"),
            # links
            (r"\blinkedin\b", get("links.linkedin"), "links.linkedin"),
            (r"\b(github|git hub)\b", get("links.github"), "links.github"),
            (r"\b(portfolio|portfolio url|behance|dribbble)", get("links.portfolio"), "links.portfolio"),
            (r"\b(website|site pessoal|personal site|blog)", get("links.website"), "links.website"),
            # endereco
            (r"\b(cidade|city|municipio)", get("location.city"), "location.city"),
            (r"\b(estado|state|provincia|uf)\b", get("location.state"), "location.state"),
            (r"\b(pais|country)\b", get("location.country"), "location.country"),
            (r"\b(cep|postal code|zip)", get("location.postal_code"), "location.postal_code"),
            (r"\b(endereco|address|logradouro|street)", get("location.address_line1"), "location.address_line1"),
            (r"\b(complemento|address line 2)", get("location.address_line2"), "location.address_line2"),
            # profissional
            (r"\b(cargo atual|current title|job title|titulo atual)",
             get("professional.current_title"), "professional.current_title"),
            (r"\b(empresa atual|current company|current employer)",
             get("professional.current_company"), "professional.current_company"),
            (r"\b(anos de experiencia|years of experience|experience \(years\))",
             lambda: str(p.get("professional.years_of_experience", "")),
             "professional.years_of_experience"),
            (r"\b(resumo|headline|about you|summary)", get("professional.headline"), "professional.headline"),
            # academico (processos de estagio perguntam sempre)
            (r"\b(previsao de (formatura|conclusao)|graduation date|quando se forma|formatura)",
             lambda: str(p.get("education.0.expected_graduation", "")),
             "education.expected_graduation"),
            (r"\b(semestre|periodo do curso)",
             lambda: str(p.get("education.0.current_semester", "")),
             "education.current_semester"),
            (r"\b(curso|graduacao)\b",
             lambda: str(p.get("education.0.degree", "")), "education.degree"),
            (r"\b(institui(c|ç)ao de ensino|universidade|faculdade|school|university)",
             lambda: str(p.get("education.0.school", "")), "education.school"),
            (r"\b(turno|periodo das aulas)",
             lambda: str(p.get("education.0.shift", "")), "education.shift"),
            # salario
            (r"\b(pretensao|salary|remuneracao|compensation|expected pay)",
             self._salary_answer, "compensation"),
        ]
        return [(re.compile(pattern, re.IGNORECASE), getter, origin) for pattern, getter, origin in table]

    def _salary_answer(self) -> str:
        text = str(self.profile.get("compensation.salary_answer_text", ""))
        if text:
            return text
        monthly = self.profile.get("compensation.desired_salary_monthly", "")
        currency = self.profile.get("compensation.currency", "BRL")
        return f"{currency} {monthly}" if monthly else ""

    # ----------------------------------------------------------------- lookup
    def resolve(self, form_field: FormField) -> Answer | None:
        """Melhor resposta para o campo, ou None se nao souber."""
        haystack = _norm(form_field.haystack)
        if not haystack:
            return None

        if form_field.kind == "checkbox":
            consent = self._consent_answer(haystack)
            if consent is not None:
                return consent

        for patterns, answer_text in self._rules:
            if any(pattern.search(haystack) for pattern in patterns):
                return self._fit(Answer(answer_text, "screening_answers"), form_field)

        for pattern, getter, origin in self._builtin:
            if pattern.search(haystack):
                value = (getter() or "").strip()
                if value:
                    return self._fit(Answer(value, f"perfil:{origin}"), form_field)

        if form_field.kind in {"select", "radio"} and form_field.required:
            fallback = self._neutral_option(form_field.options)
            if fallback:
                return Answer(fallback, "fallback:opcao-neutra", confidence=0.3, option=fallback)

        return None

    def _consent_answer(self, haystack: str) -> Answer | None:
        consents = self.profile.consents
        mapping = [
            (r"(marketing|newsletter|novidades|promocion)", "marketing_emails"),
            (r"(banco de talentos|talent (pool|community)|futuras (vagas|oportunidades))", "talent_pool"),
            (r"(termos|terms|condicoes|privacidade|privacy|lgpd|gdpr|tratamento de dados|consent)", "data_processing"),
        ]
        for pattern, key in mapping:
            if re.search(pattern, haystack, re.IGNORECASE):
                accepted = bool(consents.get(key, key != "marketing_emails"))
                return Answer("true" if accepted else "false", f"consent:{key}")
        return None

    # --------------------------------------------------------- select / radio
    def _fit(self, answer: Answer, form_field: FormField) -> Answer:
        """Encaixa a resposta livre numa das opcoes, quando o campo e fechado."""
        if form_field.kind not in {"select", "radio"} or not form_field.options:
            return answer
        option = self.match_option(answer.value, form_field.options)
        if option is None:
            neutral = self._neutral_option(form_field.options)
            if neutral:
                return Answer(neutral, answer.source + "+opcao-neutra", 0.4, neutral)
            return Answer(answer.value, answer.source, 0.2)
        return Answer(option, answer.source, answer.confidence, option)

    @staticmethod
    def match_option(value: str, options: list[str]) -> str | None:
        """Casa uma resposta textual com a opcao mais proxima do select."""
        target = _norm(value)
        if not target:
            return None
        normalized = [(option, _norm(option)) for option in options]

        for option, norm_option in normalized:
            if norm_option == target:
                return option
        for option, norm_option in normalized:
            if norm_option and (norm_option in target or target in norm_option):
                return option

        def group(text: str) -> str | None:
            if any(text.startswith(word) or text == word for word in AFFIRMATIVE):
                return "yes"
            if any(text.startswith(word) or text == word for word in NEGATIVE):
                return "no"
            if any(word in text for word in NEUTRAL):
                return "neutral"
            return None

        target_group = group(target)
        if target_group:
            for option, norm_option in normalized:
                if group(norm_option) == target_group:
                    return option

        target_words = {w for w in re.findall(r"\w+", target) if len(w) > 3}
        if target_words:
            best: tuple[int, str] | None = None
            for option, norm_option in normalized:
                overlap = len(target_words & set(re.findall(r"\w+", norm_option)))
                if overlap and (best is None or overlap > best[0]):
                    best = (overlap, option)
            if best:
                return best[1]
        return None

    @staticmethod
    def _neutral_option(options: list[str]) -> str | None:
        for option in options:
            norm_option = _norm(option)
            if any(word in norm_option for word in NEUTRAL):
                return option
        return None

    # ------------------------------------------------------------- relatorios
    def coverage_report(self, fields: list[FormField]) -> tuple[dict[str, str], list[str]]:
        """(campos respondidos, rotulos sem resposta) — usado no modo review."""
        answered: dict[str, str] = {}
        missing: list[str] = []
        for form_field in fields:
            answer = self.resolve(form_field)
            if answer and answer.value:
                answered[form_field.label or form_field.name] = answer.value
            else:
                missing.append(form_field.label or form_field.name)
        return answered, missing


def redact(value: str) -> str:
    """Esconde dados sensiveis nos logs (CPF, telefone, e-mail)."""
    if not value:
        return value
    if "@" in value:
        user, _, domain = value.partition("@")
        return f"{user[:2]}***@{domain}"
    digits = re.sub(r"\D", "", value)
    if len(digits) >= 8:
        return f"***{digits[-4:]}"
    return value
