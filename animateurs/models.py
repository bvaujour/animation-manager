"""
Modèles de données de l'application "animateurs".

Vue d'ensemble des tables et de leurs relations :

    Qualification <---M2M--- Animateur ---FK---> PreferenceCentre <---FK--- Centre
                                  |                                            |
                                  +-----------FK--- Disponibilite              |
                                  |                                            +---FK---> Evenement
                                  +-----------FK--- Affectation ----FK---------+
                                  +------FK--- AffiniteGroupeAnimateur ---FK---> Evenement
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
- AffiniteGroupeAnimateur : compteur persistant des journées terminées
  par un salarié dans chaque groupe, utilisé pour le remplissage automatique.
"""

import re
import unicodedata
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.utils import timezone


def jours_ouverts_par_defaut():
    """Jours ouverts par défaut : du lundi au samedi (weekday Python 0 à 5)."""
    return [0, 1, 2, 3, 4, 5]


QUALIFICATION_ICON_CHOICES = [
    ("", "Aucune icône"),
    ("diplome", "Diplôme / qualification"),
    ("secours", "Premiers secours"),
    ("baignade", "Surveillance baignade"),
    ("conduite", "Permis / conduite"),
    ("sport", "Sport"),
    ("direction", "Direction"),
    ("repas", "Repas / alimentation"),
]

code_postal_francais = RegexValidator(
    regex=r"^\d{5}$",
    message="Le code postal doit contenir exactement 5 chiffres.",
)

PRECISIONS_LOCALISATION = (
    ("adresse", "Adresse"),
    ("commune", "Commune"),
    ("code_postal", "Code postal"),
    ("non_localisee", "Non localisée"),
)




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


def normaliser_cle_unique(*valeurs):
    """Clé stable pour comparer les noms sans accents, casse ni espaces parasites."""
    texte = " ".join(str(v or "").strip() for v in valeurs)
    texte = unicodedata.normalize("NFKD", texte)
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    texte = texte.casefold()
    texte = re.sub(r"[^a-z0-9]+", " ", texte)
    return " ".join(texte.split())


def type_accueil_vacances_par_defaut():
    """Repli technique pour les créations hors des formulaires applicatifs."""
    return TypeAccueil.objects.only("pk").get(code=TypeAccueil.VACANCES).pk


def type_accueil_sejours_par_defaut():
    return TypeAccueil.objects.only("pk").get(code=TypeAccueil.SEJOURS).pk


class Qualification(models.Model):
    """Un diplôme/une compétence qu'un animateur peut avoir (ex: BAFA,
    permis B, PSC1...). Purement déclaratif pour l’instant."""

    nom = models.CharField(max_length=100)
    cle_unique = models.CharField(max_length=120, unique=True, editable=False)
    selectionnable_remplissage_auto = models.BooleanField(
        default=True,
        help_text="Propose ce diplôme ou statut dans les besoins du remplissage automatique.",
    )
    est_statut = models.BooleanField(
        default=False,
        help_text="Statut regroupant plusieurs diplômes (ex. Diplômé).",
    )
    statut = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        related_name="diplomes",
        null=True,
        blank=True,
        limit_choices_to={"est_statut": True},
    )
    icone = models.CharField(
        max_length=20,
        choices=QUALIFICATION_ICON_CHOICES,
        blank=True,
        default="",
        help_text="Icône facultative affichée à côté des animateurs possédant ce diplôme.",
    )

    def save(self, *args, **kwargs):
        self.nom = self.nom.strip()
        self.cle_unique = normaliser_cle_unique(self.nom)
        if self.est_statut:
            self.statut = None
            self.icone = ""
        super().save(*args, **kwargs)

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
    cle_unique = models.CharField(max_length=240, unique=True, editable=False)

    ROLE_ANIMATEUR = "animateur"
    ROLE_CHOICES = [
        (ROLE_ANIMATEUR, "Animateur"),
    ]

    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default=ROLE_ANIMATEUR,
        verbose_name="rôle dans l’application",
    )

    doit_changer_mot_de_passe = models.BooleanField(
        default=False,
        verbose_name="doit changer son mot de passe",
    )

    utilisateur = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="profil_animateur",
        verbose_name="compte de connexion",
        help_text="Compte utilisé par ce salarié pour accéder à son espace animateur.",
    )

    telephone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    date_naissance = models.DateField(null=True, blank=True)
    adresse = models.TextField(blank=True)
    numero_securite_sociale = models.CharField(
        max_length=21,
        blank=True,
        verbose_name="numéro de sécurité sociale",
        help_text="Numéro avec ou sans espaces (15 chiffres, clé comprise).",
    )
    paie_jour = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="paie par jour",
        help_text="Montant brut ou net selon la convention retenue par l'association.",
    )


    # ManyToMany "simple" (pas de table intermédiaire personnalisée) car
    # on n'a besoin d'aucune information supplémentaire sur la relation
    # elle-même.
    qualifications = models.ManyToManyField(Qualification, blank=True)

    groupes_affinite = models.ManyToManyField(
        "Evenement",
        through="AffiniteGroupeAnimateur",
        related_name="animateurs_avec_affinite",
        blank=True,
        verbose_name="affinités avec les groupes",
    )

    evenement_preferee = models.ForeignKey(
        "Evenement",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
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
        """Normalise l’identité avant enregistrement."""
        self.prenom = self.prenom.strip()
        self.nom = self.nom.strip()
        self.cle_unique = normaliser_cle_unique(self.prenom, self.nom)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.prenom} {self.nom}"


class HistoriqueStatutAnimateur(models.Model):
    """Changement daté du statut fonctionnel d'un animateur."""

    ORIGINE_MANUELLE = "manuelle"
    ORIGINE_FORMATION = "formation"
    ORIGINE_REPRISE = "reprise"
    ORIGINE_CHOICES = (
        (ORIGINE_MANUELLE, "Saisie manuelle"),
        (ORIGINE_FORMATION, "Formation"),
        (ORIGINE_REPRISE, "Reprise technique"),
    )

    animateur = models.ForeignKey(Animateur, on_delete=models.CASCADE, related_name="historique_statuts")
    statut = models.ForeignKey(
        Qualification,
        on_delete=models.PROTECT,
        related_name="historiques_statut_animateurs",
        limit_choices_to={"est_statut": True},
    )
    date_effet = models.DateField()
    origine = models.CharField(max_length=16, choices=ORIGINE_CHOICES, default=ORIGINE_MANUELLE)
    date_effet_incertaine = models.BooleanField(
        default=False,
        help_text="Vrai pour une date technique de reprise qui n'est pas une date d'obtention connue.",
    )
    commentaire = models.CharField(max_length=240, blank=True)
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-date_effet", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("animateur", "date_effet"),
                name="unique_statut_animateur_date_effet",
            )
        ]

    def clean(self):
        if self.statut_id and not self.statut.est_statut:
            raise ValidationError({"statut": "Choisissez un statut existant."})

    def save(self, *args, **kwargs):
        self.commentaire = self.commentaire.strip()
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.animateur} — {self.statut} dès le {self.date_effet:%d/%m/%Y}"


