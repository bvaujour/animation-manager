"""Moteur de préparation de paie, sans calcul de bulletin ni conversion brut/net."""

import calendar
import datetime
from collections import defaultdict
from decimal import Decimal

from django.db.models import Prefetch, Q

from animateurs.models import (
    Animateur,
    AttributionPrime,
    BaremeCEE,
    Contrat,
    Formation,
    HistoriqueStatutAnimateur,
    HistoriqueRemunerationContrat,
    ParticipationFormation,
    PrimeJournalierePeriode,
    ReferenceSMIC,
    BaremeApprentissage,
    TypeContrat,
)
from animateurs.services.contrats import situation_contractuelle_pour_date
from animateurs.services.parametres import get_parametres_structure
from animateurs.services.primes import nombre_jours_attribution_prime
from animateurs.services.statuts import situation_statut_pour_date
from animateurs.services.remunerations_contrats import (
    remuneration_apprentissage_pour_date,
    remuneration_mensualisee_pour_date,
)


ETAT_PRET = "pret"
ETAT_A_VERIFIER = "a_verifier"
ETAT_INCOMPLET = "incomplet"


def _jours(debut, fin):
    jour = debut
    while jour <= fin:
        yield jour
        jour += datetime.timedelta(days=1)


def _decimal(valeur):
    return Decimal(str(valeur or 0))


def _mois_civil_complet(debut, fin):
    return (
        debut.day == 1
        and debut.year == fin.year
        and debut.month == fin.month
        and fin.day == calendar.monthrange(fin.year, fin.month)[1]
    )


def _taux_prefetch(structure, statut, jour):
    if statut is None:
        return None
    baremes = getattr(structure, "_baremes_paie", [])
    return next(
        (item.montant_journalier for item in baremes if item.statut_id == statut.id and item.date_effet <= jour),
        None,
    )


def _alerte(alertes, niveau, code, message, date=None):
    cle = (niveau, code, message, date)
    if cle not in {(a["niveau"], a["code"], a["message"], a.get("date")) for a in alertes}:
        alertes.append({"niveau": niveau, "code": code, "message": message, "date": date})


def _charger_animateurs(ids, fin):
    historiques = HistoriqueStatutAnimateur.objects.select_related("statut").filter(
        date_effet__lte=fin
    ).order_by("-date_effet", "-id")
    remunerations = HistoriqueRemunerationContrat.objects.filter(date_effet__lte=fin).order_by(
        "-date_effet", "-id"
    )
    contrats = Contrat.objects.select_related("type_contrat_ref").filter(
        Q(date_debut__isnull=True) | Q(date_debut__lte=fin)
    ).prefetch_related(
        Prefetch("historique_remunerations", queryset=remunerations, to_attr="_historique_remunerations_paie")
    ).order_by("date_debut", "id")
    attributions = AttributionPrime.objects.select_related("type_prime", "centre").filter(
        date_debut__lte=fin
    )
    participations = ParticipationFormation.objects.select_related("formation").filter(
        formation__date_debut__lte=fin
    )
    return {
        item.id: item
        for item in Animateur.objects.filter(pk__in=ids).prefetch_related(
            "qualifications",
            Prefetch("historique_statuts", queryset=historiques, to_attr="_historique_statuts_dates"),
            Prefetch("contrats", queryset=contrats, to_attr="_contrats_paie"),
            Prefetch("attributions_primes", queryset=attributions, to_attr="_attributions_paie"),
            Prefetch("participations_formations", queryset=participations, to_attr="_participations_paie"),
        )
    }


