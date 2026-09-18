# automatic-candidate

Ferramenta de linha de comando que procura vagas nos portais de carreira das
empresas e preenche os formulários de candidatura pra você.

Nasceu de um incômodo bobo: digitar nome, e-mail, telefone, LinkedIn e "qual
sua pretensão salarial?" pela quadragésima vez, em portais que já têm esses
dados. O que sobra de tempo dá pra usar escolhendo melhor a vaga.

Roda inteira na sua máquina. Seus dados ficam em arquivos locais que o
`.gitignore` já bloqueia, e não tem servidor no meio: nada sai daqui além do
que vai pro site da empresa onde você está se candidatando.

Requer Python 3.10 ou mais novo.

## O que esperar

Por padrão ela **não envia nada sozinha**. O modo recomendado abre o navegador,
preenche o formulário, tira um print e para, esperando você conferir e
confirmar. Você pode liberar o envio automático depois, portal por portal, mas
isso é opt-in em dois lugares diferentes justamente porque candidatura enviada
não tem botão de desfazer.

Ela também não tenta burlar nada. Se aparecer captcha ou 2FA, o controle volta
pra você resolver na mão.

## Instalação

```bash
git clone https://github.com/thns7/automatic-candidate.git
cd automatic-candidate

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -e ".[browser]"
python -m playwright install chromium
```

Se você só quer listar vagas e ainda não se importa com o preenchimento
automático, `pip install -e .` basta. O Playwright (e o Chromium) só entram em
cena na hora de abrir formulário.

Depois:

```bash
candidate init      # cria os arquivos de configuração a partir dos modelos
candidate doctor    # aponta o que ainda falta preencher
candidate discover  # lista as vagas que passaram nos filtros
candidate apply --limit 3
```

## Onde ficam os seus dados

O `candidate init` copia quatro modelos `.example` para os arquivos que você vai
editar. Todos estão no `.gitignore`, então dá pra preencher sem medo de commitar
sem querer.

| Arquivo | Conteúdo |
|---|---|
| `config/profile.yaml` | nome, contato, endereço, links, formação, experiência e as respostas de triagem |
| `.env` | CPF, e-mails e senhas dos portais |
| `data/resumes/` | seu currículo em PDF |
| `config/companies.yaml` | as empresas que você quer acompanhar |
| `config/settings.yaml` | cargo alvo, filtros de vaga, limites e modo de envio |
| `templates/cover_letter.md.j2` | o texto da carta de apresentação |

### profile.yaml

É o arquivo que dá mais retorno pelo tempo investido:

```yaml
personal:
  first_name: "Seu"
  last_name: "Nome"
  email: "voce@exemplo.com"
  phone: "+55 11 99999-9999"     # formato internacional passa em mais máscaras
  cpf: "${CPF}"                  # o valor real vai no .env

links:
  linkedin: "https://www.linkedin.com/in/seu-perfil"
  github: "https://github.com/seu-usuario"

documents:
  resumes:
    default: "data/resumes/curriculo.pdf"
```

Qualquer campo pode buscar valor no `.env` com `${VARIAVEL}`, o que é útil pra
não deixar CPF escrito num YAML.

A parte mais poderosa é `screening_answers`. Cada regra casa o texto da pergunta
do formulário (regex, ignorando maiúsculas e acentos) com a resposta que você
quer dar:

```yaml
screening_answers:
  - match: ["pretens(a|ã)o salarial", "salary expectation", "expected compensation"]
    answer: "R$ 15.000 mensais (aberto a negociação)"
  - match: ["aviso pr(e|é)vio", "notice period", "start date"]
    answer: "30 dias"
  - match: ["ingl(e|ê)s", "english level"]
    answer: "Avançado"
```

Dá pra testar uma pergunta antes de rodar pra valer:

```bash
candidate answers "Qual a sua pretensão salarial?"
candidate answers "Nível de inglês" --kind select --option Básico --option Avançado
```