class TypeContrat(models.Model):
    """Type contractuel configurable, relié à un mode de paie connu."""

    MODE_CEE = "cee_journalier"
    MODE_MENSUALISE = "mensualise"
    MODE_APPRENTISSAGE = "apprentissage"
    MODE_PAIE_HABITUELLE = "paie_habituelle"
    MODE_CHOICES = (
        (MODE_CEE, "Journalier CEE"),
        (MODE_MENSUALISE, "Mensualisé"),
        (MODE_APPRENTISSAGE, "Apprentissage"),
        (MODE_PAIE_HABITUELLE, "Paie habituelle / hors calcul"),
    )

    structure = models.ForeignKey(
        "ParametresStructure", on_delete=models.CASCADE, related_name="types_contrats"
    )
    nom = models.CharField(max_length=100)
    code = models.SlugField(max_length=50)
    actif = models.BooleanField(default=True)
    ordre = models.PositiveSmallIntegerField(default=0)
    description = models.TextField(blank=True)
    mode_remuneration = models.CharField(max_length=24, choices=MODE_CHOICES)
    systeme = models.BooleanField(default=False)
    cree_le = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("ordre", "nom", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("structure", "code"), name="unique_type_contrat_structure_code"
            )
        ]

    def clean(self):
        self.nom = self.nom.strip()
        self.code = self.code.strip().lower()
        if not self.nom:
            raise ValidationError({"nom": "Le nom du type de contrat est obligatoire."})
        if not self.code:
            raise ValidationError({"code": "Le code du type de contrat est obligatoire."})
        if self.pk and self.systeme:
            precedent = TypeContrat.objects.filter(pk=self.pk).values_list("code", flat=True).first()
            if precedent and precedent != self.code:
                raise ValidationError({"code": "Le code stable d'un type système ne peut pas être modifié."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.systeme:
            raise ValidationError("Un type de contrat système ne peut pas être supprimé.")
        return super().delete(*args, **kwargs)

    def __str__(self):
        return self.nom


class Contrat(models.Model):
    """Contrat daté d'un animateur, conservé indépendamment de la Paie actuelle."""

    TYPE_CEE = "cee"
    TYPE_CDD = "cdd"
    TYPE_APPRENTISSAGE = "apprentissage"
    TYPE_PERMANENT = "permanent"
    TYPE_CHOICES = (
        (TYPE_CEE, "CEE"),
        (TYPE_CDD, "CDD"),
        (TYPE_APPRENTISSAGE, "Apprentissage"),
        (TYPE_PERMANENT, "Permanent"),
    )

    TEMPS_NON_RENSEIGNE = "non_renseigne"
    TEMPS_HEBDOMADAIRE = "hebdomadaire"
    TEMPS_MENSUEL = "mensuel"
    TEMPS_ANNUALISE = "annualise"
    TEMPS_CHOICES = (
        (TEMPS_NON_RENSEIGNE, "Non renseigné"),
        (TEMPS_HEBDOMADAIRE, "Hebdomadaire"),
        (TEMPS_MENSUEL, "Mensuel"),
        (TEMPS_ANNUALISE, "Annualisé / lissé"),
    )
    REMUNERATION_FIXE = "salaire_fixe"
    REMUNERATION_MINIMUM_SMIC = "minimum_smic"
    REMUNERATION_FIXE_CONTROLE = "fixe_controle"
    REMUNERATION_GRILLE_AUTO = "grille_auto"
    REMUNERATION_GRILLE_CONTROLE = "grille_controle"
    REMUNERATION_CHOICES = (
        (REMUNERATION_FIXE, "Salaire fixe"),
        (REMUNERATION_MINIMUM_SMIC, "Minimum SMIC automatique"),
        (REMUNERATION_FIXE_CONTROLE, "Salaire fixe avec contrôle du minimum"),
        (REMUNERATION_GRILLE_AUTO, "Minimum grille automatique"),
        (REMUNERATION_GRILLE_CONTROLE, "Salaire contractuel avec contrôle du minimum"),
    )

    STATUT_A_VENIR = "a_venir"
    STATUT_EN_COURS = "en_cours"
    STATUT_TERMINE = "termine"

    animateur = models.ForeignKey(Animateur, on_delete=models.CASCADE, related_name="contrats")
    # Champ de compatibilité conservé pour les anciens consommateurs ; le
    # référentiel TypeContrat porte désormais les choix configurables.
    type_contrat = models.CharField(max_length=50)
    type_contrat_ref = models.ForeignKey(
        TypeContrat,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="contrats",
    )
    date_debut = models.DateField(null=True, blank=True)
    date_fin = models.DateField(null=True, blank=True)
    taux_journalier_reference = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    salaire_mensuel_reference = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    mode_temps_travail = models.CharField(max_length=20, choices=TEMPS_CHOICES, default=TEMPS_NON_RENSEIGNE)
    heures_hebdomadaires = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    heures_mensuelles_reference = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    heures_annuelles_reference = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    mode_remuneration = models.CharField(max_length=24, choices=REMUNERATION_CHOICES, default=REMUNERATION_FIXE)
    annee_execution_initiale = models.PositiveSmallIntegerField(null=True, blank=True)
    date_effet_annee_execution = models.DateField(null=True, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-date_debut", "-id")

    @property
    def statut(self):
        aujourd_hui = timezone.localdate()
        if self.date_debut and self.date_debut > aujourd_hui:
            return self.STATUT_A_VENIR
        if self.date_fin and self.date_fin < aujourd_hui:
            return self.STATUT_TERMINE
        return self.STATUT_EN_COURS

    @property
    def libelle_statut(self):
        return {
            self.STATUT_A_VENIR: "À venir",
            self.STATUT_EN_COURS: "En cours",
            self.STATUT_TERMINE: "Terminé",
        }[self.statut]

    @property
    def definition_type(self):
        return self.type_contrat_ref

    @property
    def mode_paie(self):
        if self.type_contrat_ref_id:
            return self.type_contrat_ref.mode_remuneration
        return {
            self.TYPE_CEE: TypeContrat.MODE_CEE,
            self.TYPE_APPRENTISSAGE: TypeContrat.MODE_APPRENTISSAGE,
            self.TYPE_PERMANENT: TypeContrat.MODE_PAIE_HABITUELLE,
        }.get(self.type_contrat, TypeContrat.MODE_MENSUALISE)

    @property
    def libelle_type(self):
        if self.type_contrat_ref_id:
            return self.type_contrat_ref.nom
        return dict(self.TYPE_CHOICES).get(self.type_contrat, self.type_contrat)

    def clean(self):
        erreurs = {}
        mode_paie = self.mode_paie
        if mode_paie != TypeContrat.MODE_PAIE_HABITUELLE and self.date_debut is None:
            erreurs["date_debut"] = "La date de début est obligatoire pour ce type de contrat."
        if self.date_debut and self.date_fin and self.date_fin < self.date_debut:
            erreurs["date_fin"] = "La date de fin ne peut pas être antérieure à la date de début."
        if mode_paie == TypeContrat.MODE_CEE:
            if self.taux_journalier_reference is None:
                erreurs["taux_journalier_reference"] = "Le taux journalier de référence est obligatoire pour un CEE."
            if self.salaire_mensuel_reference is not None:
                erreurs["salaire_mensuel_reference"] = "Le salaire mensuel doit rester vide pour un CEE."
        elif mode_paie == TypeContrat.MODE_MENSUALISE:
            if self.mode_remuneration in (self.REMUNERATION_FIXE, self.REMUNERATION_FIXE_CONTROLE) and self.salaire_mensuel_reference is None:
                erreurs["salaire_mensuel_reference"] = "Le salaire mensuel de référence est obligatoire pour ce contrat."
            if self.taux_journalier_reference is not None:
                erreurs["taux_journalier_reference"] = "Le taux journalier doit rester vide pour ce contrat."
            if self.mode_remuneration == self.REMUNERATION_MINIMUM_SMIC and not (
                self.heures_mensuelles_reference is not None
                or self.heures_hebdomadaires is not None
            ):
                erreurs["heures_mensuelles_reference"] = "Un volume mensuel ou hebdomadaire est obligatoire pour le minimum SMIC automatique."
        elif mode_paie == TypeContrat.MODE_APPRENTISSAGE:
            if self.mode_remuneration in (self.REMUNERATION_FIXE, self.REMUNERATION_GRILLE_CONTROLE) and self.salaire_mensuel_reference is None:
                erreurs["salaire_mensuel_reference"] = "Le salaire contractuel est obligatoire dans ce mode."
            if self.mode_remuneration in (self.REMUNERATION_GRILLE_AUTO, self.REMUNERATION_GRILLE_CONTROLE):
                if not self.animateur_id or not self.animateur.date_naissance:
                    erreurs["annee_execution_initiale"] = "La date de naissance de l'animateur est nécessaire au calcul apprentissage."
                if self.annee_execution_initiale not in (1, 2, 3):
                    erreurs["annee_execution_initiale"] = "L'année d'exécution doit être comprise entre 1 et 3."

        if self.taux_journalier_reference is not None and self.taux_journalier_reference < 0:
            erreurs["taux_journalier_reference"] = "Le taux journalier ne peut pas être négatif."
        if self.salaire_mensuel_reference is not None and self.salaire_mensuel_reference < 0:
            erreurs["salaire_mensuel_reference"] = "Le salaire mensuel ne peut pas être négatif."
        for champ in ("heures_hebdomadaires", "heures_mensuelles_reference", "heures_annuelles_reference"):
            valeur = getattr(self, champ)
            if valeur is not None and valeur < 0:
                erreurs[champ] = "Le volume horaire ne peut pas être négatif."

        if self.animateur_id and not erreurs.get("date_fin"):
            chevauchements = Contrat.objects.filter(animateur_id=self.animateur_id).exclude(pk=self.pk)
            if self.date_debut:
                chevauchements = chevauchements.filter(
                    models.Q(date_fin__isnull=True) | models.Q(date_fin__gte=self.date_debut)
                )
            if self.date_fin:
                chevauchements = chevauchements.filter(
                    models.Q(date_debut__isnull=True) | models.Q(date_debut__lte=self.date_fin)
                )
            contrat = chevauchements.order_by("date_debut", "id").first()
            if contrat:
                fin_contrat = contrat.date_fin.strftime("%d/%m/%Y") if contrat.date_fin else "sans date de fin"
                debut_contrat = contrat.date_debut.strftime("%d/%m/%Y") if contrat.date_debut else "sans date de début"
                erreurs["date_debut"] = (
                    f"Ce contrat chevauche le {contrat.libelle_type} "
                    f"du {debut_contrat} au {fin_contrat}."
                )

        if erreurs:
            raise ValidationError(erreurs)

    def save(self, *args, **kwargs):
        if self.type_contrat_ref_id:
            self.type_contrat = self.type_contrat_ref.code
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        debut = self.date_debut.strftime("%d/%m/%Y") if self.date_debut else "sans date"
        return f"{self.libelle_type} — {self.animateur} — {debut}"


class ParametresStructure(models.Model):
    """Configuration générale d'une structure, accessible via un service central."""

    cle = models.SlugField(max_length=50, unique=True, default="principale", editable=False)
    nom_structure = models.CharField(max_length=200, blank=True)
    adresse = models.TextField(blank=True)
    code_postal = models.CharField(max_length=10, blank=True)
    ville = models.CharField(max_length=120, blank=True)
    telephone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    taux_indemnite_cp_cee = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("10.00"),
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))],
        verbose_name="taux indemnité congés payés CEE",
    )
    prime_journaliere_maximale = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal("7.00"),
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("10000.00"))],
        verbose_name="prime journalière maximale",
    )
    adapter_taux_cee_changement_statut = models.BooleanField(
        default=True,
        verbose_name="adapter automatiquement le taux CEE au changement de statut",
    )
    cree_le = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "paramètres de structure"
        verbose_name_plural = "paramètres de structure"

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nom_structure or "Structure principale"


