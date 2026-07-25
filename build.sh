#!/usr/bin/env bash
set -Eeuo pipefail

python -m pip install -r requirements.txt
python manage.py check
python manage.py collectstatic --noinput
python manage.py migrate --noinput
