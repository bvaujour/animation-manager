# Configuration de l'envoi d'e-mails

L'application utilise le système e-mail natif de Django. La page **E-mails**
permet de sélectionner des animateurs ayant une adresse renseignée, d'ajouter
d'autres adresses, de saisir un message et de joindre des documents existants.

## Développement local

Sans variable `EMAIL_HOST`, le backend console est utilisé. Le message n'est pas
envoyé : son contenu apparaît dans le terminal où `runserver` est lancé.

## Envoi réel avec Brevo SMTP

1. Créer/valider un expéditeur dans Brevo.
2. Générer une clé SMTP dans `Paramètres > SMTP & API`.
3. Ajouter dans `.env` en local ou dans **Render > Environment** :

```env
EMAIL_HOST=smtp-relay.brevo.com
EMAIL_PORT=587
EMAIL_HOST_USER=ton-login-smtp
EMAIL_HOST_PASSWORD=ta-cle-smtp
EMAIL_USE_TLS=True
EMAIL_USE_SSL=False
DEFAULT_FROM_EMAIL=Gestion animation <adresse-validee@ton-domaine.fr>
EMAIL_REPLY_TO=adresse-de-reponse@ton-domaine.fr
```

Ne jamais mettre la clé SMTP dans GitHub.

## Autres fournisseurs

Mailjet, Gmail Workspace ou tout serveur SMTP peuvent être utilisés en changeant
les mêmes variables. Ne jamais activer TLS et SSL simultanément.

## Limites intégrées

- 100 destinataires maximum par envoi ;
- 10 documents maximum ;
- 20 Mo maximum pour l'ensemble des pièces jointes.