class BaremeCEE(models.Model):
    """Montant journalier CEE d'un statut à compter d'une date donnée."""

    structure = models.ForeignKey(ParametresStructure, on_delete=models.CASCADE, related_name="baremes_cee")
    statut = models.ForeignKey(
        Qualification,
        on_delete=models.PROTECT,
        related_name="baremes_cee",
        limit_choices_to={"est_statut": True},
    )
    montant_journalier = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    date_effet = models.DateField()
    cree_le = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("statut__nom", "-date_effet", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("structure", "statut", "date_effet"),
                name="unique_bareme_cee_structure_statut_date",
            )
        ]

    def clean(self):
        if self.statut_id and not self.statut.est_statut:
            raise ValidationError({"statut": "Le barème CEE doit être lié à un statut animateur."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class ReferenceSMIC(models.Model):
    """Référence locale et historisée ; la Paie ne consulte jamais Internet."""

    structure = models.ForeignKey(ParametresStructure, on_delete=models.CASCADE, related_name="references_smic")
    date_effet = models.DateField()
    montant_horaire = models.DecimalField(max_digits=8, decimal_places=4, validators=[MinValueValidator(Decimal("0.00"))])
    montant_mensuel_35h = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal("0.00"))])
    source = models.CharField(max_length=160, blank=True)
    identifiant_externe = models.CharField(max_length=160, blank=True)
    recupere_le = models.DateTimeField(null=True, blank=True)
    commentaire = models.CharField(max_length=240, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-date_effet", "-id")
        constraints = [
            models.UniqueConstraint(fields=("structure", "date_effet"), name="unique_smic_structure_date")
        ]

    def save(self, *args, **kwargs):
        self.source = self.source.strip()
        self.commentaire = self.commentaire.strip()
        self.full_clean()
        super().save(*args, **kwargs)


class BaremeApprentissage(models.Model):
    """Pourcentage de SMIC d'une tranche d'âge et d'une année d'exécution."""

    structure = models.ForeignKey(ParametresStructure, on_delete=models.CASCADE, related_name="baremes_apprentissage")
    date_effet = models.DateField()
    annee_execution = models.PositiveSmallIntegerField()
    age_minimum = models.PositiveSmallIntegerField()
    age_maximum = models.PositiveSmallIntegerField(null=True, blank=True)
    pourcentage_smic = models.DecimalField(max_digits=6, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])
    actif = models.BooleanField(default=True)
    commentaire = models.CharField(max_length=240, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-date_effet", "annee_execution", "age_minimum", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("structure", "date_effet", "annee_execution", "age_minimum"),
                name="unique_bareme_apprentissage_tranche_date",
            )
        ]

    def clean(self):
        erreurs = {}
        if self.annee_execution not in (1, 2, 3):
            erreurs["annee_execution"] = "L'année d'exécution doit être comprise entre 1 et 3."
        if self.age_maximum is not None and self.age_maximum < self.age_minimum:
            erreurs["age_maximum"] = "L'âge maximum ne peut pas être inférieur à l'âge minimum."
        if erreurs:
            raise ValidationError(erreurs)

    def save(self, *args, **kwargs):
        self.commentaire = self.commentaire.strip()
        self.full_clean()
        super().save(*args, **kwargs)


class HistoriqueRemunerationContrat(models.Model):
    ORIGINE_MANUELLE = "manuel"
    ORIGINE_GRILLE = "grille_automatique"
    ORIGINE_AJUSTEMENT = "ajustement"
    ORIGINE_CHOICES = (
        (ORIGINE_MANUELLE, "Manuel"),
        (ORIGINE_GRILLE, "Grille automatique"),
        (ORIGINE_AJUSTEMENT, "Ajustement"),
    )

    contrat = models.ForeignKey(Contrat, on_delete=models.CASCADE, related_name="historique_remunerations")
    date_effet = models.DateField()
    montant_mensuel = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])
    origine = models.CharField(max_length=24, choices=ORIGINE_CHOICES, default=ORIGINE_MANUELLE)
    commentaire = models.CharField(max_length=240, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-date_effet", "-id")
        constraints = [
            models.UniqueConstraint(fields=("contrat", "date_effet"), name="unique_remuneration_contrat_date")
        ]

    def save(self, *args, **kwargs):
        self.commentaire = self.commentaire.strip()
        self.full_clean()
        super().save(*args, **kwargs)


class TypePrime(models.Model):
    """Prime configurable, indépendante de ses futures attributions en Paie."""

    MODE_JOUR = "jour"
    MODE_SEMAINE = "semaine"
    MODE_MOIS = "mois"
    MODE_FORFAIT = "forfait"
    MODE_CHOICES = (
        (MODE_JOUR, "Par jour"),
        (MODE_SEMAINE, "Par semaine"),
        (MODE_MOIS, "Par mois"),
        (MODE_FORFAIT, "Forfait"),
    )
    MONTANT_FIXE = "fixe"
    MONTANT_VARIABLE_PLAFONNE = "variable_plafonne"
    TYPE_MONTANT_CHOICES = (
        (MONTANT_FIXE, "Fixe"),
        (MONTANT_VARIABLE_PLAFONNE, "Variable plafonné"),
    )

    structure = models.ForeignKey(ParametresStructure, on_delete=models.CASCADE, related_name="types_primes")
    nom = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    active = models.BooleanField(default=False)
    mode_calcul = models.CharField(max_length=20, choices=MODE_CHOICES, default=MODE_JOUR)
    type_montant = models.CharField(max_length=24, choices=TYPE_MONTANT_CHOICES, default=MONTANT_FIXE)
    montant_fixe = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    montant_maximum = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    contrats_eligibles = models.JSONField(default=list, blank=True)
    types_contrats_eligibles = models.ManyToManyField(
        TypeContrat, blank=True, related_name="types_primes_eligibles"
    )
    tous_statuts = models.BooleanField(default=True)
    statuts_eligibles = models.ManyToManyField(
        Qualification,
        blank=True,
        related_name="types_primes_eligibles",
        limit_choices_to={"est_statut": True},
    )
    cree_le = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("nom", "id")
        constraints = [
            models.UniqueConstraint(fields=("structure", "nom"), name="unique_type_prime_structure_nom")
        ]

    def clean(self):
        erreurs = {}
        contrats_valides = {valeur for valeur, _ in Contrat.TYPE_CHOICES}
        if self.structure_id:
            contrats_valides.update(
                TypeContrat.objects.filter(structure_id=self.structure_id).values_list("code", flat=True)
            )
        contrats = list(dict.fromkeys(self.contrats_eligibles or []))
        if any(item not in contrats_valides for item in contrats):
            erreurs["contrats_eligibles"] = "Un type de contrat éligible est invalide."
        self.contrats_eligibles = contrats
        if self.montant_fixe is not None and self.montant_fixe < 0:
            erreurs["montant_fixe"] = "Le montant fixe ne peut pas être négatif."
        if self.montant_maximum is not None and self.montant_maximum < 0:
            erreurs["montant_maximum"] = "Le plafond ne peut pas être négatif."
        if self.type_montant == self.MONTANT_FIXE:
            if self.active and self.montant_fixe is None:
                erreurs["montant_fixe"] = "Le montant fixe est obligatoire pour une prime active."
            if self.montant_maximum is not None:
                erreurs["montant_maximum"] = "Le plafond doit rester vide pour une prime fixe."
        elif self.type_montant == self.MONTANT_VARIABLE_PLAFONNE:
            if self.active and self.montant_maximum is None:
                erreurs["montant_maximum"] = "Le plafond est obligatoire pour une prime active."
            if self.montant_fixe is not None:
                erreurs["montant_fixe"] = "Le montant fixe doit rester vide pour une prime variable."
        if self.active and not contrats:
            erreurs["contrats_eligibles"] = "Choisis au moins un type de contrat éligible pour une prime active."
        if erreurs:
            raise ValidationError(erreurs)

    def save(self, *args, **kwargs):
        self.nom = self.nom.strip()
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nom


class AttributionPrime(models.Model):
    """Prime de paie figée : les changements du référentiel ne sont pas rétroactifs."""

    animateur = models.ForeignKey(Animateur, on_delete=models.CASCADE, related_name="attributions_primes")
    type_prime = models.ForeignKey(TypePrime, on_delete=models.PROTECT, related_name="attributions")
    centre = models.ForeignKey(
        "Centre", on_delete=models.SET_NULL, null=True, blank=True, related_name="attributions_primes"
    )
    date_debut = models.DateField()
    date_fin = models.DateField()
    mode_calcul = models.CharField(max_length=20, choices=TypePrime.MODE_CHOICES)
    montant_unitaire = models.DecimalField(max_digits=10, decimal_places=2)
    montant_total = models.DecimalField(max_digits=12, decimal_places=2)
    commentaire = models.CharField(max_length=240, blank=True)
    attribue_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="primes_attribuees",
    )
    cree_le = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-date_debut", "animateur__prenom", "animateur__nom", "id")

    def clean(self):
        erreurs = {}
        if self.date_debut and self.date_fin and self.date_fin < self.date_debut:
            erreurs["date_fin"] = "La date de fin ne peut pas précéder la date de début."
        if self.montant_unitaire is not None and self.montant_unitaire < 0:
            erreurs["montant_unitaire"] = "Le montant ne peut pas être négatif."
        if self.montant_total is not None and self.montant_total < 0:
            erreurs["montant_total"] = "Le montant total ne peut pas être négatif."
        if erreurs:
            raise ValidationError(erreurs)

    def save(self, *args, **kwargs):
        self.commentaire = self.commentaire.strip()
        self.full_clean()
        super().save(*args, **kwargs)


