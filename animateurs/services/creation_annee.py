"""Copie limitée aux configurations explicitement rattachées à une période."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from animateurs.models import (
    AccueilCentre, AnneeScolaire, BesoinEncadrement, BesoinQualification,
    Centre, Groupe, OuvertureCentrePeriode, PeriodeCalendrier,
)


CATEGORIES = {
    "horaires": (OuvertureCentrePeriode, "Horaires d’ouverture", (
        "centre_id", "accueil_centre_id", "modalite_periscolaire_id",
        "jour_semaine", "heure_debut", "heure_fin", "actif",
    )),
    "besoins": (BesoinEncadrement, "Besoins d’encadrement annuels", (
        "evenement_id", "type_accueil_id", "modalite_periscolaire_id", "effectif_cible",
        "mode_calcul", "effectif_enfants_reference", "renforts_souhaites",
    )),
    "qualifications": (BesoinQualification, "Exigences de qualification annuelles", (
        "evenement_id", "qualification_id", "nombre_minimum", "type_accueil_id", "modalite_periscolaire_id",
    )),
}


def accueils_reutilisables(source, cible):
    # Les accueils datés doivent couvrir les deux années ; aucune prolongation
    # d'un accueil terminé n'est faite implicitement par l'assistant.
    return AccueilCentre.objects.filter(
        Q(date_debut__isnull=True) | Q(date_debut__lte=source.date_fin),
        Q(date_fin__isnull=True) | Q(date_fin__gte=cible.date_fin),
        Q(date_debut__isnull=True) | Q(date_debut__lte=cible.date_debut),
    ).select_related("centre", "type_accueil")


def preparer_copie(cible, source, centres, accueils, categories, dates):
    """Construit le récapitulatif et les seules lignes autorisées à être copiées."""
    lignes = {}
    for code in categories:
        modele = CATEGORIES[code][0]
        qs = modele.objects.filter(periode_calendrier__annee_scolaire=source.libelle)
        if code == "horaires":
            qs = qs.filter(centre_id__in=centres).filter(Q(accueil_centre_id__in=accueils) | Q(accueil_centre__isnull=True))
        else:
            qs = qs.filter(evenement__centre_id__in=centres, evenement__groupe__type_groupe=Groupe.TYPE_STRUCTURE)
            qs = qs.filter(Q(evenement__accueil_centre_id__in=accueils) | Q(evenement__accueil_centre__isnull=True))
        lignes[code] = list(qs.order_by("pk"))
    ids = {item.periode_calendrier_id for items in lignes.values() for item in items}
    periodes = list(PeriodeCalendrier.objects.filter(pk__in=ids).order_by("debut", "pk"))
    for periode in periodes:
        debut, fin = dates[periode.pk]
        if not cible.date_debut <= debut <= fin <= cible.date_fin:
            raise ValidationError(f"Les dates de « {periode.nom} » doivent être comprises dans la nouvelle année.")
        if not source.date_debut <= periode.debut <= periode.fin <= source.date_fin:
            raise ValidationError(f"La période source « {periode.nom} » dépasse les limites de l’année source.")
    return {"lignes": lignes, "periodes": periodes, "dates": dates,
            "resume": [(CATEGORIES[code][1], len(items)) for code, items in lignes.items()],
            "centres": list(Centre.objects.filter(pk__in=centres)),
            "accueils": list(AccueilCentre.objects.filter(pk__in=accueils, centre_id__in=centres))}


@transaction.atomic
def creer_annee(cible, plan=None):
    """Ne modifie aucune référence partagée ni ligne source."""
    cible.statut = AnneeScolaire.Statut.PREPARATION
    cible.date_cloture = None
    cible.full_clean()
    cible.save(force_insert=True)
    if plan is None:
        return cible
    correspondance = {}
    for source in plan["periodes"]:
        debut, fin = plan["dates"][source.pk]
        periode = PeriodeCalendrier(
            categorie=source.categorie, nom=source.nom, zone=source.zone,
            annee_scolaire=cible.libelle, debut=debut, fin=fin,
        )
        periode.full_clean()
        periode.save()
        periode.types_accueil.set(source.types_accueil.all())
        correspondance[source.pk] = periode.pk
    for code, lignes in plan["lignes"].items():
        modele, _, champs = CATEGORIES[code]
        for source in lignes:
            copie = modele(**{champ: getattr(source, champ) for champ in champs},
                           periode_calendrier_id=correspondance[source.periode_calendrier_id])
            copie.full_clean()
            copie.save()
    return cible
