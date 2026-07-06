"""
Modèles de données de l'application "animateurs".

Vue d'ensemble des tables et de leurs relations :

    Qualification <---M2M--- Animateur ---FK---> PreferenceCentre <---FK--- Centre
                                  |                                            |
                                  +-----------FK--- Disponibilite              |
                                  |                                            |
                                  +-----------FK--- Affectation ----FK---------+

- Un Animateur a des Qualifications (ManyToMany direct, pas de table
  intermédiaire explicite car on n'a pas besoin d'infos en plus comme
  une date d'obtention).
- PreferenceCentre relie un Animateur à un Centre avec un ordre de
  préférence (1 = préféré). Table intermédiaire explicite (et non un
  simple ManyToMany) car on a besoin de stocker cet ordre.
- Disponibilite : plages de dates où un animateur est disponible pour
  travailler. Voir la docstring du modèle plus bas pour la règle
  "par défaut disponible" appliquée quand il n'y a aucune plage.
- Affectation : LE planning à proprement parler. Une ligne = un
  animateur travaille dans un centre entre deux dates. C'est cette même
  table qui sert à la fois de planning prévisionnel (dates futures) et
  d'historique (dates passées) : pas de distinction de table entre les
  deux, seule la date compte.
"""

from django.db import models
from django.utils import timezone


class Qualification(models.Model):
    """Un diplôme/une compétence qu'un animateur peut avoir (ex: BAFA,
    permis B, PSC1...). Purement déclaratif pour l’instant."""

    nom = models.CharField(max_length=100)

    def __str__(self):
        return self.nom


class Animateur(models.Model):
    """Un membre de l'équipe d'animation.

    Les coordonnées et la date de naissance sont optionnelles pour ne pas
    bloquer les animateurs déjà créés avant l'ajout de ces champs. L'âge
    n'est pas stocké en base : il est calculé à la volée depuis
    `date_naissance`, ce qui évite d'avoir une valeur périmée chaque année.
    """

    prenom = models.CharField(max_length=100)
    nom = models.CharField(max_length=100)

    telephone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    date_naissance = models.DateField(null=True, blank=True)

    # ManyToMany "simple" (pas de table intermédiaire personnalisée) car
    # on n'a besoin d'aucune information supplémentaire sur la relation
    # elle-même (contrairement à PreferenceCentre qui a un `ordre`).
    qualifications = models.ManyToManyField(Qualification, blank=True)

    @property
    def age(self):
        """Âge actuel de l'animateur, calculé depuis sa date de naissance."""

        if not self.date_naissance:
            return None

        today = timezone.now().date()
        age = today.year - self.date_naissance.year

        # Si l'anniversaire n'est pas encore passé cette année, on retire 1.
        if (today.month, today.day) < (self.date_naissance.month, self.date_naissance.day):
            age -= 1

        return age

    def __str__(self):
        return f"{self.prenom} {self.nom}"


class Centre(models.Model):
    """Un centre d'animation (ex: Pacaudière, Saint-Forgeux...). Chaque
    centre a son propre calendrier sur la page planning."""

    nom = models.CharField(max_length=100)

    code = models.CharField(
        max_length=10,
        unique=True,
        help_text="Abréviation courte affichée dans les badges, ex: PAC",
    )

    couleur = models.CharField(
        max_length=7,
        default="#e03c00",
        help_text="Couleur hexadécimale utilisée pour les badges, ex: #e03c00",
    )

    effectif_cible = models.PositiveSmallIntegerField(
        default=1,
        help_text="Nombre d'animateurs souhaités par jour dans ce centre",
    )

    class Meta:
        ordering = ["nom"]

    def __str__(self):
        return self.nom