class TypeAccueil(models.Model):
    """Référentiel commun des contextes d'activité de l'application."""

    VACANCES = "vacances"
    MERCREDIS = "mercredis"
    PERISCOLAIRE = "periscolaire"
    SEJOURS = "sejours"

    code = models.SlugField(max_length=24, unique=True)
    nom = models.CharField(max_length=60, unique=True)
    ordre = models.PositiveSmallIntegerField(default=0)
    actif = models.BooleanField(default=True)

    class Meta:
        ordering = ("ordre", "nom")
        verbose_name = "type d'accueil"
        verbose_name_plural = "types d'accueil"

    def __str__(self):
        return self.nom


class ModalitePeriscolaire(models.Model):
    MERCREDI_JOURNEE = "mercredi_journee"
    MATIN = "matin"
    MIDI = "midi"
    SOIR = "soir"
    DEVOIRS = "aide_devoirs"

    code = models.SlugField(max_length=40, unique=True)
    nom = models.CharField(max_length=100)
    heure_debut = models.TimeField(null=True, blank=True)
    heure_fin = models.TimeField(null=True, blank=True)
    jour_entier = models.BooleanField(default=False)
    actif = models.BooleanField(default=True)
    ordre = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("ordre", "nom")

    def __str__(self):
        return self.nom


class Centre(models.Model):
    """Un centre d'animation (ex: Pacaudière, Saint-Forgeux...). Chaque
    centre a son propre calendrier sur la page planning."""

    nom = models.CharField(max_length=100)
    cle_unique = models.CharField(max_length=120, unique=True, editable=False)

    code = models.CharField(
        max_length=10,
        unique=True,
        help_text="Abréviation courte affichée dans les badges, ex: PAC",
    )

    adresse = models.CharField(max_length=240, blank=True, default="")
    code_postal = models.CharField(
        max_length=5, blank=True, default="", validators=[code_postal_francais]
    )
    commune = models.CharField(max_length=120, blank=True, default="")
    code_insee = models.CharField(max_length=5, blank=True, default="")
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    precision_localisation = models.CharField(
        max_length=14,
        choices=PRECISIONS_LOCALISATION,
        default="non_localisee",
    )

    couleur = models.CharField(
        max_length=7,
        default="#e03c00",
        help_text="Couleur hexadécimale utilisée pour les badges, ex: #e03c00",
    )

    effectif_cible = models.PositiveSmallIntegerField(default=1)
    types_accueil = models.ManyToManyField(
        TypeAccueil,
        related_name="centres",
        blank=True,
        help_text="Types d'accueil proposés dans ce lieu physique.",
    )

    ordre = models.PositiveSmallIntegerField(
        default=0,
        help_text="Ordre d’affichage des lieux sur la page planning.",
    )

    class Meta:
        ordering = ["ordre", "nom"]

    def save(self, *args, **kwargs):
        self.nom = self.nom.strip()
        self.code = self.code.strip().upper()
        self.adresse = self.adresse.strip()
        self.code_postal = self.code_postal.strip()
        self.commune = self.commune.strip()
        self.code_insee = self.code_insee.strip().upper()
        self.cle_unique = normaliser_cle_unique(self.nom)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nom


class Groupe(models.Model):
    """Définition partagée d'un groupe, instanciable dans plusieurs lieux."""

    nom = models.CharField(max_length=100)
    cle_unique = models.CharField(max_length=120, unique=True, editable=False, default="")
    enfants_par_animateur_defaut = models.PositiveSmallIntegerField(
        default=8,
        verbose_name="nombre d’enfants par animateur par défaut",
    )
    types_accueil = models.ManyToManyField(
        TypeAccueil,
        related_name="groupes_partages",
        blank=True,
        help_text="Types d'accueil utilisant cette définition partagée.",
    )

    class Meta:
        ordering = ["nom"]
        verbose_name = "groupe partagé"
        verbose_name_plural = "groupes partagés"

    def save(self, *args, **kwargs):
        self.nom = self.nom.strip()
        self.cle_unique = normaliser_cle_unique(self.nom)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nom


