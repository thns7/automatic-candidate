#!/usr/bin/env bash
# Fluxo completo, do zero ate a primeira candidatura revisada.
set -euo pipefail

python -m venv .venv
source .venv/bin/activate
pip install -e ".[browser]"
python -m playwright install chromium

candidate init

cat <<'TXT'

Agora edite, nesta ordem:
  1. config/profile.yaml   -> seus dados e as respostas de triagem
  2. .env                  -> CPF e senhas dos portais
  3. data/resumes/         -> coloque seu curriculo.pdf aqui
  4. config/companies.yaml -> empresas que voce quer acompanhar

Quando terminar, rode:
  candidate doctor
  candidate sources verify
  candidate discover
  candidate apply --limit 3

TXT