Se a resposta vier `(sem resposta)`, é sinal de que falta uma regra. Campo que a
automação não reconhece ela deixa em branco e reporta como pendente. Ela não
chuta resposta no seu lugar.

### .env

```bash
CPF=000.000.000-00

GUPY_EMAIL=voce@exemplo.com     # Gupy vale pra Itaú, Zamp e boa parte do mercado BR
GUPY_PASSWORD=sua-senha
NVIDIA_EMAIL=voce@exemplo.com   # Workday
NVIDIA_PASSWORD=sua-senha
```

### Currículo

Coloque o PDF em `data/resumes/` e aponte o caminho no perfil. Dá pra manter
versões diferentes e escolher qual vai pra cada empresa:

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
  resume: ai
```

## Cargo alvo

Os filtros mudam conforme o momento da carreira, e mudam em data previsível:
quem procura estágio hoje vai procurar júnior depois de formar. Em vez de
reescrever os filtros quando chegar a hora, você declara os cargos com janela de
validade e a busca vira sozinha.

```yaml
active_role: auto     # decide pela data; troque pelo nome de um cargo pra travar

roles:
  - name: estagio
    description: "Estágio em tecnologia"
    valid_until: "2027-12-31"
    resume: estagio
    filters:
      title_include: [estagi, estági, intern, internship, aprendiz]
      title_exclude: [senior, pleno, manager, vendas, rh]
      posted_within_days: 30       # vaga de estágio fecha rápido
    screening_answers:             # perguntas que só aparecem nesse tipo de processo
      - match: ["previs(a|ã)o de (formatura|conclus(a|ã)o)", "graduation date"]
        answer: "Dezembro de 2028"

  - name: junior
    valid_from: "2028-01-01"
    valid_until: "2029-12-31"
    filters:
      title_include: [junior, júnior, engenheir, developer, backend]
      title_exclude: [estagi, intern, trainee, senior, manager]

  - name: pleno
    valid_from: "2030-01-01"
```

Vale o primeiro cargo cuja janela cobre a data de hoje:

```console
$ candidate roles
hoje: 2026-09-18   (active_role: auto)

>> estagio    sempre ate 2027-12-31      Estágio em tecnologia
      titulos: estagi, estági, intern, internship, aprendiz
      curriculo: documents.resumes.estagio
      +7 resposta(s) de triagem so deste cargo
   junior     2028-01-01 ate 2029-12-31  Desenvolvedor junior / entry level
   pleno      2030-01-01 ate sem prazo   Desenvolvedor pleno

proxima troca: junior em 2028-01-01 (em 470 dias) — automatica, voce nao precisa fazer nada.
```

Alguns detalhes de comportamento:

Os `filters` do cargo **substituem** as chaves que declaram, em vez de somar com
o bloco `filters` base. Tem que ser assim: a lista base exclui `estagi`, e um
cargo de estágio precisa poder apagar essa exclusão. Chave que o cargo não
declara continua herdada.

O `resume` escolhe a variante do currículo, mas um pedido explícito da empresa
em `companies.yaml` tem prioridade.

As `screening_answers` do cargo entram na frente das do perfil. Enquanto o cargo
for estágio, "pretensão salarial" responde sobre a bolsa, e não sobre salário
CLT.

Se quiser espiar como ficaria outro cargo sem mexer em nada:
`candidate discover --role junior`.

Processo de estágio quase sempre pergunta curso, semestre e previsão de
formatura. Isso sai direto do primeiro item de `education` no perfil, sem
precisar de regra:

```yaml
education:
  - degree: "Bacharelado em Ciência da Computação"
    school: "Universidade Exemplo"
    status: "cursando"
    current_semester: "5o semestre"
    expected_graduation: "Dezembro de 2028"
    shift: "Noturno"
