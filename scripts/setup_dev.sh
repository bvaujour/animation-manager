#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-.venv}"

"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r requirements-dev.txt

if [[ ! -f .env ]]; then
    cp .env.example .env
fi

"$VENV_DIR/bin/python" manage.py migrate

echo "Environnement prêt. Activation : source $VENV_DIR/bin/activate"