class PreferenceCentre(models.Model):
    """Table intermédiaire explicite entre Animateur et Centre : indique
    l'ordre de préférence d'un animateur pour un centre donné (1 =
    centre préféré, 2 = deuxième choix, etc.).

    Utilisée pour afficher les badges numérotés à côté du nom de
    l'animateur dans le planning et aider visuellement au choix manuel.
    """

    animateur = models.ForeignKey(
        Animateur,
        on_delete=models.CASCADE,
        related_name="preferences",
    )
    centre = models.ForeignKey(
        Centre,
        on_delete=models.CASCADE,
        related_name="preferences",
    )
    ordre = models.PositiveSmallIntegerField(
        help_text="1 = centre préféré",
    )

    class Meta:
        ordering = ["ordre"]
        constraints = [
            # Un animateur ne peut pas avoir deux fois le même centre
            # dans ses préférences...
            models.UniqueConstraint(
                fields=["animateur", "centre"],
                name="unique_animateur_centre",
            ),
            # ... ni deux centres au même rang de préférence (ex: deux
            # centres classés tous les deux "1").
            models.UniqueConstraint(
                fields=["animateur", "ordre"],
                name="unique_animateur_ordre",
            ),
        ]

    def __str__(self):
        return f"{self.animateur} - {self.ordre}. {self.centre}"


class Disponibilite(models.Model):
    """Une plage de dates (bornes incluses) où un animateur est
    disponible pour travailler.

    Règle importante appliquée côté vues (voir _animateur_disponible
    dans views.py) : un animateur qui n'a AUCUNE ligne Disponibilite est
    considéré disponible tout le temps (pas de contrainte tant que
    l'information n'a pas été saisie). Dès qu'il a au moins une plage,
    seuls les jours couverts par une de ses plages sont autorisés.

    On utilise des plages (debut/fin) plutôt qu'une ligne par jour :
    plus rapide à saisir dans l'admin (ex: "disponible du 6 au 20
    juillet" en une seule ligne plutôt que 15 lignes).
    """

    animateur = models.ForeignKey(
        Animateur,
        on_delete=models.CASCADE,
        related_name="disponibilites",
    )
    debut = models.DateField(help_text="Premier jour de disponibilité")
    fin = models.DateField(help_text="Dernier jour de disponibilité (inclus)")

    class Meta:
        ordering = ["debut"]
        constraints = [
            # Empêche de saisir une plage à l'envers (fin avant début).
            models.CheckConstraint(
                condition=models.Q(fin__gte=models.F("debut")),
                name="dispo_fin_apres_debut",
            ),
        ]

    def __str__(self):
        return f"{self.animateur} disponible du {self.debut:%d/%m/%Y} au {self.fin:%d/%m/%Y}"


class Affectation(models.Model):
    """Le planning proprement dit : un animateur travaille dans un
    centre entre `debut` (inclus) et `fin` (exclu, convention "allDay"
    de FullCalendar : une affectation d'une seule journée a
    fin = debut + 1 jour).

    Une même ligne sert à la fois de planning prévisionnel (dates
    futures) et d'historique (dates passées) : il n'y a pas de
    distinction de table entre les deux, seule la date compte pour
    savoir si c'est "à venir" ou "déjà travaillé" (voir la page
    Récapitulatif, qui fait cette distinction à la volée).

    Deux règles métier sont imposées AVANT la sauvegarde (voir
    _valider_affectation dans views.py, PAS de contrainte au niveau du
    modèle ici) :
      1. un animateur ne peut pas avoir deux affectations qui se
         chevauchent le même jour, même dans deux centres différents ;
      2. il doit être disponible sur toute la période couverte.
    """

    animateur = models.ForeignKey(
        Animateur,
        on_delete=models.CASCADE,
        related_name="affectations",
    )
    centre = models.ForeignKey(
        Centre,
        on_delete=models.CASCADE,
        related_name="affectations",
    )
    debut = models.DateTimeField()
    fin = models.DateTimeField()

    class Meta:
        ordering = ["debut"]

    def __str__(self):
        return f"{self.animateur} @ {self.centre} ({self.debut:%d/%m/%Y})"


class Document(models.Model):
    """Un document administratif (contrat, planning imprimé, etc.)
    consultable depuis la page /documents/."""

    titre = models.CharField(max_length=150)
    fichier = models.FileField(upload_to="documents/")
    date_ajout = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.titre