class Evenement(models.Model):
    """Instance d'un groupe partagé dans un lieu."""

    groupe = models.ForeignKey(
        Groupe,
        on_delete=models.PROTECT,
        related_name="instances",
        verbose_name="groupe partagé",
    )

    centre = models.ForeignKey(
        Centre,
        on_delete=models.CASCADE,
        related_name="evenements",
        verbose_name="lieu",
    )
    nom = models.CharField(max_length=100)
    cle_unique = models.CharField(max_length=120, editable=False, default="")
    permanent = models.BooleanField(
        default=False,
        verbose_name="groupe permanent",
        help_text="Un groupe permanent est ouvert à toutes les périodes selon ses jours habituels.",
    )
    periodes_scolaires = models.ManyToManyField(
        "PeriodeScolaire",
        related_name="groupes",
        blank=True,
        verbose_name="périodes",
    )
    types_accueil = models.ManyToManyField(
        TypeAccueil,
        related_name="groupes_accueil",
        blank=True,
    )
    modalite_periscolaire = models.ForeignKey(
        ModalitePeriscolaire, on_delete=models.PROTECT, related_name="groupes_accueil", null=True, blank=True
    )
    ferme_jours_feries = models.BooleanField(
        default=True,
        verbose_name="fermé les jours fériés",
    )
    effectif_cible = models.PositiveSmallIntegerField(
        default=1,
        help_text="Nombre de personnes nécessaires chaque jour",
    )
    enfants_par_animateur_defaut = models.PositiveSmallIntegerField(
        default=8,
        verbose_name="nombre d’enfants par animateur par défaut",
        help_text="Ratio proposé automatiquement dans le Planning, par exemple 8 pour 1 animateur pour 8 enfants.",
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
                fields=["centre", "groupe"],
                name="unique_instance_groupe_par_lieu",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self.groupe_id:
            cle = normaliser_cle_unique(self.nom)
            self.groupe, _ = Groupe.objects.get_or_create(
                cle_unique=cle,
                defaults={
                    "nom": self.nom.strip(),
                    "enfants_par_animateur_defaut": self.enfants_par_animateur_defaut,
                },
            )
        if self.groupe_id:
            self.nom = self.groupe.nom
            self.enfants_par_animateur_defaut = self.groupe.enfants_par_animateur_defaut
        self.nom = self.nom.strip()
        self.cle_unique = normaliser_cle_unique(self.nom)
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        try:
            jours = sorted({int(numero) for numero in (self.jours_ouverts or [])})
        except (TypeError, ValueError):
            raise ValidationError({"jours_ouverts": "Les jours d’ouverture sont invalides."}) from None
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
        if not self.permanent:
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


class EffectifEnfantsJour(models.Model):
    """Effectif réel d'enfants prévu pour un groupe à une date donnée."""

    evenement = models.ForeignKey(
        Evenement,
        on_delete=models.CASCADE,
        related_name="effectifs_enfants",
        verbose_name="groupe",
    )
    date = models.DateField(db_index=True)
    type_accueil = models.ForeignKey(
        TypeAccueil,
        on_delete=models.PROTECT,
        related_name="effectifs_enfants",
        null=True,
        blank=True,
    )
    modalite_periscolaire = models.ForeignKey(ModalitePeriscolaire, on_delete=models.PROTECT, related_name="effectifs", null=True, blank=True)
    nombre = models.PositiveSmallIntegerField(default=0)
    heure_arrivee = models.TimeField(blank=True, null=True)
    heure_depart = models.TimeField(blank=True, null=True)
    enfants_par_animateur = models.PositiveSmallIntegerField(
        default=8,
        verbose_name="nombre d’enfants par animateur",
    )
    ratio_encadrement_exceptionnel = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        verbose_name="ratio d’encadrement exceptionnel",
    )
    modifie_le = models.DateTimeField(auto_now=True)

    @property
    def ratio_encadrement_effectif(self):
        return self.ratio_encadrement_exceptionnel or self.evenement.enfants_par_animateur_defaut

    class Meta:
        ordering = ("date",)
        constraints = [
            models.UniqueConstraint(
                fields=("evenement", "date"),
                name="unique_effectif_enfants_groupe_date",
            ),
        ]
        verbose_name = "effectif enfants journalier"
        verbose_name_plural = "effectifs enfants journaliers"

    def __str__(self):
        return f"{self.evenement} — {self.date:%d/%m/%Y} : {self.nombre} enfants (1/{self.enfants_par_animateur})"


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
    type_accueil = models.ForeignKey(
        TypeAccueil,
        on_delete=models.PROTECT,
        related_name="besoins_qualifications",
        null=True,
        blank=True,
    )
    modalite_periscolaire = models.ForeignKey(ModalitePeriscolaire, on_delete=models.PROTECT, related_name="besoins", null=True, blank=True)

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

    Une relation peut être marquée comme lieu préféré, interdite ou neutre.
    Plusieurs lieux peuvent être préférés ; leur ordre est porté par la liste
    envoyée par l'interface lors des mises à jour.
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
        help_text="Centre à privilégier lors du remplissage automatique.",
    )
    est_interdit = models.BooleanField(
        default=False,
        help_text="Centre dans lequel cet animateur ne doit jamais être affecté.",
    )

    class Meta:
        ordering = ["-est_prefere", "centre__nom"]
        constraints = [
            # Un animateur ne peut pas avoir deux fois le même centre
            # dans ses préférences.
            models.UniqueConstraint(
                fields=["animateur", "centre"],
                name="unique_animateur_centre",
            ),
        ]

    def __str__(self):
        if self.est_interdit:
            type_centre = "centre interdit"
        elif self.est_prefere:
            type_centre = "centre préféré"
        else:
            type_centre = "centre neutre"
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
    periode_calendrier = models.ForeignKey(
        "PeriodeCalendrier",
        on_delete=models.PROTECT,
        related_name="semaines",
        null=True,
        blank=True,
    )
    type_accueil = models.ForeignKey(
        TypeAccueil,
        default=type_accueil_vacances_par_defaut,
        on_delete=models.PROTECT,
        related_name="periodes",
    )
    types_accueil = models.ManyToManyField(
        TypeAccueil,
        related_name="semaines_reference",
        blank=True,
        help_text="Types utilisant cette même semaine de référence.",
    )
    modalite_periscolaire = models.ForeignKey(ModalitePeriscolaire, on_delete=models.PROTECT, related_name="periodes_travail", null=True, blank=True)
    modalites_periscolaires = models.ManyToManyField(ModalitePeriscolaire, related_name="semaines_reference", blank=True)
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
        if (
            self.type_accueil_id
            and self.type_accueil.code == TypeAccueil.VACANCES
            and (self.debut.weekday() != 0 or self.fin.weekday() != 4)
        ):
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

    @property
    def categorie_vacances(self):
        """Libellé commun utilisé pour regrouper les semaines d'une période."""
        categorie = re.split(r"\s*[—–-]\s*Semaine\b", self.nom, maxsplit=1, flags=re.IGNORECASE)[0]
        return re.sub(r"\s+\d{4}$", "", categorie).strip() or "Autres périodes"

    def __str__(self):
        return f"{self.libelle_avec_annee} ({self.debut:%d/%m/%Y} au {self.fin:%d/%m/%Y})"


class PeriodeCalendrier(models.Model):
    """Référence calendaire commune, distincte du type d'accueil."""

    VACANCES = "vacances"
    SCOLAIRE = "scolaire"
    CATEGORIES = ((VACANCES, "Vacances scolaires"), (SCOLAIRE, "Période scolaire"))

    categorie = models.CharField(max_length=12, choices=CATEGORIES)
    nom = models.CharField(max_length=140)
    annee_scolaire = models.CharField(max_length=9)
    zone = models.CharField(max_length=1, choices=PeriodeScolaire.ZONES)
    debut = models.DateField()
    fin = models.DateField()
    types_accueil = models.ManyToManyField(TypeAccueil, related_name="periodes_calendrier", blank=True)

    class Meta:
        ordering = ("-annee_scolaire", "zone", "debut", "nom")
        constraints = [
            models.UniqueConstraint(
                fields=("categorie", "annee_scolaire", "zone", "debut", "fin"),
                name="unique_periode_calendrier_zone_dates",
            ),
            models.CheckConstraint(
                condition=models.Q(fin__gte=models.F("debut")),
                name="periode_calendrier_fin_apres_debut",
            ),
        ]

    def __str__(self):
        return f"{self.nom} {self.debut.year}"


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
    types_accueil = models.ManyToManyField(
        TypeAccueil,
        related_name="disponibilites",
        blank=True,
        help_text="Vide signifie que la disponibilité reste générale.",
    )

    class Meta:
        ordering = ["debut"]
        indexes = [
            models.Index(fields=["animateur", "debut", "fin"], name="dispo_anim_dates_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(debut__isnull=True)
                | models.Q(fin__isnull=True)
                | models.Q(fin__gte=models.F("debut")),
                name="dispo_fin_apres_debut",
            ),
        ]

    def __str__(self):
        return f"{self.animateur} disponible du {self.debut:%d/%m/%Y} au {self.fin:%d/%m/%Y}"


class AffiniteGroupeAnimateur(models.Model):
    """Affinité persistante d'un animateur avec un groupe.

    Le score correspond au nombre de journées réellement terminées dans ce
    groupe. Il est synchronisé depuis les affectations passées et sert de
    critère au remplissage automatique. Une table intermédiaire est nécessaire
    car chaque animateur possède une valeur différente pour chaque groupe.
    """

    animateur = models.ForeignKey(
        Animateur,
        on_delete=models.CASCADE,
        related_name="affinites_groupes",
    )
    evenement = models.ForeignKey(
        Evenement,
        on_delete=models.CASCADE,
        related_name="affinites_animateurs",
        verbose_name="groupe",
    )
    jours_travailles = models.PositiveIntegerField(
        default=0,
        verbose_name="jours travaillés",
    )
    dernier_jour_travaille = models.DateField(
        null=True,
        blank=True,
        verbose_name="dernier jour travaillé",
    )
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-jours_travailles", "evenement__centre__nom", "evenement__nom")
        constraints = [
            models.UniqueConstraint(
                fields=("animateur", "evenement"),
                name="unique_affinite_animateur_groupe",
            ),
        ]
        indexes = [
            models.Index(
                fields=("animateur", "jours_travailles"),
                name="affinite_anim_score_idx",
            ),
            models.Index(
                fields=("evenement", "jours_travailles"),
                name="affinite_groupe_score_idx",
            ),
        ]
        verbose_name = "affinité animateur-groupe"
        verbose_name_plural = "affinités animateurs-groupes"

    @property
    def score(self):
        return self.jours_travailles

    def __str__(self):
        return f"{self.animateur} ↔ {self.evenement} : {self.jours_travailles} jour(s)"


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
    centre = models.ForeignKey(Centre, on_delete=models.CASCADE, related_name="affectations")
    evenement = models.ForeignKey(
        Evenement,
        on_delete=models.PROTECT,
        related_name="affectations",
        verbose_name="groupe",
    )
    debut = models.DateTimeField()
    fin = models.DateTimeField()
    type_accueil = models.ForeignKey(
        TypeAccueil,
        on_delete=models.PROTECT,
        related_name="affectations",
        null=True,
        blank=True,
    )
    modalite_periscolaire = models.ForeignKey(ModalitePeriscolaire, on_delete=models.PROTECT, related_name="affectations", null=True, blank=True)

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


