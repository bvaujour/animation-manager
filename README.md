# Animation Manager

Application Django de gestion des salariés, lieux, groupes, périodes scolaires, disponibilités, documents et plannings journaliers.

## Installation locale

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py runserver
```

Sans variables `DB_*`, l'application utilise SQLite. En production, renseigner `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER` et `DB_PASSWORD` pour PostgreSQL/Supabase.

## Vérifications

```bash
python manage.py check
python manage.py test animateurs.tests
python manage.py check --deploy
```

## Déploiement Render

La commande de build est contenue dans `build.sh`. La commande de démarrage recommandée est :

```bash
gunicorn config.wsgi:application
```

Définir impérativement `SECRET_KEY`, `DEBUG=False`, `ALLOWED_HOSTS` et les variables de base de données. Les fichiers utilisateurs doivent être stockés dans Supabase Storage en production.

## Organisation

- `animateurs/models.py` : modèle de données actuel ;
- `animateurs/services/` : règles métier et exports ;
- `animateurs/views.py` : pages et API ;
- `static/js/` : interfaces clientes ;
- `animateurs/tests/` : tests correspondant au modèle actuel. Les tests HTTP
  héritent de `animateurs/tests/base.py` (`ConnexionTestCase`), qui connecte
  automatiquement un compte maître pour traverser l'authentification obligatoire.

## Comptes animateurs et droits d'accès

Chaque salarié peut être relié à un compte Django depuis sa fiche dans l'administration Django (`Animateurs > Animateurs > compte de connexion`).

- Un compte de direction doit avoir le statut **staff**. Il conserve l'accès à toutes les pages et fonctions.
- Un compte animateur ne doit pas être staff. Il accède uniquement à l'accueil en lecture seule, aux documents partagés et à la saisie de ses propres disponibilités.
- La page de connexion est `/connexion/`.

Pour créer un accès animateur :
1. créer l'utilisateur dans `Administration Django > Utilisateurs` ;
2. ne pas cocher « statut équipe » ;
3. rattacher ce compte à la fiche du salarié via le champ « compte de connexion ».

## Compte maître indépendant

Un superutilisateur Django est traité comme un **compte maître**. Il peut se connecter et accéder à toute l'application même s'il n'est associé à aucune fiche salarié.

Création locale :

```bash
python manage.py createsuperuser
```

Les comptes ordinaires, y compris ceux créés manuellement dans Django, doivent en revanche être associés à une fiche salarié. Sans cette association, l'accès métier est refusé. Cette règle évite qu'un compte oublié contourne les rôles définis dans Animation Manager.

## Interface Salariés

La rubrique Salariés utilise désormais une vue maître/détail unique :

- liste verticale compacte à gauche ;
- fiche éditable à droite sans changement de page ;
- rubriques Fiche, Affectations, Accès et Disponibilités ;
- création, modification et suppression directement dans le panneau droit ;
- les anciennes URL `/employes/<id>/` et `/employes/nouveau/` redirigent vers cette vue ;
- l’ancien template autonome `employe_detail.html` a été supprimé.

## Équivalences directionnelles des qualifications

Dans **Gestion > Qualifications**, chaque relation peut désormais être configurée avec un sens précis :

- `A → B` : un salarié possédant A couvre aussi un besoin B ;
- `B → A` : le sens inverse uniquement ;
- `A ↔ B` : équivalence dans les deux sens.

Les règles restent transitives pour le remplissage automatique. Les anciennes équivalences sont migrées automatiquement en double sens.

## Envoi d’e-mails directement depuis le site

Le module de la fiche salarié utilise uniquement l’e-mail. Il n’ouvre aucun logiciel externe : Django envoie le message par SMTP et conserve le résultat dans l’historique commun des e-mails.

Les pièces jointes sont facultatives. Elles proviennent de la bibliothèque de documents de l’application.

Pour un envoi réel sur Render, renseigner les variables d’environnement SMTP fournies par la messagerie de l’association ou par un service disposant d’une offre gratuite :

```env
EMAIL_HOST=smtp.exemple.fr
EMAIL_PORT=587
EMAIL_HOST_USER=adresse@exemple.fr
EMAIL_HOST_PASSWORD=mot_de_passe_ou_cle_smtp
EMAIL_USE_TLS=True
EMAIL_USE_SSL=False
DEFAULT_FROM_EMAIL=AJS <adresse@exemple.fr>
EMAIL_REPLY_TO=adresse@exemple.fr
```

Sans `EMAIL_HOST`, le projet local reste en mode de test et aucun message réel n’est remis au destinataire.

## Modèles d’e-mails et variables

Aucun modèle n’est créé automatiquement. Les utilisateurs de direction créent leurs propres modèles depuis **Administration → E-mails → Modèles**. Un modèle peut être modifié, désactivé temporairement ou supprimé depuis cette interface. Les modèles actifs sont proposés dans l’envoi groupé et dans l’onglet E-mail de chaque fiche salarié.

Variables automatiquement remplacées pour chaque destinataire :

- `{{prenom}}`, `{{nom}}`, `{{nom_complet}}` ;
- `{{email}}`, `{{telephone}}` ;
- `{{centre_prefere}}`, `{{centres}}` ;
- `{{qualifications}}` ;
- `{{date_du_jour}}`.

La migration `0043_supprimer_modeles_email_exemples` retire les anciens exemples éventuellement déjà installés. Les textes personnalisés réellement envoyés sont conservés dans l’historique individuel.


## Variables de planning dans les modèles d’e-mail

Les modèles d’e-mail peuvent utiliser la semaine choisie au moment de l’envoi.
Variables principales : `{{planning_semaine}}`, `{{affectation_lundi}}` à
`{{affectation_dimanche}}`, `{{lieu_lundi}}`, `{{groupe_lundi}}`, ainsi que
`{{semaine_du}}` et `{{semaine_au}}`. Chaque destinataire reçoit ses propres
affectations enregistrées dans le planning.
