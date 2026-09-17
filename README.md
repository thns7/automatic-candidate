# automatic-candidate

Automação **pessoal** para descobrir vagas de engenharia de software nas empresas
que você escolher (Itaú, NVIDIA, Google, Microsoft, Zamp, e qualquer outra) e
preencher as candidaturas nos portais delas.

Escrito em Python. Sem serviço externo, sem banco na nuvem, sem enviar seus
dados para lugar nenhum: tudo roda na sua máquina, a partir de arquivos que
ficam no seu computador e **não** vão para o Git.

---

## Início rápido

```bash
git clone https://github.com/thns7/automatic-candidate.git
cd automatic-candidate

python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[browser]"
python -m playwright install chromium

candidate init      # cria os arquivos de configuração
# >>> edite os arquivos (seção abaixo) <<<
candidate doctor    # confere se está tudo certo
candidate discover  # lista as vagas que passaram nos filtros
candidate apply --limit 3
```

---

## 📍 ONDE COLOCAR AS SUAS INFORMAÇÕES

`candidate init` cria quatro arquivos a partir dos modelos `.example`.
**Todos os quatro estão no `.gitignore`** — pode preencher à vontade que nada
vaza para o GitHub.

| Arquivo | O que vai nele |
|---|---|
| **`config/profile.yaml`** | **Seus dados**: nome, e-mail, telefone, endereço, LinkedIn/GitHub, formação, experiência, pretensão salarial e as **respostas de triagem** |
| **`.env`** | **Segredos**: CPF, e-mails e senhas dos portais. Referenciados nos YAMLs como `${CPF}` |
| **`data/resumes/`** | **Seu currículo em PDF**. Aponte o caminho em `documents.resumes.default` |
| **`config/companies.yaml`** | As **empresas** que você quer acompanhar (já vem com Itaú, NVIDIA, Google, Microsoft e Zamp) |
| **`config/settings.yaml`** | **Filtros** de vaga, limites diários e o modo de envio |
| **`templates/cover_letter.md.j2`** | O texto da sua **carta de apresentação** |

### 1. `config/profile.yaml` — o arquivo mais importante

```yaml
personal:
  first_name: "Thiago"
  last_name: "Nascimento"
  email: "seu.email@exemplo.com"      # <- troque
  phone: "+55 11 99999-9999"          # <- troque
  cpf: "${CPF}"                       # <- deixe assim; o valor vai no .env

links:
  linkedin: "https://www.linkedin.com/in/seu-perfil"
  github: "https://github.com/thns7"

documents:
  resumes:
    default: "data/resumes/curriculo.pdf"   # <- coloque o PDF aqui
```

**A parte que mais economiza seu tempo** é `screening_answers`. Cada regra casa
o *texto da pergunta* do formulário (regex, sem diferenciar maiúscula ou acento)
com a resposta que você quer dar:

```yaml
screening_answers:
  - match: ["pretens(a|ã)o salarial", "salary expectation", "expected compensation"]
    answer: "R$ 15.000 mensais (aberto a negociação)"
  - match: ["aviso pr(e|é)vio", "notice period", "start date"]
    answer: "30 dias"
  - match: ["ingl(e|ê)s", "english level"]
    answer: "Avançado"
```

Quer saber como uma pergunta específica seria respondida antes de rodar?

```bash
candidate answers "Qual a sua pretensão salarial?"
candidate answers "Nível de inglês" --kind select --option Básico --option Avançado
```

Se aparecer `(sem resposta)`, adicione uma regra em `screening_answers`. A
automação **nunca inventa resposta**: campo que ela não conhece fica em branco e
entra no relatório como pendente, para você preencher na revisão.

### 2. `.env` — só o que é sensível

```bash
CPF=000.000.000-00
GUPY_EMAIL=seu.email@exemplo.com     # Itaú, Zamp e a maioria das empresas BR
GUPY_PASSWORD=sua-senha
NVIDIA_EMAIL=seu.email@exemplo.com   # Workday
NVIDIA_PASSWORD=sua-senha
```

Qualquer valor de `config/*.yaml` pode ler daqui com `${NOME_DA_VARIAVEL}`.

### 3. `data/resumes/` — seu currículo

Coloque o PDF e aponte em `documents.resumes.default`. Dá para ter variantes por
área e escolher qual usar em cada empresa:

```yaml
# profile.yaml
documents:
  resumes:
    default: "data/resumes/curriculo.pdf"
    ai:      "data/resumes/curriculo-ml.pdf"
    en:      "data/resumes/resume-en.pdf"
```
```yaml
# companies.yaml
- key: nvidia
  resume: ai      # a NVIDIA recebe a versão de ML
```

---

## 🏢 Empresas e portais

Empresa grande quase nunca tem "API de candidatura". O que existe é o portal de
recrutamento que ela usa. Este projeto fala com os principais:

| `source.type` | Quem usa | Descoberta de vagas |
|---|---|---|
| `workday` | NVIDIA e a maioria das multinacionais | API CxS pública |
| `gupy` | **Itaú**, **Zamp** e a maior parte do mercado BR | API do portal da empresa |
| `microsoft` | Microsoft | API de busca do site de carreiras |
| `greenhouse` | Nubank, muitas startups | API pública do board |
| `lever` | várias empresas de tecnologia | API pública |
| `ashby` | startups mais novas | API pública |
| `smartrecruiters` | Mercado Livre, Bosch | API pública |
| `manual` | **Google** e sites sem API estável | você abre a busca; a automação preenche |

Exemplo de entrada em `config/companies.yaml`:

```yaml
- key: itau
  name: Itau Unibanco
  enabled: true
  source:
    type: gupy
    board: vemproitau          # https://vemproitau.gupy.io
    query: "engenheiro de software"
  apply:
    applier: gupy
    login_env_prefix: GUPY     # lê GUPY_EMAIL e GUPY_PASSWORD do .env
    allow_auto_submit: false
  resume: default
```

> **Os slugs mudam.** `vemproitau`, `NVIDIAExternalCareerSite` e afins são
> definidos pelas empresas e mudam sem aviso. Rode `candidate sources verify`
> para ver quais portais estão respondendo, e `candidate sources raw -c itau`
> para inspecionar o JSON cru quando precisar ajustar um slug.

---

## 🚦 Modos de envio

Definido em `config/settings.yaml` (`submit_mode`):

| Modo | O que faz |
|---|---|
| `dry_run` | Só descobre e lista as vagas. Não abre navegador. |
| `review` | **(recomendado)** Abre o navegador, preenche tudo, tira screenshot e **para**. Você confere e confirma no terminal. |
| `auto` | Preenche e envia sem perguntar. Exige **também** `allow_auto_submit: true` na empresa. |

O envio automático é opt-in duplo de propósito. Um formulário preenchido errado
e enviado para a empresa dos seus sonhos não tem botão de desfazer — e o
recrutador vê o resultado, não a intenção. Comece no `review`, veja os
screenshots em `data/screenshots/`, e só migre para `auto` nos portais em que
você já viu a automação acertar.

Existem também limites de segurança, para não virar spam nem derrubar sua conta:

```yaml
limits:
  max_applications_per_run: 5
  max_applications_per_day: 15
  max_per_company_per_day: 5
  min_seconds_between_applications: 45
  max_seconds_between_applications: 120
```

---

## 🔐 Login nos portais

A automação usa um **perfil de navegador persistente** (`browser-profile/`): você
loga uma vez por portal e as próximas execuções já entram autenticadas.

```bash
candidate open itau --browser-profile     # abre o portal, você loga, pronto
```

Quando houver **2FA ou captcha**, a automação **para e devolve o controle para
você** — nada é burlado aqui. Você resolve no navegador aberto e aperta ENTER
para continuar.

---

## 🧰 Comandos

```bash
candidate init                          # cria os arquivos de configuração
candidate doctor                        # confere config, currículo e dependências
candidate discover                      # busca e filtra vagas (não envia nada)
candidate discover -c itau -c nvidia    # só nestas empresas
candidate discover --show-rejected 20   # mostra também o que foi descartado e por quê
candidate apply --limit 3               # preenche e pede confirmação
candidate apply --mode dry_run          # sobrescreve o modo desta execução
candidate status                        # histórico de candidaturas
candidate export --format csv           # exporta para data/reports/
candidate sources verify                # checa se os portais respondem
candidate sources raw -c zamp           # JSON cru do portal (para ajustar slugs)
candidate open google                   # abre a busca de vagas da empresa
candidate answers "Pretensão salarial?" # testa uma pergunta de triagem
```

---

## 🗂 Como funciona

```
descobrir            filtrar/ranquear         candidatar              registrar
──────────           ────────────────         ──────────              ─────────
sources/*     ──►    matching.py        ──►   appliers/*        ──►   storage.py
(APIs dos            (title_include,          (Playwright:            (SQLite:
 portais)             localidade, data,        detecta campos,         dedupe +
                      keywords_boost)          responde, anexa         limites +
                                               currículo)              histórico)
                                                     ▲
                                              answers.py
                                        (rótulo do campo → sua resposta)
```

- **`sources/`** — um arquivo por portal, só leitura de API pública.
- **`matching.py`** — filtra e dá nota para cada vaga.
- **`answers.py`** — o cérebro do preenchimento: traduz "Telefone celular",
  "Phone number" ou `mobile_phone` para o mesmo campo do seu perfil.
- **`appliers/`** — Playwright: acha os campos visíveis, descobre o rótulo de
  cada um (label, `aria-label`, legenda do fieldset, texto anterior), preenche,
  anexa currículo e carta, e para para você revisar.
- **`storage.py`** — SQLite em `data/applications.sqlite3`: nunca se candidata
  duas vezes à mesma vaga e respeita os limites diários.

---

## ✅ Testes

```bash
pip install -e ".[dev,browser]"
python -m playwright install chromium
pytest -q          # 73 testes
ruff check src tests
```

Os testes de integração preenchem um formulário de candidatura real
(`tests/fixtures_form.html`, com select, radio, checkbox de consentimento e dois
campos de arquivo) e verificam o resultado campo a campo. Sem Playwright
instalado, eles são pulados e o resto da suíte roda normalmente.

---

## ⚠️ Antes de usar

- **Uso pessoal.** Isto automatiza *as suas* candidaturas. Não é um serviço para
  candidatar outras pessoas nem para disparar currículo em massa.
- **Termos de uso.** Vários portais restringem automação nos termos. O risco é
  seu: comece no modo `review`, mantenha os limites baixos e o ritmo humano.
- **Qualidade > volume.** Trinta candidaturas genéricas rendem menos que cinco
  bem-feitas. Use os filtros para mirar, não para espalhar.
- **A automação não burla nada**: captcha e 2FA sempre devolvem o controle para
  você.
- **Portais mudam.** Quando um `verify` falhar, é slug ou seletor que mudou —
  ajuste o `companies.yaml` ou abra uma issue.

## Licença

MIT — veja [LICENSE](LICENSE).