class ActiviteTravailComplementaire(models.Model):
    """Temps de travail hors affectation dans un lieu ou un groupe."""

    TYPE_REUNION = "reunion"
    TYPE_PREPARATION = "preparation"
    TYPES = [
        (TYPE_REUNION, "Réunion"),
        (TYPE_PREPARATION, "Télétravail / préparation"),
    ]

    type = models.CharField(max_length=20, choices=TYPES)
    intitule = models.CharField(max_length=160)
    date = models.DateField(null=True, blank=True)
    remarque = models.TextField(blank=True, default="")
    periodes = models.ManyToManyField(
        PeriodeScolaire,
        related_name="activites_travail_complementaires",
    )
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)
    type_accueil = models.ForeignKey(
        TypeAccueil,
        on_delete=models.PROTECT,
        related_name="activites_travail_complementaires",
        null=True,
        blank=True,
        help_text="Vide signifie que l'activité reste visible dans la vue générale.",
    )
    modalite_periscolaire = models.ForeignKey(ModalitePeriscolaire, on_delete=models.PROTECT, related_name="activites_travail", null=True, blank=True)

    class Meta:
        ordering = ("date", "intitule", "id")
        indexes = [models.Index(fields=("type", "date"), name="activite_travail_type_date_idx")]
        verbose_name = "activité de travail complémentaire"
        verbose_name_plural = "activités de travail complémentaires"

    def clean(self):
        super().clean()
        if self.type == self.TYPE_REUNION and self.date is None:
            raise ValidationError({"date": "Une réunion doit posséder une date."})
        if self.type == self.TYPE_PREPARATION:
            self.date = None

    def __str__(self):
        return self.intitule


class ParticipationTravailComplementaire(models.Model):
    """Nombre de journées complémentaires attribuées à un animateur."""

    activite = models.ForeignKey(
        ActiviteTravailComplementaire,
        on_delete=models.CASCADE,
        related_name="participations",
    )
    animateur = models.ForeignKey(
        Animateur,
        on_delete=models.CASCADE,
        related_name="participations_travail_complementaire",
    )
    nombre_jours = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("1.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    remarque = models.CharField(max_length=240, blank=True, default="")
    autoriser_double_comptage = models.BooleanField(default=False)

    class Meta:
        ordering = ("animateur__prenom", "animateur__nom")
        constraints = [
            models.UniqueConstraint(
                fields=("activite", "animateur"),
                name="unique_participation_activite_animateur",
            ),
            models.CheckConstraint(
                condition=models.Q(nombre_jours__gte=0),
                name="participation_nombre_jours_positif",
            ),
        ]
        verbose_name = "participation de travail complémentaire"
        verbose_name_plural = "participations de travail complémentaire"

    def clean(self):
        super().clean()
        if self.activite_id and self.activite.type == ActiviteTravailComplementaire.TYPE_REUNION:
            self.nombre_jours = Decimal("1.00")

    def save(self, *args, **kwargs):
        if self.activite_id and self.activite.type == ActiviteTravailComplementaire.TYPE_REUNION:
            self.nombre_jours = Decimal("1.00")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.animateur} — {self.activite} : {self.nombre_jours} jour(s)"


class PrimeJournalierePeriode(models.Model):
    """Prime journalière propre à un animateur et à une semaine de paie."""

    animateur = models.ForeignKey(
        Animateur,
        on_delete=models.CASCADE,
        related_name="primes_journalieres",
    )
    periode = models.ForeignKey(
        PeriodeScolaire,
        on_delete=models.CASCADE,
        related_name="primes_journalieres",
    )
    montant = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("7.00")),
        ],
    )
    date_modification = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("periode__debut", "animateur__prenom", "animateur__nom")
        constraints = [
            models.UniqueConstraint(
                fields=("animateur", "periode"),
                name="unique_prime_journaliere_animateur_periode",
            ),
            models.CheckConstraint(
                condition=models.Q(montant__gte=0, montant__lte=7),
                name="prime_journaliere_entre_zero_et_sept",
            ),
        ]
        verbose_name = "prime journalière par période"
        verbose_name_plural = "primes journalières par période"

    def __str__(self):
        return f"{self.animateur} — {self.periode} : {self.montant} € / jour"

    def clean(self):
        super().clean()
        if self.montant is not None and self.montant != self.montant.to_integral_value():
            raise ValidationError({"montant": "La prime doit être indiquée en euros entiers."})


class HoraireAffectationJour(models.Model):
    """Horaires propres à un animateur pour une journée de son affectation."""

    affectation = models.ForeignKey(
        Affectation,
        on_delete=models.CASCADE,
        related_name="horaires_journaliers",
    )
    date = models.DateField(db_index=True)
    heure_arrivee = models.TimeField()
    heure_depart = models.TimeField()

    class Meta:
        ordering = ("date",)
        constraints = [
            models.UniqueConstraint(
                fields=("affectation", "date"),
                name="horaire_unique_par_affectation_jour",
            ),
            models.CheckConstraint(
                condition=models.Q(heure_depart__gt=models.F("heure_arrivee")),
                name="horaire_affectation_depart_apres_arrivee",
            ),
        ]


class PublicationPlanning(models.Model):
    """État de publication d’une semaine de planning pour les animateurs."""

    semaine_debut = models.DateField(unique=True, db_index=True)
    publie = models.BooleanField(default=False, db_index=True)
    type_accueil = models.ForeignKey(
        TypeAccueil,
        on_delete=models.PROTECT,
        related_name="publications_planning",
        null=True,
        blank=True,
    )
    modalite_periscolaire = models.ForeignKey(ModalitePeriscolaire, on_delete=models.PROTECT, related_name="publications", null=True, blank=True)
    date_modification = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-semaine_debut"]

    def clean(self):
        super().clean()
        if self.semaine_debut and self.semaine_debut.weekday() != 0:
            raise ValidationError({"semaine_debut": "La date doit être un lundi."})

    def __str__(self):
        statut = "publié" if self.publie else "non publié"
        return f"Planning du {self.semaine_debut:%d/%m/%Y} — {statut}"


class DemandeMateriel(models.Model):
    """Demande de matériel créée par un animateur et traitée par la direction."""

    STATUT_EN_ATTENTE = "en_attente"
    STATUT_VALIDEE = "validee"
    STATUT_CHOICES = [
        (STATUT_EN_ATTENTE, "En attente"),
        (STATUT_VALIDEE, "Validée"),
    ]

    animateur = models.ForeignKey(
        Animateur,
        on_delete=models.CASCADE,
        related_name="demandes_materiel",
    )
    centre = models.ForeignKey(
        Centre,
        on_delete=models.PROTECT,
        related_name="demandes_materiel",
        null=True,
        blank=True,
    )
    materiel = models.CharField(max_length=180)
    quantite = models.PositiveIntegerField(default=1)
    date_besoin = models.DateField(verbose_name="date souhaitée")
    statut = models.CharField(
        max_length=20,
        choices=STATUT_CHOICES,
        default=STATUT_EN_ATTENTE,
        db_index=True,
    )
    date_creation = models.DateTimeField(auto_now_add=True)
    date_validation = models.DateTimeField(null=True, blank=True)
    validee_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="demandes_materiel_validees",
    )

    class Meta:
        ordering = ("statut", "date_besoin", "-date_creation")
        verbose_name = "demande de matériel"
        verbose_name_plural = "demandes de matériel"

    def __str__(self):
        centre = f" — {self.centre}" if self.centre_id else ""
        return f"{self.materiel} × {self.quantite} — {self.animateur}{centre}"


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
    periodes = models.ManyToManyField(
        "PeriodeScolaire",
        related_name="documents",
        blank=True,
        help_text="Semaines auxquelles ce document est rattaché.",
    )
    tous_centres = models.BooleanField(
        default=True,
        help_text="Si coché, le document concerne tous les centres.",
    )
    centres = models.ManyToManyField(
        Centre,
        related_name="documents",
        blank=True,
        help_text="Centres concernés lorsque le document n'est pas destiné à tous les centres.",
    )
    types_accueil = models.ManyToManyField(
        TypeAccueil,
        related_name="documents",
        blank=True,
        help_text="Types d'accueil concernés ; vide conserve le comportement général historique.",
    )
    modalites_periscolaires = models.ManyToManyField(ModalitePeriscolaire, related_name="documents", blank=True)
    publie = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="publié pour les animateurs",
        help_text="Seuls les documents publiés sont visibles dans l’espace animateur.",
    )
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
        periodes = list(self.periodes.all()) if self.pk else []
        if periodes:
            if len(periodes) == 1:
                return periodes[0].libelle_avec_annee
            return f"{len(periodes)} semaines sélectionnées"
        if self.permanent:
            return "Permanent"
        if self.periode_debut and self.periode_fin:
            return f"Du {self.periode_debut:%d/%m/%Y} au {self.periode_fin:%d/%m/%Y}"
        return "Période non renseignée"

    def __str__(self):
        return self.titre