def enrichir_recapitulatif_paie(recap, debut, fin, periodes=()):
    """Enrichit le récapitulatif existant avec les règles contractuelles datées."""

    structure = get_parametres_structure()
    structure._baremes_paie = list(
        BaremeCEE.objects.filter(structure=structure, date_effet__lte=fin)
        .select_related("statut").order_by("statut_id", "-date_effet", "-id")
    )
    structure._references_smic_paie = list(
        ReferenceSMIC.objects.filter(structure=structure, date_effet__lte=fin).order_by("-date_effet", "-id")
    )
    structure._baremes_apprentissage_paie = list(
        BaremeApprentissage.objects.filter(structure=structure, date_effet__lte=fin).order_by(
            "-date_effet", "annee_execution", "age_minimum", "id"
        )
    )
    ids = {item["id"] for item in recap["animateurs"]}
    ids.update(ParticipationFormation.objects.filter(
        formation__date_debut__lte=fin, formation__date_fin__gte=debut
    ).values_list("animateur_id", flat=True))
    ids.update(AttributionPrime.objects.filter(
        date_debut__lte=fin, date_fin__gte=debut
    ).values_list("animateur_id", flat=True))
    ids_existants = {item["id"] for item in recap["animateurs"]}
    for animateur in Animateur.objects.filter(pk__in=ids - ids_existants).order_by("prenom", "nom"):
        recap["animateurs"].append({
            "id": animateur.id, "prenom": animateur.prenom, "nom": animateur.nom,
            "paie_jour": None,
            "jours_affectation": 0, "jours_reunion": 0, "jours_preparation": 0,
            "dates_reunions_comptabilisees": [], "jours_travailles": 0,
            "paie_totale": None, "paie_base": None, "centres": [], "jours": [],
            "prime_jour": None, "prime_jour_variable": False,
            "total_jour_avec_prime": None, "montant_primes": "0.00",
            "primes_detail": [], "prime_modifiable": False, "total_paie_estime": None,
        })
    recap["animateurs"].sort(key=lambda item: (item["prenom"].casefold(), item["nom"].casefold()))
    animateurs = _charger_animateurs(ids, fin)
    anciennes_primes = {
        (item.animateur_id, item.periode_id): item
        for item in PrimeJournalierePeriode.objects.filter(
            animateur_id__in=animateurs, periode__in=periodes
        ).select_related("periode")
    }
    total_calcule = Decimal("0.00")
    total_primes = Decimal("0.00")
    incomplets = 0

    for ligne in recap["animateurs"]:
        animateur = animateurs[ligne["id"]]
        alertes = []
        jours_affectes = {datetime.date.fromisoformat(item["date"]) for item in ligne.get("jours", [])}
        jours_reunions = {datetime.date.fromisoformat(item) for item in ligne.get("dates_reunions_comptabilisees", [])}
        jours_payes_dates = sorted(jours_affectes | jours_reunions)
        unites_cee_par_jour = {
            jour: int(jour in jours_affectes) + int(jour in jours_reunions)
            for jour in jours_payes_dates
        }
        base_cee = Decimal("0.00")
        details_cee = defaultdict(lambda: {"jours": 0, "montant": Decimal("0.00")})
        situations = []
        reference_mensuelle = None
        base_mensuelle = None
        types = []
        remuneration_cee_par_jour = {}
        jours_cee_calcules = 0
        paie_habituelle = False
        valeurs_mensuelles = set()
        minimum_mensuel = None
        source_reference_mensuelle = None

        for jour in _jours(debut, fin):
            contractuelle = situation_contractuelle_pour_date(animateur, jour)
            jour_financier = jour in jours_payes_dates
            if jour_financier and contractuelle.type_contrat not in types:
                types.append(contractuelle.type_contrat)
            if jour_financier and not contractuelle.explicite:
                _alerte(
                    alertes, "information", "contrat_implicite",
                    "Contrat non renseigné — CEE appliqué par défaut",
                )
            taux = None
            statut = None
            salaire = None
            minimum = None
            source_reference = None
            if contractuelle.mode_remuneration == TypeContrat.MODE_CEE:
                statut_situation = situation_statut_pour_date(animateur, jour)
                statut = statut_situation.statut
                taux_contractuel = contractuelle.explicite and (
                    not structure.adapter_taux_cee_changement_statut
                    or statut_situation.source == "fallback_actuel"
                )
                if taux_contractuel:
                    # Un statut actuel sans historique daté ne peut pas
                    # remplacer le taux certain inscrit au contrat CEE.
                    taux = contractuelle.contrat.taux_journalier_reference
                    statut = None
                    if taux is None and jour_financier:
                        _alerte(
                            alertes, "incomplet", "taux_contractuel_manquant",
                            "Taux journalier contractuel CEE manquant.", jour.isoformat(),
                        )
                elif statut is None and jour_financier:
                    _alerte(
                        alertes, "incomplet", "statut_manquant",
                        "Statut non renseigné — impossible de déterminer le barème CEE.", jour.isoformat(),
                    )
                elif statut is not None:
                    if not statut_situation.fiable and jour_financier:
                        _alerte(
                            alertes, "verification", "statut_incertain",
                            "Statut historique incertain pour cette période.",
                        )
                    taux = _taux_prefetch(structure, statut, jour)
                    if taux is None and jour_financier:
                        _alerte(
                            alertes, "incomplet", "bareme_manquant",
                            f"Barème CEE manquant — {statut.nom} au {jour:%d/%m/%Y}.", jour.isoformat(),
                        )
                if jour in jours_payes_dates and taux is not None:
                    unites = unites_cee_par_jour[jour]
                    base_cee += taux * unites
                    jours_cee_calcules += unites
                    statut_nom = statut.nom if statut else "Taux contractuel"
                    remuneration_cee_par_jour[jour] = (statut_nom, taux)
                    cle = (statut_nom, str(taux))
                    details_cee[cle]["jours"] += unites
                    details_cee[cle]["montant"] += taux * unites
            elif contractuelle.mode_remuneration == TypeContrat.MODE_PAIE_HABITUELLE:
                paie_habituelle = paie_habituelle or jour_financier
            elif jour_financier:
                if contractuelle.mode_remuneration == TypeContrat.MODE_APPRENTISSAGE:
                    reference = remuneration_apprentissage_pour_date(
                        contractuelle.contrat, jour, structure
                    )
                else:
                    reference = remuneration_mensualisee_pour_date(
                        contractuelle.contrat, jour, structure
                    )
                salaire = reference.montant_retenu
                minimum = reference.minimum_calcule
                source_reference = reference.source
                reference_mensuelle = salaire
                minimum_mensuel = minimum
                source_reference_mensuelle = source_reference
                if salaire is not None:
                    valeurs_mensuelles.add(salaire)
                for message in reference.alertes:
                    niveau = "verification" if salaire is not None else "incomplet"
                    code = "reference_contractuelle"
                    if "SMIC manquante" in message:
                        code = "smic_manquant"
                    elif "Barème apprentissage" in message:
                        code = "bareme_apprentissage_manquant"
                    elif "naissance" in message:
                        code = "date_naissance_manquante"
                    elif "exécution" in message:
                        code = "annee_execution_manquante"
                    elif "inférieur" in message:
                        code = "minimum_smic"
                    _alerte(alertes, niveau, code, message)
                if salaire is None and not reference.alertes:
                    _alerte(
                        alertes, "incomplet", "salaire_mensuel_manquant",
                        f"Salaire mensuel de référence {contractuelle.libelle} manquant.",
                    )
            if jour_financier:
                situations.append((
                    jour, contractuelle.type_contrat, getattr(contractuelle.contrat, "id", None),
                    taux, statut, contractuelle.explicite,
                    salaire, contractuelle.mode_remuneration, minimum, source_reference,
                ))

        modes_mensualises = {TypeContrat.MODE_MENSUALISE, TypeContrat.MODE_APPRENTISSAGE}
        jours_preparation = _decimal(ligne.get("jours_preparation"))
        if jours_preparation and situations and all(item[7] == TypeContrat.MODE_CEE for item in situations):
            _, _, _, taux_preparation, statut_preparation, _, _, _, _, _ = situations[-1]
            if taux_preparation is not None:
                montant_preparation = (jours_preparation * taux_preparation).quantize(Decimal("0.01"))
                base_cee += montant_preparation
                jours_cee_calcules += jours_preparation
                statut_nom = statut_preparation.nom if statut_preparation else "Taux contractuel"
                cle = (statut_nom, str(taux_preparation))
                details_cee[cle]["jours"] += jours_preparation
                details_cee[cle]["montant"] += montant_preparation
        if any(item[7] in modes_mensualises for item in situations):
            contrats_mensuels = {item[2] for item in situations if item[7] in modes_mensualises}
            meme_contrat_mensuel = len(contrats_mensuels) == 1
            tout_mensualise = all(item[7] in modes_mensualises for item in situations)
            contrat_mensuel = next(
                (item for item in getattr(animateur, "_contrats_paie", []) if item.id in contrats_mensuels),
                None,
            )
            couvre_periode = bool(
                contrat_mensuel
                and (contrat_mensuel.date_debut is None or contrat_mensuel.date_debut <= debut)
                and (contrat_mensuel.date_fin is None or contrat_mensuel.date_fin >= fin)
            )
            if (
                _mois_civil_complet(debut, fin) and tout_mensualise
                and meme_contrat_mensuel and couvre_periode and len(valeurs_mensuelles) == 1
            ):
                base_mensuelle = reference_mensuelle
            else:
                _alerte(
                    alertes, "verification", "mensualise_partiel",
                    "Salaire mensuel de référence — période sélectionnée différente d'un mois complet.",
                )
            if len(valeurs_mensuelles) > 1:
                _alerte(
                    alertes, "verification", "remuneration_mensuelle_changeante",
                    "Plusieurs références mensuelles s'appliquent sur la période.",
                )

        jours_formation = set()
        formations_detail = []
        for participation in getattr(animateur, "_participations_paie", []):
            formation = participation.formation
            if formation.date_fin < debut or formation.date_debut > fin:
                continue
            if formation.statut_calcule(fin) == Formation.STATUT_A_CLOTURER:
                _alerte(alertes, "verification", "formation_a_cloturer", f"Formation à clôturer — {formation.intitule}")
            if formation.statut == Formation.STATUT_TERMINEE and participation.presence == ParticipationFormation.PRESENCE_PRESENT:
                dates = set(_jours(max(debut, formation.date_debut), min(fin, formation.date_fin)))
                jours_formation |= dates
                formations_detail.append({"intitule": formation.intitule, "jours": len(dates)})

        primes = []
        montant_primes = Decimal("0.00")
        for attribution in getattr(animateur, "_attributions_paie", []):
            if attribution.date_fin < debut or attribution.date_debut > fin:
                continue
            montant_primes += attribution.montant_total
            primes.append({
                "id": attribution.id,
                "type_prime_id": attribution.type_prime_id,
                "nom": attribution.type_prime.nom,
                "mode": attribution.mode_calcul,
                "montant_unitaire": str(attribution.montant_unitaire),
                "montant_total": str(attribution.montant_total),
                "nombre_jours": nombre_jours_attribution_prime(attribution),
                "date_debut": attribution.date_debut.isoformat(),
                "date_fin": attribution.date_fin.isoformat(),
                "centre_id": attribution.centre_id,
                "historique": False,
            })

        # Compatibilité en lecture : l'ancien stockage reste intact car son
        # total ne peut pas être figé rétroactivement avec certitude.
        anciennes = [
            anciennes_primes[(animateur.id, periode.id)]
            for periode in periodes if (animateur.id, periode.id) in anciennes_primes
        ]
        for ancienne in anciennes:
            nombre_jours = sum(1 for jour in jours_affectes if ancienne.periode.debut <= jour <= ancienne.periode.fin)
            nombre_jours += sum(1 for jour in jours_reunions if ancienne.periode.debut <= jour <= ancienne.periode.fin)
            total = ancienne.montant * nombre_jours
            montant_primes += total
            primes.append({
                "id": None, "nom": "Prime d'autonomie (historique)", "mode": "jour",
                "montant_unitaire": str(ancienne.montant), "montant_total": str(total),
                "date_debut": ancienne.periode.debut.isoformat(), "date_fin": ancienne.periode.fin.isoformat(),
                "historique": True,
            })

        cp_cee = (base_cee * structure.taux_indemnite_cp_cee / Decimal("100")).quantize(Decimal("0.01"))
        calculable = base_cee + cp_cee + montant_primes
        if base_mensuelle is not None:
            calculable += base_mensuelle
        etat = ETAT_PRET
        if any(item["niveau"] == "incomplet" for item in alertes):
            etat = ETAT_INCOMPLET
            incomplets += 1
        elif any(item["niveau"] == "verification" for item in alertes):
            etat = ETAT_A_VERIFIER

        segments = []
        contrats_par_id = {item.id: item for item in getattr(animateur, "_contrats_paie", [])}
        for (
            jour, type_contrat, contrat_id, taux, statut, explicite,
            salaire_mensuel, mode_paie, minimum_calcule, source_reference,
        ) in situations:
            cle = (
                type_contrat, contrat_id, str(taux) if taux is not None else None,
                getattr(statut, "id", None), explicite,
                str(salaire_mensuel) if salaire_mensuel is not None else None,
                mode_paie, str(minimum_calcule) if minimum_calcule is not None else None,
                source_reference,
            )
            if segments and segments[-1]["_cle"] == cle and datetime.date.fromisoformat(segments[-1]["date_fin"]) + datetime.timedelta(days=1) == jour:
                segments[-1]["date_fin"] = jour.isoformat()
            else:
                contrat_segment = contrats_par_id.get(contrat_id)
                segments.append({
                    "_cle": cle, "date_debut": jour.isoformat(), "date_fin": jour.isoformat(),
                    "type_contrat": type_contrat, "contrat_id": contrat_id, "explicite": explicite,
                    "type_contrat_libelle": contrat_segment.libelle_type if contrat_segment else "CEE",
                    "mode_paie": mode_paie,
                    "contrat_date_debut": (
                        contrat_segment.date_debut.isoformat()
                        if contrat_segment and contrat_segment.date_debut else None
                    ),
                    "contrat_date_fin": (
                        contrat_segment.date_fin.isoformat()
                        if contrat_segment and contrat_segment.date_fin else None
                    ),
                    "statut": statut.nom if statut else None,
                    "taux_journalier": str(taux) if taux is not None else None,
                    "salaire_mensuel_reference": (
                        str(salaire_mensuel) if salaire_mensuel is not None else None
                    ),
                    "minimum_calcule": str(minimum_calcule) if minimum_calcule is not None else None,
                    "source_reference": source_reference,
                })
        for segment in segments:
            segment.pop("_cle", None)

        centres_par_id = {item["centre_id"]: item for item in ligne.get("centres", [])}
        details_centres = defaultdict(lambda: defaultdict(lambda: {"jours": 0, "montant": Decimal("0.00")}))
        for jour_item in ligne.get("jours", []):
            jour = datetime.date.fromisoformat(jour_item["date"])
            remuneration = remuneration_cee_par_jour.get(jour)
            lieux = jour_item.get("lieux", [])
            if remuneration and lieux:
                # Une journée multi-centres n'est financièrement imputée qu'une
                # fois, au premier centre de la ventilation déjà ordonnée.
                statut_nom, taux = remuneration
                detail = details_centres[lieux[0]["id"]][(statut_nom, str(taux))]
                detail["jours"] += 1
                detail["montant"] += taux
        for centre_id, centre in centres_par_id.items():
            centre["details_cee"] = [
                {"statut": cle[0], "taux": cle[1], "jours": valeur["jours"], "montant": str(valeur["montant"])}
                for cle, valeur in details_centres[centre_id].items()
            ]
            centre["base_cee"] = str(sum(
                (valeur["montant"] for valeur in details_centres[centre_id].values()), Decimal("0.00")
            ).quantize(Decimal("0.01")))

        remuneration_calculee = bool(jours_cee_calcules) or base_mensuelle is not None
        base_preparee = base_cee + (base_mensuelle or Decimal("0.00"))
        ligne.update({
            "types_contrat": types,
            "type_contrat": types[0] if len(types) == 1 else "mixte",
            "type_contrat_libelle": " / ".join(
                "Apprentissage / alternance" if item == Contrat.TYPE_APPRENTISSAGE
                else dict(Contrat.TYPE_CHOICES).get(item, item)
                for item in types
            ),
            "segments_contractuels": segments,
            "base_cee": str(base_cee.quantize(Decimal("0.01"))),
            "details_cee": [
                {"statut": cle[0], "taux": cle[1], "jours": valeur["jours"], "montant": str(valeur["montant"])}
                for cle, valeur in details_cee.items()
            ],
            "taux_cp_cee": str(structure.taux_indemnite_cp_cee),
            "indemnite_cp_cee": str(cp_cee),
            "salaire_mensuel_reference": str(reference_mensuelle) if reference_mensuelle is not None else None,
            "base_mensuelle_reference": str(base_mensuelle) if base_mensuelle is not None else None,
            "minimum_mensuel_calcule": str(minimum_mensuel) if minimum_mensuel is not None else None,
            "source_reference_mensuelle": source_reference_mensuelle,
            "paie_habituelle": paie_habituelle,
            "montant_primes_preparees": str(montant_primes.quantize(Decimal("0.01"))),
            "attributions_primes": primes,
            "jours_formation": len(jours_formation),
            "formations_detail": formations_detail,
            "alertes_paie": alertes,
            "etat_preparation": etat,
            "total_prepare": str(calculable.quantize(Decimal("0.01"))) if etat != ETAT_INCOMPLET else None,
            "base_preparee": str(base_preparee.quantize(Decimal("0.01"))) if remuneration_calculee else None,
            "reference_mensuelle_a_ajuster": reference_mensuelle is not None and base_mensuelle is None,
        })
        total_primes += montant_primes
        if etat != ETAT_INCOMPLET:
            total_calcule += calculable

    recap["total_prepare"] = str(total_calcule.quantize(Decimal("0.01")))
    recap["total_primes_preparees"] = str(total_primes.quantize(Decimal("0.01")))
    recap["preparations_incompletes"] = incomplets
    return recap
