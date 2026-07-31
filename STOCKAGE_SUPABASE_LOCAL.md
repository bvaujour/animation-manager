# Stockage Supabase depuis le serveur local

Le stockage des documents est indépendant de `DEBUG`.

## Comportement recommandé

```env
FILE_STORAGE_BACKEND=auto
SUPABASE_S3_ACCESS_KEY=...
SUPABASE_S3_SECRET_KEY=...
SUPABASE_S3_BUCKET=Documents
SUPABASE_S3_ENDPOINT_URL=https://<project-ref>.storage.supabase.co/storage/v1/s3
SUPABASE_S3_REGION=eu-west-1
```

Avec `auto`, Supabase est utilisé dès que les deux clés S3 sont présentes, y compris avec `python manage.py runserver`. Sans clés, le stockage local est utilisé.

Pour imposer Supabase :

```env
FILE_STORAGE_BACKEND=s3
```

Pour imposer le disque local :

```env
FILE_STORAGE_BACKEND=local
```

Les tests Django restent forcés sur le stockage local pour ne pas écrire dans le bucket.
