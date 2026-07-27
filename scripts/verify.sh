#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

python scripts/static_audit.py

while IFS= read -r -d '' file; do
    node --check "$file" >/dev/null
done < <(find static/js -type f -name '*.js' -print0)
echo "Syntaxe JavaScript : OK"

if python -c 'import django' >/dev/null 2>&1; then
    python manage.py check
    python manage.py test animateurs.tests
else
    echo "Contrôles Django : NON EXÉCUTÉS (Django absent de l'environnement courant)"
fi

if command -v ruff >/dev/null 2>&1; then
    ruff check config animateurs scripts
else
    echo "Ruff : NON EXÉCUTÉ (commande absente de l'environnement courant)"
fi
