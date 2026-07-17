"""
Modèles de données de l'application "animateurs".

Vue d'ensemble des tables et de leurs relations :

    Qualification <---M2M--- Animateur ---FK---> PreferenceCentre <---FK--- Centre
                                  |                                            |
                                  +-----------FK--- Disponibilite              |
                                  |                                            +---FK---> Evenement
                                  +-----------FK--- Affectation ----FK---------+
                                                            +---FK---> Evenement

- Un Animateur a des Qualifications (ManyToMany direct, pas de table
  intermédiaire explicite car on n'a pas besoin d'infos en plus comme
  une date d'obtention).
- PreferenceCentre relie un Animateur à son centre préféré et à ses
  centres secondaires. Le nom historique du modèle est conservé pour ne pas
  casser la table existante.
- Disponibilite : plages de dates où un animateur est disponible pour
  travailler. Voir la docstring du modèle plus bas pour la règle
  "par défaut disponible" appliquée quand il n'y a aucune plage.
- Evenement : nom technique historique du modèle « Groupe » rattaché à un
  lieu (ex. Maternelles, Élémentaires, séjour ou renfort).
- Affectation : LE planning à proprement parler. Une ligne = un
  animateur travaille dans un groupe (et donc dans son centre) entre
  deux dates. Le champ `centre` est conservé temporairement pour ne pas
  casser les écrans et API existants pendant la migration progressive.
"""

import re
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


def jours_ouverts_par_defaut():
    """Jours ouverts par défaut : du lundi au samedi (weekday Python 0 à 5)."""
    return [0, 1, 2, 3, 4, 5]



ANIMATEUR_COLOR_PALETTE = [
    "#2563EB", "#059669", "#DC2626", "#9333EA", "#EA580C",
    "#0891B2", "#65A30D", "#DB2777", "#4F46E5", "#D97706",
    "#0F766E", "#BE123C", "#7C3AED", "#0284C7", "#16A34A",
    "#C2410C", "#A21CAF", "#0369A1", "#15803D", "#B91C1C",
]


def _date_paques(annee):
    """Retourne le dimanche de Pâques (calendrier grégorien)."""
    a = annee % 19
    b = annee // 100
    c = annee % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    correction_dimanche = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * correction_dimanche) // 451
    mois = (h + correction_dimanche - 7 * m + 114) // 31
    jour = ((h + correction_dimanche - 7 * m + 114) % 31) + 1
    from datetime import date
    return date(annee, mois, jour)


