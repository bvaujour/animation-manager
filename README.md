# Animation Manager

Application Django de gestion des animateurs, lieux, groupes, périodes scolaires et plannings journaliers.

## Installation locale

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

L'application utilise SQLite sans configuration supplémentaire. Une variable `DATABASE_URL` dans `.env` permet d'utiliser PostgreSQL/Supabase.

## Routes API principales

- `/api/animateurs/`
- `/api/centres/`
- `/api/centres/<id>/groupes/`
- `/api/groupes/<id>/`
- `/api/periodes-scolaires/`
- `/api/planning/`
- `/api/recapitulatif/`
- `/api/documents/`
- `/api/envois-email/`

Voir `AUDIT_NETTOYAGE_ROUTES.md` pour le détail de la passe de nettoyage.