```

## Empresas e portais

Empresa grande quase nunca tem API de candidatura. O que existe é o sistema de
recrutamento que ela contratou, e a maioria expõe as vagas publicadas em JSON
público. A ferramenta fala com estes:

| `source.type` | Quem costuma usar |
|---|---|
| `workday` | NVIDIA e boa parte das multinacionais |
| `gupy` | Itaú, Zamp e a maior parte do mercado brasileiro |
| `microsoft` | Microsoft |
| `greenhouse` | Nubank e muitas startups |
| `lever` | várias empresas de tecnologia |
| `ashby` | startups mais recentes |
| `smartrecruiters` | Mercado Livre, Bosch |
| `manual` | Google e outros sites sem API estável |

O `manual` é o caso em que não dá pra listar vagas por API: a ferramenta abre a
busca no navegador pra você escolher, e assume dali em diante preenchendo o
formulário.

Uma entrada de `config/companies.yaml` é assim:

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

Para acompanhar uma empresa que não vem no arquivo, descubra qual portal ela
usa (costuma estar na URL da página de carreiras) e copie o bloco trocando o
`board`. `boards.greenhouse.io/empresa` vira `type: greenhouse, board: empresa`,
`empresa.gupy.io` vira `type: gupy, board: empresa`, e assim por diante.

Vale avisar: esses slugs são das empresas e mudam sem aviso. Quando algo parar
de responder, `candidate sources verify` diz qual portal quebrou e
`candidate sources raw -c itau` mostra o JSON cru pra você achar o nome novo.

## Modos de envio

Configurado em `submit_mode`, no `config/settings.yaml`:

| Modo | Comportamento |
|---|---|
| `dry_run` | só descobre e lista as vagas, sem abrir navegador |
| `review` | abre o navegador, preenche tudo, tira print e para pra você confirmar |
| `auto` | preenche e envia direto; exige também `allow_auto_submit: true` na empresa |

O padrão é `review`, e a recomendação é ficar nele por um tempo. Olhe os prints
em `data/screenshots/` e só migre pro `auto` nos portais em que você já viu a
automação acertar. Um formulário errado chega ao recrutador como resultado, não
como intenção.

Tem também limites, pra evitar rajada de candidatura e conta bloqueada:

```yaml
limits:
  max_applications_per_run: 5
  max_applications_per_day: 15
  max_per_company_per_day: 5
  min_seconds_between_applications: 45
  max_seconds_between_applications: 120
```

O histórico fica num SQLite em `data/applications.sqlite3`, então a mesma vaga
nunca é trabalhada duas vezes, mesmo entre execuções.

## Login nos portais

A automação usa um perfil de navegador persistente, guardado em
`browser-profile/`. Você loga uma vez em cada portal e as execuções seguintes já
entram autenticadas:

```bash
candidate open itau --browser-profile
```

Quando aparecer captcha ou verificação em duas etapas, a execução pausa e avisa.
Você resolve na janela que está aberta e aperta ENTER pra continuar.

## Comandos

```bash
candidate init                          # cria os arquivos de configuração
candidate doctor                        # confere config, currículo e dependências
candidate discover                      # busca e filtra vagas (não envia nada)
candidate discover -c itau -c nvidia    # só nessas empresas
candidate discover --show-rejected 20   # mostra também o que foi descartado e por quê
candidate roles                         # cargos alvo, qual vale hoje e quando troca
candidate discover --role junior        # espia outro cargo sem mudar a configuração
candidate apply --limit 3               # preenche e pede confirmação
candidate apply --mode dry_run          # sobrescreve o modo nesta execução
candidate status                        # histórico de candidaturas
candidate export --format csv           # exporta para data/reports/
candidate sources verify                # checa se os portais ainda respondem
candidate sources raw -c zamp           # JSON cru do portal, pra ajustar slugs
candidate open google                   # abre a busca de vagas da empresa
candidate answers "Pretensão salarial?" # testa uma pergunta de triagem
```

## Como funciona por dentro

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

`sources/` tem uma classe por portal e só lê API pública. `matching.py` filtra e
dá nota pra cada vaga. `answers.py` é o miolo do preenchimento: é ele que
entende que "Telefone celular", "Phone number" e `mobile_phone` são a mesma
coisa. `appliers/` usa Playwright pra achar os campos visíveis, descobrir o
rótulo de cada um (label, `aria-label`, legenda do fieldset, texto anterior),
preencher e anexar os arquivos. `storage.py` guarda o histórico.

## Rodando os testes

```bash
pip install -e ".[dev,browser]"
python -m playwright install chromium

