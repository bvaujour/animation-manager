"""Copie limitée aux configurations explicitement rattachées à une période."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from datetime import date as date_value

from animateurs.models import (
    AccueilCentre, AnneeScolaire, BesoinEncadrement, BesoinQualification,
    Centre, Groupe, OuvertureCentrePeriode, PeriodeCalendrier,
)
from .calendrier_scolaire import CalendrierScolaireError, calculer_periodes_scolaires, recuperer_semaines


def calendrier_officiel(libelle, zone):
    """Retourne les périodes calculées par le service officiel, sans écriture."""
    semaines = recuperer_semaines(libelle, zone)
    try:
        periodes = calculer_periodes_scolaires(libelle, semaines)
    except (ValueError, TypeError, OverflowError) as erreur:
        raise CalendrierScolaireError("Le calcul des périodes scolaires officielles a échoué.") from erreur
    if not periodes:
        raise CalendrierScolaireError("Aucune période scolaire officielle n’a pu être calculée.")
    return {"periodes": periodes, "semaines": semaines}


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
    from .multisite import multisite_actif
    if not multisite_actif() and len(set(centres)) > 1:
        raise ValidationError("Le mode mono-site ne permet de reprendre qu’un seul centre.")
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
    evenements = list(__import__("animateurs.models", fromlist=["Evenement"]).Evenement.objects.filter(
        centre_id__in=centres,
        groupe__type_groupe=Groupe.TYPE_STRUCTURE,
    ).filter(Q(accueil_centre_id__in=accueils) | Q(accueil_centre__isnull=True)).prefetch_related("periodes_scolaires"))
    accueils_tous = AccueilCentre.objects.filter(centre_id__in=centres)
    accueils_repris = set(accueils)
    groupes_partages = {e.groupe_id for e in evenements if e.groupe.portee == Groupe.PARTAGE}
    groupes_locaux = {e.groupe_id for e in evenements if e.groupe.portee == Groupe.LOCAL}
    return {"lignes": lignes, "periodes": periodes, "dates": dates, "evenements": evenements,
            "source_libelle": source.libelle, "source_date_debut": source.date_debut,
            "resume": [(CATEGORIES[code][1], len(items)) for code, items in lignes.items()],
            "centres": list(Centre.objects.filter(pk__in=centres)),
            "accueils": list(AccueilCentre.objects.filter(pk__in=accueils, centre_id__in=centres)),
            "accueils_ignores": list(accueils_tous.exclude(pk__in=accueils_repris)),
            "groupes_partages": list(Groupe.objects.filter(pk__in=groupes_partages)),
            "groupes_locaux": list(Groupe.objects.filter(pk__in=groupes_locaux)),
            "mode_multisite": multisite_actif()}


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
    calendrier = plan.get("calendrier_officiel") or {}
    calendrier_officiel = calendrier.get("periodes", []) if isinstance(calendrier, dict) else calendrier
    periodes_creees = set()
    for entree in calendrier_officiel:
        debut = date_value.fromisoformat(entree["debut"])
        fin = date_value.fromisoformat(entree["fin"])
        periode, _ = PeriodeCalendrier.objects.get_or_create(
            categorie=PeriodeCalendrier.SCOLAIRE, annee_scolaire=cible.libelle,
            zone=plan.get("zone", "A"), debut=debut, fin=fin,
            defaults={"nom": entree["nom"]},
        )
        periodes_creees.add(periode.pk)
    for source in plan["periodes"]:
        debut, fin = plan["dates"][source.pk]
        periode = PeriodeCalendrier(
            categorie=source.categorie, nom=source.nom, zone=source.zone,
            annee_scolaire=cible.libelle, debut=debut, fin=fin,
        )
        periode, _ = PeriodeCalendrier.objects.get_or_create(
            categorie=periode.categorie, annee_scolaire=periode.annee_scolaire,
            zone=periode.zone, debut=periode.debut, fin=periode.fin,
            defaults={"nom": periode.nom},
        )
        periode.types_accueil.set(source.types_accueil.all())
        correspondance[source.pk] = periode.pk
    # Les semaines officielles sont créées dans la cible, sans toucher à la source.
    # leurs lignes datées sont recréées, jamais la définition du groupe.
    from animateurs.models import PeriodeScolaire, TypeAccueil
    type_vacances, _ = TypeAccueil.objects.get_or_create(code=TypeAccueil.VACANCES, defaults={"nom": "Vacances", "ordre": 10, "actif": True})
    semaines = {}
    for semaine_source in (calendrier.get("semaines", []) if isinstance(calendrier, dict) else []):
        semaine, _ = PeriodeScolaire.objects.get_or_create(
            annee_scolaire=cible.libelle, zone=plan.get("zone", "A"),
            debut=semaine_source.debut, fin=semaine_source.fin,
            defaults={"nom": semaine_source.nom, "description_source": semaine_source.description_source,
                      "ordre": semaine_source.numero, "type_accueil_id": type_vacances.pk if type_vacances else None},
        )
        semaines[(semaine_source.debut, semaine_source.fin)] = semaine
    decalage = cible.date_debut.year - plan["source_date_debut"].year
    for evenement in plan.get("evenements", []):
        cibles = []
        for source_semaine in evenement.periodes_scolaires.all():
            # Un événement partagé peut déjà couvrir plusieurs années. Seule
            # l'année choisie est reprise ; les autres liens restent intacts.
            if source_semaine.annee_scolaire != plan["source_libelle"]:
                continue
            try:
                debut = source_semaine.debut.replace(year=source_semaine.debut.year + decalage)
                fin = source_semaine.fin.replace(year=source_semaine.fin.year + decalage)
            except ValueError:
                continue
            if not cible.date_debut <= debut <= fin <= cible.date_fin:
                raise ValidationError(f"La période reprise « {source_semaine.nom} » dépasse les limites de l’année cible.")
            semaine, _ = PeriodeScolaire.objects.get_or_create(
                annee_scolaire=cible.libelle,
                zone=plan.get("zone", source_semaine.zone), debut=debut, fin=fin,
                defaults={"nom": source_semaine.nom, "description_source": source_semaine.description_source,
                          "ordre": source_semaine.ordre, "type_accueil_id": source_semaine.type_accueil_id},
            )
            cibles.append(semaine)
        if cibles:
            evenement.periodes_scolaires.add(*cibles)
    for code, lignes in plan["lignes"].items():
        modele, _, champs = CATEGORIES[code]
        for source in lignes:
            copie = modele(**{champ: getattr(source, champ) for champ in champs},
                           periode_calendrier_id=correspondance[source.periode_calendrier_id])
            copie.full_clean()
            copie.save()
    return cible