class Sejour(models.Model):
    """Séjour distinct d'un lieu, avec traçabilité de la donnée historique."""

    nom = models.CharField(max_length=160)
    type_accueil = models.ForeignKey(TypeAccueil, default=type_accueil_sejours_par_defaut, on_delete=models.PROTECT, related_name="sejours_structures")
    date_debut = models.DateField(null=True, blank=True)
    date_fin = models.DateField(null=True, blank=True)
    destination = models.CharField(max_length=240, blank=True, default="")
    hebergement = models.CharField(max_length=240, blank=True, default="")
    periode_vacances = models.ForeignKey(
        PeriodeCalendrier,
        on_delete=models.PROTECT,
        related_name="sejours",
        null=True,
        blank=True,
        limit_choices_to={"categorie": PeriodeCalendrier.VACANCES},
    )
    equipe = models.ManyToManyField(Animateur, related_name="sejours", blank=True)
    responsable = models.ForeignKey(Animateur, on_delete=models.PROTECT, related_name="sejours_responsable", null=True, blank=True)
    documents = models.ManyToManyField(Document, related_name="sejours", blank=True)
    source_lieu_legacy = models.OneToOneField(
        Centre,
        on_delete=models.PROTECT,
        related_name="sejour_migre",
        null=True,
        blank=True,
        help_text="Lieu historique conservé pendant sa migration progressive.",
    )
    actif = models.BooleanField(default=True)

    class Meta:
        ordering = ("date_debut", "nom")

    def clean(self):
        super().clean()
        if self.date_debut and self.date_fin and self.date_fin < self.date_debut:
            raise ValidationError({"date_fin": "La fin du séjour doit suivre son début."})

    @property
    def avertissement_periode_vacances(self):
        if not self.periode_vacances or not self.date_debut or not self.date_fin:
            return ""
        if self.date_debut < self.periode_vacances.debut or self.date_fin > self.periode_vacances.fin:
            return "Les dates du séjour dépassent la période de vacances associée."
        return ""

    def __str__(self):
        return self.nom


class StatutPreparationSemaine(models.Model):
    """Surcharge purement visuelle du statut de préparation d'une semaine."""

    debut_semaine = models.DateField(unique=True)
    est_force_prete = models.BooleanField(default=False)
    modifie_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="statuts_preparation_semaines_modifies",
    )
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-debut_semaine",)

    def __str__(self):
        return f"Semaine du {self.debut_semaine:%d/%m/%Y}"


class ParticipantSejour(models.Model):
    sejour = models.ForeignKey(Sejour, on_delete=models.CASCADE, related_name="participants")
    prenom = models.CharField(max_length=100)
    nom = models.CharField(max_length=100)
    date_naissance = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ("nom", "prenom")

    def __str__(self):
        return f"{self.prenom} {self.nom}"


class Sortie(models.Model):
    """Préparation d'une sortie ; les effectifs restent calculés depuis le Planning."""

    MODE_CAR = "Car"
    MODE_MINIBUS = "Minibus"
    MODE_LIGNE_REGULIERE = "Ligne régulière"
    MODE_TRANSPORT_COMMUN = "Transport en commun"
    MODES_TRANSPORT = (
        (MODE_CAR, MODE_CAR),
        (MODE_MINIBUS, MODE_MINIBUS),
        (MODE_LIGNE_REGULIERE, MODE_LIGNE_REGULIERE),
        (MODE_TRANSPORT_COMMUN, MODE_TRANSPORT_COMMUN),
    )

    nom = models.CharField(max_length=150)
    type_accueil = models.ForeignKey(
        TypeAccueil,
        on_delete=models.PROTECT,
        related_name="sorties",
        null=True,
        blank=True,
    )
    modalite_periscolaire = models.ForeignKey(ModalitePeriscolaire, on_delete=models.PROTECT, related_name="sorties", null=True, blank=True)
    date = models.DateField(db_index=True)
    destination = models.CharField(max_length=180)
    destination_adresse = models.CharField(max_length=240, blank=True, default="")
    destination_code_postal = models.CharField(
        max_length=5, blank=True, default="", validators=[code_postal_francais]
    )
    destination_commune = models.CharField(max_length=120, blank=True, default="")
    destination_code_insee = models.CharField(max_length=5, blank=True, default="")
    destination_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    destination_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    PRECISION_ADRESSE = "adresse"
    PRECISION_COMMUNE = "commune"
    PRECISION_CODE_POSTAL = "code_postal"
    PRECISION_NON_LOCALISEE = "non_localisee"
    PRECISIONS_DESTINATION = PRECISIONS_LOCALISATION
    destination_precision = models.CharField(
        max_length=14,
        choices=PRECISIONS_DESTINATION,
        default=PRECISION_NON_LOCALISEE,
    )
    meteo_lieu_libelle = models.CharField(max_length=180, blank=True, default="")
    meteo_adresse = models.CharField(max_length=300, blank=True, default="")
    meteo_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    meteo_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    meteo_code_departement = models.CharField(max_length=3, blank=True, default="")
    mode_transport = models.CharField(max_length=100, choices=MODES_TRANSPORT, blank=True, default="")
    nombre_vehicules = models.PositiveSmallIntegerField(null=True, blank=True)
    heure_depart = models.TimeField(null=True, blank=True)
    heure_arrivee = models.TimeField(null=True, blank=True)
    heure_depart_site = models.TimeField(null=True, blank=True)
    heure_retour = models.TimeField(null=True, blank=True)
    heure_arrivee_retour = models.TimeField(null=True, blank=True)
    temps_arret_par_site = models.PositiveSmallIntegerField(
        default=10,
        validators=[MinValueValidator(0), MaxValueValidator(60)],
    )
    SOURCE_HORAIRE_AUTOMATIQUE = "automatique"
    SOURCE_HORAIRE_MANUELLE = "manuelle"
    SOURCE_HORAIRE_CHOICES = (
        (SOURCE_HORAIRE_AUTOMATIQUE, "Estimation automatique"),
        (SOURCE_HORAIRE_MANUELLE, "Heure ajustée manuellement"),
    )
    source_heure_arrivee = models.CharField(
        max_length=12, choices=SOURCE_HORAIRE_CHOICES, blank=True, default=""
    )
    source_heure_arrivee_retour = models.CharField(
        max_length=12, choices=SOURCE_HORAIRE_CHOICES, blank=True, default=""
    )
    trajet_ramassage = models.TextField(blank=True, default="")
    consignes_transport = models.TextField(blank=True, default="")
    objectifs_pedagogiques = models.TextField(blank=True, default="")
    consignes_encadrement = models.TextField(blank=True, default="")
    organisation_maternels = models.TextField(blank=True, default="")
    organisation_elementaires = models.TextField(blank=True, default="")
    repas_gouter = models.TextField(blank=True, default="")
    documents = models.ManyToManyField(Document, related_name="sorties", blank=True)
    groupes = models.ManyToManyField(Evenement, through="SortieParticipation", related_name="sorties")
    cree_le = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("date", "nom")

    def save(self, *args, **kwargs):
        self.nom = self.nom.strip()
        self.destination = self.destination.strip()
        self.destination_adresse = self.destination_adresse.strip()
        self.destination_code_postal = self.destination_code_postal.strip()
        self.destination_commune = self.destination_commune.strip()
        self.destination_code_insee = self.destination_code_insee.strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.nom} — {self.date:%d/%m/%Y}"


class SortieEtapeTransport(models.Model):
    """Lieu ordonné d'un circuit de transport, sans horaire individuel."""

    SENS_ALLER = "aller"
    SENS_RETOUR = "retour"
    SENS_CHOICES = ((SENS_ALLER, "Aller"), (SENS_RETOUR, "Retour"))

    sortie = models.ForeignKey(Sortie, on_delete=models.CASCADE, related_name="etapes_transport")
    centre = models.ForeignKey(Centre, on_delete=models.PROTECT, related_name="etapes_transport_sorties")
    sens = models.CharField(max_length=6, choices=SENS_CHOICES)
    ordre = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ("sens", "ordre", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("sortie", "sens", "centre"),
                name="unique_centre_par_circuit_sortie",
            ),
            models.UniqueConstraint(
                fields=("sortie", "sens", "ordre"),
                name="unique_ordre_par_circuit_sortie",
            ),
        ]


class PreferenceTransportUtilisateur(models.Model):
    """Dernier mode de transport choisi, isolé par compte utilisateur."""

    utilisateur = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="preference_transport",
    )
    mode_transport = models.CharField(max_length=100, choices=Sortie.MODES_TRANSPORT)
    modifie_le = models.DateTimeField(auto_now=True)


