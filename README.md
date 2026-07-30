# Animation Manager

Application Django de gestion des salariés, lieux, groupes, périodes scolaires, disponibilités, documents et plannings journaliers.

## Installation locale

La commande suivante crée `.venv`, installe les dépendances de développement,
crée `.env` si nécessaire et applique les migrations :

```bash
make install
source .venv/bin/activate
make run
```

Installation manuelle équivalente :

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
cp .env.example .env
python manage.py migrate
python manage.py runserver
```

Sans variables `DB_*`, l'application crée une base SQLite locale. Cette base
n'est pas versionnée. En production, renseigner `DB_HOST`, `DB_PORT`, `DB_NAME`,
`DB_USER` et `DB_PASSWORD` pour PostgreSQL/Supabase.

## Vérifications

```bash
make check     # audit statique + contrôles Django
make test      # suite Django
make lint      # Ruff
make verify    # tous les contrôles disponibles
```

`scripts/static_audit.py` ne dépend d'aucun paquet externe. Il contrôle la
syntaxe Python, les références de templates et de fichiers statiques, la façade
des vues, les migrations et, lorsqu'elle existe, l'intégrité de SQLite.

## Déploiement Render

La commande de build est contenue dans `build.sh`. La commande de démarrage recommandée est :

```bash
gunicorn config.wsgi:application
```

Définir impérativement `SECRET_KEY`, `DEBUG=False`, `ALLOWED_HOSTS` et les variables de base de données. Les fichiers utilisateurs doivent être stockés dans Supabase Storage en production.

### Estimation des trajets des sorties

L'estimation automatique utilise les services publics de la Géoplateforme IGN
côté serveur. Aucune clé API n'est nécessaire. Les valeurs suivantes peuvent
être conservées dans les variables d'environnement Render :

```text
ROUTING_PROVIDER=geoplateforme
ROUTING_API_URL=https://data.geopf.fr/navigation/itineraire
ROUTING_GEOCODING_URL=https://data.geopf.fr/geocodage/search
ROUTING_RESOURCE=bdtopo-osrm
ROUTING_TIMEOUT_SECONDS=8
```

Les itinéraires et le géocodage sont mis en cache afin de limiter les requêtes.
Le calcul utilise le réseau routier BD TOPO de l'IGN et respecte l'ordre des
lieux enregistré dans la sortie. Si le service public est momentanément
indisponible, les heures d'arrivée restent saisissables manuellement.

### Localisation des sorties

La destination d'une sortie est enregistrée sous forme structurée : nom,
adresse ou lieu-dit facultatif, code postal, commune, code INSEE, coordonnées
et niveau de précision. L'autocomplétion commune/code postal passe par l'API
publique officielle `geo.api.gouv.fr` via Django ; aucune clé ni donnée secrète
n'est envoyée au navigateur. Le géocodage précis utilise le service de
géocodage de la Géoplateforme. Les recherches sont mises en cache et une panne
externe n'empêche jamais l'enregistrement manuel de la sortie.

La météo et l'itinéraire consomment les mêmes coordonnées de destination. Les
anciens champs météo restent présents pour compatibilité de schéma, mais ne
sont plus utilisés comme une seconde localisation modifiable.

Les lieux de Gestion utilisent le même composant commune/code postal et le
même service de géocodage. Leurs coordonnées sont enregistrées avec le code
INSEE et le niveau de précision, puis reprises directement par les étapes des
circuits aller et retour. En cas d'échec, l'API Transport renvoie un code métier
(`ROUTING_NOT_CONFIGURED`, `LOCATION_MISSING`, `GEOCODING_FAILED`,
`ROUTING_FAILED`, `INVALID_ROUTE` ou `PROVIDER_TIMEOUT`) sans exposer la clé ni
la réponse technique du fournisseur.

## Organisation

- `animateurs/models.py` : modèle de données actuel ;
- `animateurs/services/` : règles métier et exports ;
- `animateurs/views.py` : façade stable utilisée par les routes ;
- `animateurs/views_pages.py` : pages, administration et exports ;
- `animateurs/views_staff.py` : salariés et disponibilités ;
- `animateurs/views_planning.py` : planning et affectations ;
- `animateurs/views_catalogue.py` : centres, groupes, qualifications et périodes ;
- `animateurs/views_reporting.py` : documents et récapitulatif ;
- `animateurs/views_communications.py`, `views_effectifs.py` et `views_sorties.py` : domaines déjà séparés ;
- `static/js/` : interfaces clientes ;
- `scripts/` : installation et contrôles reproductibles ;
- `animateurs/tests/` : tests correspondant au modèle actuel. Les tests HTTP
  héritent de `animateurs/tests/base.py` (`ConnexionTestCase`), qui connecte
  automatiquement un compte maître pour traverser l'authentification obligatoire.

## Comptes animateurs et droits d'accès

Chaque salarié peut être relié à un compte Django depuis sa fiche dans l'administration Django (`Animateurs > Animateurs > compte de connexion`).

- Un compte de direction doit être **superutilisateur**. Il conserve l'accès à toutes les pages et fonctions.
- Un compte animateur est un compte ordinaire relié à une fiche salarié. Il accède uniquement à l'accueil en lecture seule, aux documents partagés et à la saisie de ses propres disponibilités.
- La page de connexion est `/connexion/`.

Pour créer un accès animateur :
1. créer l'utilisateur dans `Administration Django > Utilisateurs` ;
2. ne pas lui attribuer le statut superutilisateur ;
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

## Interface pastel unifiée

Toutes les pages utilisent désormais le même langage visuel que le tableau de bord :

- barre latérale persistante sur ordinateur et menu coulissant sur petit écran ;
- palette pastel violette, cartes blanches, bordures légères et ombres discrètes ;
- titres, onglets, boutons, formulaires et tableaux harmonisés ;
- en-têtes explicites pour Planning, Salariés, Gestion, Récapitulatif et Administration ;
- espaces de travail adaptés à leur usage : Planning dense, Salariés en maître/détail, Gestion en cartes par lieu et Administration organisée par outils ;
- mise en page responsive conservant l'accès à toutes les fonctions sur tablette et mobile.

Les fondations et composants communs se trouvent dans `static/css/common-base.css` et `static/css/common-ui.css`. Les pages ne chargent ensuite que leur feuille spécialisée. Les en-têtes de pages et la navigation de semaine sont rendus par les partials communs de `templates/partials/`, et toutes les ressources statiques utilisent la même variable `ASSET_VERSION`.

## Disposition modulable des centres dans le Planning

Le menu compact **Centres** permet de rouvrir un centre précédemment fermé. Chaque carte peut être déplacée depuis sa poignée : les centres déposés sur une même ligne se partagent automatiquement toute la largeur disponible, tandis qu'un dépôt entre deux lignes crée une nouvelle rangée. Les calendriers conservent une hauteur utile pour les affectations ; le Planning défile uniquement vers le bas et ne crée jamais de défilement horizontal. La disposition reste mémorisée dans le navigateur sans modifier l'ordre métier enregistré dans Gestion.

## Navigation réorganisée

Le menu de direction est regroupé par usage :

- **Pilotage** : Tableau de bord, Planning, Récapitulatif ;
- **Équipe** : Salariés ;
- **Organisation** : Gestion, Documents ;
- **Communication** : E-mails ;
- **Paramètres** : Administration.

Sur ordinateur, le menu ouvert réserve sa propre largeur et ne recouvre plus les pages. Il peut être replié en rail compact. Sur mobile, il reste disponible sous forme de tiroir. Les accès **Documents** et **E-mails** disposent de liens directs.


## Audit technique

Le rapport `AUDIT_NETTOYAGE.md` décrit le nettoyage du dépôt, les vérifications exécutées et les limites de la revue.