def jours_feries_france(annee):
    """Jours fériés nationaux métropolitains pour une année."""
    from datetime import date
    paques = _date_paques(annee)
    return {
        date(annee, 1, 1),
        paques + timedelta(days=1),
        date(annee, 5, 1),
        date(annee, 5, 8),
        paques + timedelta(days=39),
        paques + timedelta(days=50),
        date(annee, 7, 14),
        date(annee, 8, 15),
        date(annee, 11, 1),
        date(annee, 11, 11),
        date(annee, 12, 25),
    }


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
    """Un membre du groupe d'animation.

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



    evenement_preferee = models.ForeignKey(
        "Evenement", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="animateurs_preferant",
        verbose_name="groupe préféré",
    )

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

    effectif_cible = models.PositiveSmallIntegerField(default=1)

    ordre = models.PositiveSmallIntegerField(
        default=0,
        help_text="Ordre d’affichage des lieux sur la page planning.",
    )

    class Meta:
        ordering = ["ordre", "nom"]

    def __str__(self):
        return self.nom


class Evenement(models.Model):
    """Un groupe organisé dans un lieu, éventuellement rattaché à des périodes prédéfinies."""

    centre = models.ForeignKey(
        Centre,
        on_delete=models.CASCADE,
        related_name="evenements",
        verbose_name="lieu",
    )
    nom = models.CharField(max_length=100)
    periodes_scolaires = models.ManyToManyField(
        "PeriodeScolaire",
        related_name="groupes",
        blank=True,
        verbose_name="périodes",
    )
    ferme_jours_feries = models.BooleanField(
        default=True,
        verbose_name="fermé les jours fériés",
    )
    debut = models.DateField(null=True, blank=True, help_text="Premier jour du groupe")
    fin = models.DateField(null=True, blank=True, help_text="Dernier jour du groupe inclus")
    effectif_cible = models.PositiveSmallIntegerField(
        default=1,
        help_text="Nombre de personnes nécessaires chaque jour",
    )
    jours_ouverts = models.JSONField(
        default=jours_ouverts_par_defaut,
        help_text="Jours habituels d’ouverture, de 0=lundi à 6=dimanche.",
    )
    qualifications_requises = models.ManyToManyField(
        Qualification,
        through="BesoinQualification",
        related_name="evenements_requerants",
        blank=True,
    )
    ordre = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "groupe"
        verbose_name_plural = "groupes"
        ordering = ["centre__nom", "ordre", "nom"]
        constraints = [
            models.UniqueConstraint(
                fields=["centre", "nom", "debut", "fin"],
                name="unique_evenement_lieu_periode",
            ),
            models.CheckConstraint(
                condition=models.Q(debut__isnull=True) | models.Q(fin__isnull=True) | models.Q(fin__gte=models.F("debut")),
                name="evenement_fin_apres_debut",
            ),
        ]

    def clean(self):
        super().clean()
        if self.fin and self.debut and self.fin < self.debut:
            raise ValidationError("La date de fin doit être postérieure ou égale à la date de début.")
        try:
            jours = sorted({int(numero) for numero in (self.jours_ouverts or [])})
        except (TypeError, ValueError):
            raise ValidationError({"jours_ouverts": "Les jours d’ouverture sont invalides."})
        if not jours or any(numero < 0 or numero > 6 for numero in jours):
            raise ValidationError({"jours_ouverts": "Choisis au moins un jour d’ouverture valide."})
        self.jours_ouverts = jours

    def fin_ouverture_periode(self, periode):
        """Dernier jour réellement utilisable pour une période.

        Les périodes scolaires importées vont volontairement du lundi au
        vendredi. Si le groupe ouvre le samedi ou le dimanche, ces jours qui
        suivent immédiatement la semaine doivent néanmoins être accessibles.
        """
        jours = {int(numero) for numero in (self.jours_ouverts or [])}
        extension = 2 if 6 in jours else (1 if 5 in jours else 0)
        return periode.fin + timedelta(days=extension)

    def est_ouvert_le(self, jour, dates_exclues=None):
        """Indique si le groupe est ouvert à cette date.

        Sans période sélectionnée, le groupe existe dans Gestion mais ne doit
        apparaître ni dans les calendriers ni dans le remplissage automatique.
        """
        periodes = list(self.periodes_scolaires.all())
        if not periodes:
            return False
        if not any(periode.debut <= jour <= self.fin_ouverture_periode(periode) for periode in periodes):
            return False
        if jour.weekday() not in {int(numero) for numero in (self.jours_ouverts or [])}:
            return False
        if self.ferme_jours_feries and jour in jours_feries_france(jour.year):
            return False
        if dates_exclues is None:
            dates_exclues = set(self.dates_exclues.values_list("date", flat=True))
        return jour not in dates_exclues

    def __str__(self):
        return f"{self.centre.nom} — {self.nom}"


class DateExclueEvenement(models.Model):
    """Une fermeture ponctuelle à l’intérieur de la période d’un groupe."""

    evenement = models.ForeignKey(
        Evenement,
        on_delete=models.CASCADE,
        related_name="dates_exclues",
        verbose_name="groupe",
    )
    date = models.DateField()
    motif = models.CharField(max_length=120, blank=True, default="")

    class Meta:
        ordering = ["date"]
        constraints = [
            models.UniqueConstraint(
                fields=["evenement", "date"],
                name="unique_date_exclue_evenement",
            ),
        ]

    def clean(self):
        super().clean()
        if self.evenement.debut and self.date < self.evenement.debut:
            raise ValidationError("La date exclue doit appartenir à la période du groupe.")
        if self.evenement.fin and self.date > self.evenement.fin:
            raise ValidationError("La date exclue doit appartenir à la période du groupe.")

    def __str__(self):
        return f"{self.evenement} fermé le {self.date:%d/%m/%Y}"


class BesoinQualification(models.Model):
    """Nombre minimal de titulaires d’une qualification pour un groupe."""

    evenement = models.ForeignKey(
        Evenement,
        on_delete=models.CASCADE,
        related_name="besoins_qualifications",
        verbose_name="groupe",
    )
    qualification = models.ForeignKey(Qualification, on_delete=models.CASCADE)
    nombre_minimum = models.PositiveSmallIntegerField(default=1)

    class Meta:
        ordering = ["qualification__nom"]
        constraints = [
            models.UniqueConstraint(
                fields=["evenement", "qualification"],
                name="unique_besoin_qualification_evenement",
            ),
        ]

    def __str__(self):
        return f"{self.evenement} : {self.nombre_minimum} × {self.qualification}"


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


class PeriodeScolaire(models.Model):
    """Semaine de vacances importée et sélectionnable par les groupes.

    Les dates restent centralisées dans cette bibliothèque : un groupe ne
    saisit pas ses propres bornes et peut simplement référencer zéro, une ou
    plusieurs périodes.
    """

    ZONES = [("A", "Zone A"), ("B", "Zone B"), ("C", "Zone C")]

    nom = models.CharField(max_length=140)
    annee_scolaire = models.CharField(max_length=9, help_text="Ex. 2026-2027")
    zone = models.CharField(max_length=1, choices=ZONES)
    debut = models.DateField()
    fin = models.DateField()
    description_source = models.CharField(max_length=180, blank=True, default="")
    ordre = models.PositiveSmallIntegerField(default=0)
    date_import = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-annee_scolaire", "zone", "debut", "ordre", "nom"]
        constraints = [
            models.UniqueConstraint(
                fields=["annee_scolaire", "zone", "debut", "fin"],
                name="unique_periode_scolaire_zone_dates",
            ),
            models.CheckConstraint(
                condition=models.Q(fin__gte=models.F("debut")),
                name="periode_scolaire_fin_apres_debut",
            ),
        ]

    def clean(self):
        super().clean()
        if not re.fullmatch(r"\d{4}-\d{4}", self.annee_scolaire or ""):
            raise ValidationError({"annee_scolaire": "Utilise le format 2026-2027."})
        premiere, seconde = map(int, self.annee_scolaire.split("-"))
        if seconde != premiere + 1:
            raise ValidationError({"annee_scolaire": "Les années doivent être consécutives."})
        if self.fin < self.debut:
            raise ValidationError({"fin": "La date de fin doit suivre la date de début."})
        if self.debut.weekday() != 0 or self.fin.weekday() != 4:
            raise ValidationError("Une période importée doit aller du lundi au vendredi.")

    @property
    def libelle_avec_annee(self):
        """Nom court non ambigu, par exemple « Été 2026 — Semaine 2 »."""
        annee = str(self.debut.year)
        separateur = " — Semaine "
        if annee in self.nom:
            return self.nom
        if separateur in self.nom:
            return self.nom.replace(separateur, f" {annee}{separateur}")
        return f"{self.nom} {annee}"

    def __str__(self):
        return f"{self.libelle_avec_annee} ({self.debut:%d/%m/%Y} au {self.fin:%d/%m/%Y})"


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
                condition=models.Q(debut__isnull=True) | models.Q(fin__isnull=True) | models.Q(fin__gte=models.F("debut")),
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

    Chaque affectation correspond à une ou plusieurs journées entières. Une même ligne sert à la fois de planning prévisionnel (dates
    futures) et d'historique (dates passées) : il n'y a pas de
    distinction de table entre les deux, seule la date compte pour
    savoir si c'est "à venir" ou "déjà travaillé" (voir la page
    Récapitulatif, qui fait cette distinction à la volée).

    Deux règles métier sont imposées par le service
    ``services/affectations.py`` avant la sauvegarde :
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
        Centre, on_delete=models.CASCADE, related_name="affectations"
    )
    evenement = models.ForeignKey(
        Evenement,
        on_delete=models.PROTECT,
        related_name="affectations",
        verbose_name="groupe",
    )
    debut = models.DateTimeField()
    fin = models.DateTimeField()

    class Meta:
        ordering = ["debut"]
        indexes = [
            models.Index(fields=["centre", "debut"], name="aff_centre_debut_idx"),
            models.Index(fields=["evenement", "debut"], name="aff_evenement_debut_idx"),
            models.Index(fields=["animateur", "debut"], name="aff_anim_debut_idx"),
            models.Index(fields=["debut", "fin"], name="aff_periode_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(fin__gt=models.F("debut")),
                name="affectation_fin_apres_debut",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.evenement_id:
            self.centre_id = self.evenement.centre_id
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.animateur} @ {self.evenement} ({self.debut:%d/%m/%Y})"


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


class EnvoiEmail(models.Model):
    """Historique d'un envoi groupé réalisé depuis la bibliothèque."""

    objet = models.CharField(max_length=200)
    message = models.TextField()
    documents = models.ManyToManyField(Document, related_name="envois_email", blank=True)
    documents_titres = models.JSONField(
        default=list,
        help_text="Copie des titres au moment de l’envoi, conservée si un document est supprimé.",
    )
    date_creation = models.DateTimeField(auto_now_add=True)
    nombre_destinataires = models.PositiveIntegerField(default=0)
    nombre_envoyes = models.PositiveIntegerField(default=0)
    nombre_echecs = models.PositiveIntegerField(default=0)
    mode_test = models.BooleanField(default=False)

    class Meta:
        ordering = ["-date_creation"]

    def __str__(self):
        return f"{self.objet} ({self.date_creation:%d/%m/%Y %H:%M})"


class DestinataireEnvoiEmail(models.Model):
    """Résultat individuel conservé même si le salarié est supprimé ensuite."""

    STATUT_ENVOYE = "envoye"
    STATUT_ECHEC = "echec"
    STATUTS = [
        (STATUT_ENVOYE, "Envoyé"),
        (STATUT_ECHEC, "Échec"),
    ]

    envoi = models.ForeignKey(
        EnvoiEmail,
        on_delete=models.CASCADE,
        related_name="destinataires",
    )
    animateur = models.ForeignKey(
        Animateur,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="emails_recus",
    )
    prenom = models.CharField(max_length=100)
    nom = models.CharField(max_length=100)
    email = models.EmailField()
    statut = models.CharField(max_length=10, choices=STATUTS)
    erreur = models.TextField(blank=True, default="")
    date_traitement = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["prenom", "nom", "email"]
        constraints = [
            models.UniqueConstraint(
                fields=["envoi", "email"],
                name="unique_destinataire_par_envoi_email",
            ),
        ]

    def __str__(self):
        return f"{self.prenom} {self.nom} — {self.get_statut_display()}"