class SortieResponsabilite(models.Model):
    """Responsabilité opérationnelle définie pour une sortie.

    Une ligne représente un seul périmètre : toute la sortie (direction),
    un lieu ou un groupe. Le formulaire peut néanmoins regrouper plusieurs
    lignes afin d'attribuer plusieurs lieux ou groupes au même responsable.
    """

    TYPE_DIRECTION = "direction"
    TYPE_LIEU = "lieu"
    TYPE_GROUPE = "groupe"
    TYPE_CHOICES = [
        (TYPE_DIRECTION, "Direction"),
        (TYPE_LIEU, "Responsable de lieu"),
        (TYPE_GROUPE, "Responsable de groupe"),
    ]

    sortie = models.ForeignKey(Sortie, on_delete=models.CASCADE, related_name="responsabilites")
    animateur = models.ForeignKey(
        Animateur,
        on_delete=models.PROTECT,
        related_name="responsabilites_sorties",
    )
    type = models.CharField(max_length=12, choices=TYPE_CHOICES)
    centre = models.ForeignKey(
        Centre,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="responsabilites_sorties",
    )
    evenement = models.ForeignKey(
        Evenement,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="responsabilites_sorties",
    )
    affectation_creee = models.ForeignKey(
        Affectation,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="responsabilites_sorties_creees",
        help_text="Affectation ajoutée automatiquement lors de la nomination du responsable.",
    )
    ordre = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("ordre", "type", "centre__ordre", "evenement__ordre", "id")
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(type="direction", centre__isnull=True, evenement__isnull=True)
                    | models.Q(type="lieu", centre__isnull=False, evenement__isnull=True)
                    | models.Q(type="groupe", centre__isnull=True, evenement__isnull=False)
                ),
                name="responsabilite_sortie_perimetre_coherent",
            ),
            models.UniqueConstraint(
                fields=("sortie", "animateur"),
                condition=models.Q(type="direction"),
                name="unique_direction_anim_par_sortie",
            ),
            models.UniqueConstraint(
                fields=("sortie", "animateur", "centre"),
                condition=models.Q(type="lieu"),
                name="unique_lieu_anim_par_sortie",
            ),
            models.UniqueConstraint(
                fields=("sortie", "animateur", "evenement"),
                condition=models.Q(type="groupe"),
                name="unique_groupe_anim_par_sortie",
            ),
        ]

    def __str__(self):
        if self.type == self.TYPE_LIEU and self.centre_id:
            perimetre = self.centre.nom
        elif self.type == self.TYPE_GROUPE and self.evenement_id:
            perimetre = f"{self.evenement.centre.nom} — {self.evenement.nom}"
        else:
            perimetre = "Direction"
        return f"{self.animateur} — {perimetre}"


class SortieRenfort(models.Model):
    """Trace qu'une affectation Planning a été créée depuis une sortie."""

    sortie = models.ForeignKey(Sortie, on_delete=models.CASCADE, related_name="renforts")
    affectation = models.OneToOneField(
        Affectation,
        on_delete=models.CASCADE,
        related_name="renfort_sortie",
    )
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("affectation__animateur__nom", "affectation__animateur__prenom", "id")


class SortieParticipation(models.Model):
    sortie = models.ForeignKey(Sortie, on_delete=models.CASCADE, related_name="participations")
    evenement = models.ForeignKey(Evenement, on_delete=models.PROTECT, related_name="participations_sorties")
    activite_horaire = models.CharField(max_length=240, blank=True, default="")

    class Meta:
        ordering = ("evenement__centre__ordre", "evenement__ordre", "evenement__nom")
        constraints = [
            models.UniqueConstraint(fields=("sortie", "evenement"), name="unique_groupe_par_sortie"),
        ]


class SortieLien(models.Model):
    sortie = models.ForeignKey(Sortie, on_delete=models.CASCADE, related_name="liens")
    libelle = models.CharField(max_length=120)
    url = models.URLField(max_length=500)
    ordre = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("ordre", "id")


class ModeleEmail(models.Model):
    """Modèle réutilisable pour préparer rapidement un e-mail personnalisé."""

    nom = models.CharField(max_length=120, unique=True)
    objet = models.CharField(max_length=200)
    message = models.TextField()
    actif = models.BooleanField(default=True)
    types_accueil = models.ManyToManyField(
        TypeAccueil,
        related_name="modeles_email",
        blank=True,
        help_text="Vide signifie que le modèle reste utilisable dans tous les contextes.",
    )
    ordre = models.PositiveSmallIntegerField(default=0)
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("ordre", "nom")
        verbose_name = "modèle d’e-mail"
        verbose_name_plural = "modèles d’e-mail"

    def __str__(self):
        return self.nom


class ContactEmailExterne(models.Model):
    """Destinataire e-mail enregistré indépendamment des salariés."""

    prenom = models.CharField(max_length=100, blank=True)
    nom = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    organisation = models.CharField(max_length=150, blank=True)
    actif = models.BooleanField(default=True)
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nom", "prenom", "email"]
        verbose_name = "contact e-mail externe"
        verbose_name_plural = "contacts e-mail externes"

    def __str__(self):
        return f"{self.prenom} {self.nom}".strip() or self.email


class ProfilImportEffectifs(models.Model):
    """Correspondance Excel enregistrée par un utilisateur de direction."""

    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profils_import_effectifs",
    )
    nom = models.CharField(max_length=120)
    configuration = models.JSONField(default=dict)
    cree_le = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("nom",)
        constraints = [
            models.UniqueConstraint(
                fields=("utilisateur", "nom"),
                name="unique_profil_import_effectifs_par_utilisateur",
            )
        ]
        verbose_name = "profil d'import d'effectifs"
        verbose_name_plural = "profils d'import d'effectifs"

    def __str__(self):
        return self.nom


class Formation(models.Model):
    """Formation prévue puis clôturée avec la présence de chaque participant."""

    STATUT_PREVUE = "prevue"
    STATUT_EN_COURS = "en_cours"
    STATUT_A_CLOTURER = "a_cloturer"
    STATUT_TERMINEE = "terminee"
    STATUT_ANNULEE = "annulee"
    STATUT_CHOICES = (
        (STATUT_PREVUE, "Prévue"),
        (STATUT_EN_COURS, "En cours"),
        (STATUT_A_CLOTURER, "À clôturer"),
        (STATUT_TERMINEE, "Terminée"),
        (STATUT_ANNULEE, "Annulée"),
    )
    HEBERGEMENT_INTERNAT = "internat"
    HEBERGEMENT_EXTERNAT = "externat"
    HEBERGEMENT_CHOICES = (
        (HEBERGEMENT_INTERNAT, "Internat"),
        (HEBERGEMENT_EXTERNAT, "Externat"),
    )

    intitule = models.CharField(max_length=180)
    animateurs = models.ManyToManyField(
        Animateur,
        through="ParticipationFormation",
        related_name="formations",
        verbose_name="animateurs concernés",
    )
    date_debut = models.DateField()
    date_fin = models.DateField()
    organisme = models.CharField(max_length=180, blank=True)
    email_contact = models.EmailField(blank=True, verbose_name="e-mail du contact")
    telephone_contact = models.CharField(max_length=40, blank=True, verbose_name="téléphone du contact")
    lieu = models.CharField(max_length=180, blank=True)
    hebergement = models.CharField(max_length=12, choices=HEBERGEMENT_CHOICES, blank=True)
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default=STATUT_PREVUE)
    qualification = models.ForeignKey(
        Qualification,
        on_delete=models.SET_NULL,
        related_name="formations_liees",
        null=True,
        blank=True,
        verbose_name="qualification liée",
    )
    qualification_libre = models.CharField(
        max_length=180,
        blank=True,
        verbose_name="autre qualification / qualification libre",
    )
    documents = models.ManyToManyField(
        Document,
        related_name="formations",
        blank=True,
        help_text="Documents existants de la bibliothèque liés à cette formation.",
    )
    commentaire = models.TextField(blank=True, verbose_name="commentaire / notes")
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("date_debut", "intitule", "id")
        verbose_name = "formation"
        verbose_name_plural = "formations"

    def clean(self):
        super().clean()
        self.intitule = self.intitule.strip()
        erreurs = {}
        if not self.intitule:
            erreurs["intitule"] = "L’intitulé est obligatoire."
        if self.date_debut and self.date_fin and self.date_fin < self.date_debut:
            erreurs["date_fin"] = "La date de fin ne peut pas être antérieure à la date de début."
        if erreurs:
            raise ValidationError(erreurs)

    def __str__(self):
        return self.intitule

    def statut_calcule(self, aujourd_hui=None):
        """Statut visible : seules l'annulation et la clôture sont manuelles."""
        aujourd_hui = aujourd_hui or timezone.localdate()
        if self.statut == self.STATUT_ANNULEE:
            return self.STATUT_ANNULEE
        if self.statut == self.STATUT_TERMINEE:
            return self.STATUT_TERMINEE
        if aujourd_hui < self.date_debut:
            return self.STATUT_PREVUE
        if aujourd_hui <= self.date_fin:
            return self.STATUT_EN_COURS
        return self.STATUT_A_CLOTURER

    @property
    def statut_effectif(self):
        return self.statut_calcule()


class ParticipationFormation(models.Model):
    PRESENCE_A_CONFIRMER = "a_confirmer"
    PRESENCE_PRESENT = "present"
    PRESENCE_ABSENT = "absent"
    PRESENCE_CHOICES = (
        (PRESENCE_A_CONFIRMER, "À confirmer"),
        (PRESENCE_PRESENT, "Présent"),
        (PRESENCE_ABSENT, "Absent"),
    )

    formation = models.ForeignKey(Formation, on_delete=models.CASCADE, related_name="participations")
    animateur = models.ForeignKey(Animateur, on_delete=models.CASCADE, related_name="participations_formations")
    presence = models.CharField(max_length=16, choices=PRESENCE_CHOICES, default=PRESENCE_A_CONFIRMER)

    class Meta:
        ordering = ("animateur__nom", "animateur__prenom", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("formation", "animateur"),
                name="unique_participation_formation_animateur",
            )
        ]

    def __str__(self):
        return f"{self.formation} — {self.animateur} ({self.get_presence_display()})"
