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
- PreferenceCentre relie un Animateur à son centre préféré et à ses
  centres secondaires. Le nom historique du modèle est conservé pour ne pas
  casser la table existante.
- Disponibilite : plages de dates où un animateur est disponible pour
  travailler. Voir la docstring du modèle plus bas pour la règle
  "par défaut disponible" appliquée quand il n'y a aucune plage.
- Affectation : LE planning à proprement parler. Une ligne = un
  animateur travaille dans un centre entre deux dates. C'est cette même
  table qui sert à la fois de planning prévisionnel (dates futures) et
  d'historique (dates passées) : pas de distinction de table entre les
  deux, seule la date compte.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


ANIMATEUR_COLOR_PALETTE = [
    "#2563EB", "#059669", "#DC2626", "#9333EA", "#EA580C",
    "#0891B2", "#65A30D", "#DB2777", "#4F46E5", "#D97706",
    "#0F766E", "#BE123C", "#7C3AED", "#0284C7", "#16A34A",
    "#C2410C", "#A21CAF", "#0369A1", "#15803D", "#B91C1C",
]


class Qualification(models.Model):
    """Un diplôme/une compétence qu'un animateur peut avoir (ex: BAFA,
    permis B, PSC1...). Purement déclaratif pour l’instant."""

    nom = models.CharField(max_length=100)
    selectionnable_remplissage_auto = models.BooleanField(
        default=False,
        help_text="Affiche cette qualification parmi les exigences du remplissage automatique.",
    )

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

    couleur = models.CharField(
        max_length=7,
        blank=True,
        default="",
        help_text="Couleur hexadécimale fixe utilisée dans le planning.",
    )

    # ManyToMany "simple" (pas de table intermédiaire personnalisée) car
    # on n'a besoin d'aucune information supplémentaire sur la relation
    # elle-même.
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

    def save(self, *args, **kwargs):
        """Attribue une couleur lisible et stable si aucune n'est définie."""
        if not self.couleur:
            couleurs_utilisees = set(
                Animateur.objects.exclude(pk=self.pk).exclude(couleur="")
                .values_list("couleur", flat=True)
            )
            self.couleur = next(
                (couleur for couleur in ANIMATEUR_COLOR_PALETTE if couleur not in couleurs_utilisees),
                ANIMATEUR_COLOR_PALETTE[Animateur.objects.count() % len(ANIMATEUR_COLOR_PALETTE)],
            )
        super().save(*args, **kwargs)

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
    """Lien entre un animateur et un centre où il peut être affecté.

    Une relation peut être marquée comme centre préféré. Les autres
    relations sont des centres secondaires. Un animateur ne peut avoir
    qu'un seul centre préféré, mais plusieurs centres secondaires.
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
    est_prefere = models.BooleanField(
        default=False,
        help_text="Centre principal à privilégier lors du remplissage automatique.",
    )

    class Meta:
        ordering = ["-est_prefere", "centre__nom"]
        constraints = [
            # Un animateur ne peut pas avoir deux fois le même centre
            # dans ses centres autorisés.
            models.UniqueConstraint(
                fields=["animateur", "centre"],
                name="unique_animateur_centre",
            ),
            models.UniqueConstraint(
                fields=["animateur"],
                condition=models.Q(est_prefere=True),
                name="unique_centre_prefere_par_animateur",
            ),
        ]

    def __str__(self):
        type_centre = "centre préféré" if self.est_prefere else "centre secondaire"
        return f"{self.animateur} - {type_centre} : {self.centre}"


class Disponibilite(models.Model):
    """Une plage de dates (bornes incluses) où un animateur est
    disponible pour travailler.

    Règle métier : un animateur qui n'a AUCUNE ligne Disponibilite est
    considéré indisponible. Une affectation n'est autorisée que lorsque
    chaque jour concerné est couvert par au moins une plage renseignée.

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
        indexes = [
            models.Index(fields=["animateur", "debut", "fin"], name="dispo_anim_dates_idx"),
        ]
        constraints = [
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
        indexes = [
            models.Index(fields=["centre", "debut"], name="aff_centre_debut_idx"),
            models.Index(fields=["animateur", "debut"], name="aff_anim_debut_idx"),
            models.Index(fields=["debut", "fin"], name="aff_periode_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(fin__gt=models.F("debut")),
                name="affectation_fin_apres_debut",
            ),
        ]

    def __str__(self):
        return f"{self.animateur} @ {self.centre} ({self.debut:%d/%m/%Y})"


class Document(models.Model):
    """Un document administratif consultable depuis l'application.

    Un document est soit permanent, soit rattaché à une période précise.
    Les dates sont inclusives. Les anciens documents sont considérés comme
    permanents afin de préserver les données existantes.
    """

    titre = models.CharField(max_length=150)
    fichier = models.FileField(upload_to="documents/")
    permanent = models.BooleanField(
        default=True,
        help_text="Cocher si le document n'est lié à aucune période précise.",
    )
    periode_debut = models.DateField(null=True, blank=True)
    periode_fin = models.DateField(null=True, blank=True)
    date_ajout = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-permanent", "-periode_debut", "-date_ajout"]
        indexes = [
            models.Index(fields=["permanent", "periode_debut", "periode_fin"], name="document_periode_idx"),
        ]

    def clean(self):
        super().clean()
        if self.permanent:
            self.periode_debut = None
            self.periode_fin = None
            return

        if not self.periode_debut or not self.periode_fin:
            raise ValidationError("Une période complète est obligatoire pour un document non permanent.")
        if self.periode_fin < self.periode_debut:
            raise ValidationError("La date de fin doit être postérieure ou égale à la date de début.")

    @property
    def libelle_periode(self):
        if self.permanent:
            return "Permanent"
        if self.periode_debut and self.periode_fin:
            return f"Du {self.periode_debut:%d/%m/%Y} au {self.periode_fin:%d/%m/%Y}"
        return "Période non renseignée"

    def __str__(self):
        return self.titre
