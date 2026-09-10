"""Copie limitée aux configurations explicitement rattachées à une période."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from datetime import date as date_value, timedelta

from animateurs.models import (
    AccueilCentre, AnneeScolaire, BesoinEncadrement, BesoinQualification,
    Centre, Groupe, OuvertureCentrePeriode, PeriodeCalendrier, PeriodeScolaire,
)
from .calendrier_scolaire import (
    CalendrierScolaireError, SemaineVacances, calculer_periodes_scolaires,
    recuperer_semaines, regrouper_semaines_vacances,
)


def calendrier_officiel(libelle, zone):
    """Retourne les périodes calculées par le service officiel, sans écriture."""
    reponse = recuperer_semaines(libelle, zone, inclure_bornes=True)
    debut_ete = next((semaine.debut for semaine in reponse if semaine.numero == 0), None)
    semaines = [semaine for semaine in reponse if semaine.numero]
    try:
        periodes = calculer_periodes_scolaires(libelle, semaines)
    except (ValueError, TypeError, OverflowError) as erreur:
        raise CalendrierScolaireError("Le calcul des périodes scolaires officielles a échoué.") from erreur
    if not periodes:
        raise CalendrierScolaireError("Aucune période scolaire officielle n’a pu être calculée.")
    return {"periodes": periodes, "semaines": semaines, "debut_ete": debut_ete}


def _lundi_suivant(jour):
    return jour + timedelta(days=(7 - jour.weekday()) % 7)


def _cle_semaine(semaine):
    """Clé stable entre les semaines officielles de deux années."""
    nom, separateur, numero = semaine.nom.rpartition("— Semaine")
    if separateur and numero.strip().isdigit():
        return (nom.strip(), int(numero.strip()))
    return (semaine.nom, getattr(semaine, "numero", getattr(semaine, "ordre", 0)))


def proposer_semaines_ete(source, cible, evenements, debut_ete):
    """Propose tout l'été ; l'année source détermine seulement les suggestions."""
    if not debut_ete:
        return []
    source_semaines = {}
    for evenement in evenements:
        for semaine in evenement.periodes_scolaires.all():
            if semaine.annee_scolaire != source.libelle:
                continue
            texte = f"{semaine.nom} {semaine.description_source}".casefold()
            if "été" not in texte and "ete" not in texte:
                continue
            source_semaines.setdefault(semaine.pk, {"semaine": semaine, "evenements": []})["evenements"].append(evenement)
    premier_cible = _lundi_suivant(debut_ete)
    dernier_jour = date_value(cible.date_fin.year, 8, 31)
    suggestions = {}
    if source_semaines:
        premier_source = min(item["semaine"].debut for item in source_semaines.values())
        for item in source_semaines.values():
            position = (item["semaine"].debut - premier_source).days // 7
            suggestions[position] = item
    candidats = []
    position = 0
    while True:
        debut = premier_cible + timedelta(days=position * 7)
        fin = debut + timedelta(days=4)
        if fin > dernier_jour or fin > cible.date_fin:
            break
        item = suggestions.get(position)
        candidats.append({"id": str(position), "nom": f"Été — Semaine {position + 1}",
                          "debut": debut, "fin": fin, "suggeree": item is not None,
                          "source_ids": [item["semaine"].pk] if item else [],
                          "evenement_ids": [e.pk for e in item["evenements"]] if item else []})
        position += 1
    return candidats


def previsualiser_calendrier(cible, zone, calendrier, semaines_ete=()):
    """Décrit les objets générés ou existants, sans recalcul ni écriture."""
    periodes = list(PeriodeCalendrier.objects.filter(annee_scolaire=cible.libelle, zone=zone))
    semaines_existantes = list(PeriodeScolaire.objects.filter(
        annee_scolaire=cible.libelle, zone=zone).select_related("type_accueil", "periode_calendrier"))
    dates_existantes = {(s.debut, s.fin) for s in semaines_existantes}
    scolaires = []
    for entree in calendrier["periodes"]:
        reutilisee = any(p.categorie == PeriodeCalendrier.SCOLAIRE
            and p.debut.isoformat() == entree["debut"] and p.fin.isoformat() == entree["fin"] for p in periodes)
        scolaires.append({**entree, "reutilisee": reutilisee})

    # Les vacances sont déjà représentées par des semaines dans le plan de
    # création. Leur regroupement est uniquement visuel, pas un nouvel objet.
    semaines = {(s.debut, s.fin): s for s in calendrier["semaines"]}
    for ete in semaines_ete:
        semaines[(ete["debut"], ete["fin"])] = SemaineVacances(
            ete["nom"], ete["debut"], ete["fin"], "Vacances d'Été", int(ete["id"]) + 1)
    for s in semaines_existantes:
        if (s.type_accueil and s.type_accueil.code == "vacances") or (
                s.periode_calendrier and s.periode_calendrier.categorie == PeriodeCalendrier.VACANCES):
            semaines.setdefault((s.debut, s.fin), SemaineVacances(
                s.nom, s.debut, s.fin, s.description_source, s.ordre))
    vacances = []
    for p in periodes:
        if p.categorie != PeriodeCalendrier.VACANCES:
            continue
        couvertes = [s for s in semaines.values() if p.debut <= s.debut <= s.fin <= p.fin]
        vacances.append({"nom": p.nom, "debut": p.debut.isoformat(), "fin": p.fin.isoformat(),
                         "periode_existante": True, "semaines": [s.to_dict() for s in couvertes]})
        for s in couvertes:
            semaines.pop((s.debut, s.fin))
    for groupe in regrouper_semaines_vacances(sorted(semaines.values(), key=lambda s: s.debut)):
        vacances.append({**groupe, "debut": min(s["debut"] for s in groupe["semaines"]),
                         "fin": max(s["fin"] for s in groupe["semaines"]), "periode_existante": False})
    for vacance in vacances:
        for semaine in vacance["semaines"]:
            semaine["reutilisee"] = (date_value.fromisoformat(semaine["debut"]),
                                     date_value.fromisoformat(semaine["fin"])) in dates_existantes
        vacance["creees"] = sum(not s["reutilisee"] for s in vacance["semaines"])
        vacance["reutilisees"] = sum(s["reutilisee"] for s in vacance["semaines"])
    return {"scolaires": scolaires, "vacances": sorted(vacances, key=lambda v: v["debut"]),
            "vacances_sans_dates": [nom for nom in ("Toussaint", "Noël", "Hiver", "Printemps", "Été")
                                    if not any(v["nom"].startswith(nom) for v in vacances)],
            "scolaires_creees": sum(not p["reutilisee"] for p in scolaires),
            "scolaires_reutilisees": sum(p["reutilisee"] for p in scolaires),
            "semaines_creees": sum(v["creees"] for v in vacances),
            "semaines_reutilisees": sum(v["reutilisees"] for v in vacances)}


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

    # Les semaines d'été viennent exclusivement de la sélection prévisualisée.
    # Elles ne décalent jamais les dates historiques d'une année à l'autre.
    semaines_ete = {}
    for entree in plan.get("semaines_ete", []):
        debut, fin = entree["debut"], entree["fin"]
        if debut.weekday() != 0 or fin != debut + timedelta(days=4):
            raise ValidationError("Les semaines estivales doivent aller du lundi au vendredi.")
        semaine, _ = PeriodeScolaire.objects.get_or_create(
            annee_scolaire=cible.libelle, zone=plan.get("zone", "A"), debut=debut, fin=fin,
            defaults={"nom": entree["nom"], "description_source": "Vacances d'Été",
                      "ordre": int(entree["id"]) + 1, "type_accueil_id": type_vacances.pk},
        )
        semaines_ete[entree["id"]] = (semaine, set(entree["evenement_ids"]))

    # Les autres vacances réutilisent leur semaine officielle correspondante,
    # identifiée par son libellé et son numéro, jamais par un décalage de date.
    semaines_cibles = {_cle_semaine(s): s for s in (calendrier.get("semaines", []) if isinstance(calendrier, dict) else [])}
    liens_ete = {evenement_id: [] for _, (_, evenement_ids) in semaines_ete.items() for evenement_id in evenement_ids}
    for semaine, evenement_ids in semaines_ete.values():
        for evenement_id in evenement_ids:
            liens_ete.setdefault(evenement_id, []).append(semaine)
    for evenement in plan.get("evenements", []):
        cibles = []
        for source_semaine in evenement.periodes_scolaires.all():
            # Un événement partagé peut déjà couvrir plusieurs années. Seule
            # l'année choisie est reprise ; les autres liens restent intacts.
            if source_semaine.annee_scolaire != plan["source_libelle"]:
                continue
            cle = _cle_semaine(source_semaine)
            if cle in semaines_cibles:
                cibles.append(semaines[(semaines_cibles[cle].debut, semaines_cibles[cle].fin)])
        cibles.extend(liens_ete.get(evenement.pk, []))
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