pytest
ruff check src tests
```

Os testes de integração preenchem um formulário de candidatura de verdade
(`tests/fixtures_form.html`, com select, radio, checkbox de consentimento e dois
campos de arquivo) e conferem o resultado campo a campo. Sem Playwright
instalado eles são pulados e o resto da suíte roda normal.

## Quando algo não funciona

**`discover` não trouxe nada.** Provavelmente os filtros estão apertados demais,
ou o cargo ativo está mirando em outra coisa. Rode `candidate roles` pra ver qual
cargo vale hoje e `candidate discover --show-rejected 20` pra ver o que foi
descartado e por quê.

**`sources verify` acusou falha num portal.** O slug mudou, é o motivo mais
comum. Abra a página de carreiras da empresa, confira o endereço e ajuste o
`board` (ou `host`/`site`, no caso do Workday) no `companies.yaml`.
`candidate sources raw -c <empresa>` ajuda a ver o que o portal está devolvendo.

**Campos ficando em branco no formulário.** Use `candidate answers "<a pergunta>"`
pra ver o que a automação responderia. Se vier `(sem resposta)`, acrescente uma
regra em `screening_answers`.

**"Playwright não está instalado".** `pip install -e ".[browser]"` seguido de
`python -m playwright install chromium`.

**Já tenho Chrome instalado e não quero outro download.** Aponte o executável em
`browser.executable_path`, no `settings.yaml`, ou exporte
`PLAYWRIGHT_CHROMIUM_EXECUTABLE`.

**O portal fica pedindo login toda vez.** Faça o login uma vez com
`candidate open <empresa> --browser-profile` e deixe a sessão salva no perfil do
navegador. Se o site usa 2FA, essa é a forma de resolver.

## Contribuindo

Contribuição mais útil de todas: portal novo ou slug corrigido. O mercado de
recrutamento muda toda hora e ninguém acompanha tudo sozinho.

Para adicionar um portal, crie uma classe em `src/automatic_candidate/sources/`
herdando de `JobSource`, implemente `fetch()` devolvendo uma lista de
`JobPosting` e registre em `SOURCES` (`sources/__init__.py`). Os testes em
`tests/test_sources.py` usam payloads gravados, então dá pra testar o parsing
sem rede. Copie um caso de lá.

Se o portal tiver alguma particularidade no formulário (login, banner de cookie,
botão que abre o formulário só depois de um clique), crie também um applier em
`appliers/portals.py` herdando de `GenericFormApplier` e sobrescreva só o que
muda. O preenchimento genérico já resolve a maior parte dos casos.

Issues com o print do formulário que não foi preenchido corretamente ajudam
bastante, mas **apague os seus dados pessoais do print antes de anexar**.

## Antes de sair usando

Vários portais restringem automação nos termos de uso. Leia os do site que você
vai usar e decida com consciência: o risco é de quem roda. Manter os limites
baixos, o modo `review` ligado e o ritmo parecido com o humano é o que mantém
isso razoável.

Volume também não é o objetivo. Trinta candidaturas genéricas rendem menos que
cinco bem escolhidas, e os filtros existem pra mirar, não pra espalhar.

Por fim: isto aqui é pra você se candidatar às suas vagas. Não é ferramenta pra
disparar currículo de terceiros nem pra vender serviço de candidatura em massa.

## Licença

MIT. Veja [LICENSE](LICENSE).
