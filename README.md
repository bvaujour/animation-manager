# animation-manager (AM)

Application Django de gestion d'une équipe d'animation : animateurs,
centres, qualifications, disponibilités, planning (FullCalendar) et
récapitulatif.

## Démarrage rapide (local, sans Supabase)

Le projet fonctionne **sans aucune configuration** : s'il ne trouve pas de
base Postgres dans les variables d'environnement, il bascule
automatiquement sur SQLite + stockage de fichiers local.

```bash
python -m venv venv
source venv/bin/activate          # Windows : venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser  # optionnel, pour l'admin /admin/
python manage.py runserver
```

Puis ouvrez http://127.0.0.1:8000/.

> Astuce : créez d'abord quelques centres et animateurs via la page
> **Gestion** (ou l'admin Django) avant d'utiliser le planning.

## Utilisation de Supabase (Postgres + stockage S3)

Copiez `.env.example` en `.env` et renseignez les valeurs. Dès que
`DB_HOST` est défini, le projet utilise Postgres ; dès que les clés S3
sont définies, les documents sont stockés sur Supabase.

```bash
cp .env.example .env
# éditez .env, puis :
python manage.py migrate
python manage.py runserver
```

## Notes de configuration

- `config/settings.py` : bascule automatique Postgres/SQLite selon la
  présence de `DB_HOST`, et S3/local selon la présence des clés S3.
- Le stockage local écrit dans `media/` (servi en dev seulement, quand
  `DEBUG=True`).
- Pensez à passer `DEBUG = False` et à définir un vrai `SECRET_KEY` en
  production.

## Déploiement (Render)

`build.sh` installe les dépendances, collecte les fichiers statiques et
applique les migrations. Configurez les variables d'environnement
(`DB_*`, `SUPABASE_S3_*`) dans le tableau de bord Render.
