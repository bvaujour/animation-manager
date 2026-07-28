"""Synthèse des jours planifiés et de la paie par animateur et par lieu."""

from __future__ import annotations

import datetime
from collections import defaultdict
from decimal import Decimal
from io import BytesIO

from django.utils import timezone

from animateurs.models import Affectation, ActiviteTravailComplementaire
from animateurs.services.flottants import est_groupe_flottants


def _jours_entre(debut: datetime.date, fin_exclusive: datetime.date):
    """Itère de ``debut`` inclus à ``fin_exclusive`` exclu."""

    jour = debut
    while jour < fin_exclusive:
        yield jour
        jour += datetime.timedelta(days=1)


def _montant(jours: int, paie_jour):
    """Calcule un montant sérialisable, ou ``None`` si le tarif manque."""

    if paie_jour is None:
        return None
    return str((Decimal(jours) * paie_jour).quantize(Decimal("0.01")))


def _nombre_json(nombre):
    """Conserve des entiers lisibles tout en autorisant les demi-journées."""

    valeur = Decimal(nombre)
    return int(valeur) if valeur == valeur.to_integral_value() else float(valeur)


def generer_recapitulatif(debut, fin, jours_selectionnes=None, periode_ids=None):
    """Retourne les jours et la paie par animateur, ventilés par centre.

    ``debut`` est inclus et ``fin`` est exclusif. Une même date ne compte
    qu'une fois par animateur et par centre, même si plusieurs groupes du même
    centre lui sont affectés ce jour-là. Le total animateur compte également
    chaque date une seule fois.
    """

    debut_date = debut.date()
    fin_date = fin.date()
    jours_autorises = set(_jours_entre(debut_date, fin_date))
    if jours_selectionnes is not None:
        jours_autorises &= set(jours_selectionnes)

    affectations = (
        Affectation.objects.select_related("animateur", "centre", "evenement")
        .filter(debut__lt=fin, fin__gt=debut)
        .order_by("animateur__prenom", "animateur__nom", "debut")
    )

    jours_par_animateur = defaultdict(set)
    jours_par_animateur_centre = defaultdict(lambda: defaultdict(set))
    details_par_animateur = defaultdict(lambda: defaultdict(dict))
    animateurs = {}
    centres = {}

    for affectation in affectations:
        animateur = affectation.animateur
        centre = affectation.centre
        animateurs[animateur.id] = animateur
        centres[centre.id] = {
            "id": centre.id,
            "nom": centre.nom,
            "code": centre.code,
            "couleur": centre.couleur,
            "ordre": centre.ordre,
        }

        debut_affectation = max(timezone.localtime(affectation.debut).date(), debut_date)
        fin_affectation = min(timezone.localtime(affectation.fin).date(), fin_date)
        for jour in _jours_entre(debut_affectation, fin_affectation):
            if jour not in jours_autorises:
                continue
            jours_par_animateur[animateur.id].add(jour)
            jours_par_animateur_centre[animateur.id][centre.id].add(jour)
            details_par_animateur[animateur.id][jour][centre.id] = {
                "id": centre.id,
                "nom": centre.nom,
                "code": centre.code,
                "couleur": centre.couleur,
                "groupe": "Animateur flottant" if est_groupe_flottants(affectation.evenement) else affectation.evenement.nom,
            }

    centres_tries = sorted(
        centres.values(),
        key=lambda centre: (centre["ordre"], centre["nom"].casefold(), centre["code"]),
    )

    activites = (
        ActiviteTravailComplementaire.objects.prefetch_related("periodes", "participations")
        .filter(participations__animateur_id__in=animateurs.keys())
        .distinct()
        .order_by("date", "id")
    )
    reunions = []
    preparations = []
    ids_periodes_selectionnees = {int(item) for item in (periode_ids or [])}
    for activite in activites:
        jours_activite = {
            periode.debut + datetime.timedelta(days=decalage)
            for periode in activite.periodes.all()
            for decalage in range((periode.fin - periode.debut).days + 1)
        }
        # Une quantité sans date n'est pas répartissable entre plusieurs
        # semaines : elle n'entre dans le total que si toute sa sélection est
        # comprise dans le récapitulatif demandé.
        ids_periodes_activite = {periode.id for periode in activite.periodes.all()}
        selection_correspond = (
            ids_periodes_activite == ids_periodes_selectionnees
            if ids_periodes_selectionnees
            else jours_activite and jours_activite <= jours_autorises
        )
        if not selection_correspond:
            continue
        if activite.type == ActiviteTravailComplementaire.TYPE_REUNION:
            reunions.append(activite)
        elif activite.type == ActiviteTravailComplementaire.TYPE_PREPARATION:
            preparations.append(activite)

    lignes = []
    for animateur in animateurs.values():
        jours_totaux = jours_par_animateur[animateur.id]
        if not jours_totaux:
            continue
        ventilation = []
        for centre in centres_tries:
            nombre_jours = len(jours_par_animateur_centre[animateur.id][centre["id"]])
            ventilation.append({
                "centre_id": centre["id"],
                "jours_travailles": nombre_jours,
                "paie": _montant(nombre_jours, animateur.paie_jour),
            })

        jours_comptes = set(jours_totaux)
        jours_reunion = Decimal("0")
        for reunion in reunions:
            participation = next(
                (item for item in reunion.participations.all() if item.animateur_id == animateur.id),
                None,
            )
            if participation is None:
                continue
            if reunion.date in jours_comptes and not participation.autoriser_double_comptage:
                continue
            jours_reunion += participation.nombre_jours
            if not participation.autoriser_double_comptage:
                jours_comptes.add(reunion.date)

        jours_preparation = sum(
            (
                participation.nombre_jours
                for activite in preparations
                for participation in activite.participations.all()
                if participation.animateur_id == animateur.id
            ),
            Decimal("0"),
        )
        jours_affectation = Decimal(len(jours_totaux))
        total_jours = jours_affectation + jours_reunion + jours_preparation
        lignes.append({
            "id": animateur.id,
            "prenom": animateur.prenom,
            "nom": animateur.nom,
            "paie_jour": str(animateur.paie_jour) if animateur.paie_jour is not None else None,
            "jours_affectation": _nombre_json(jours_affectation),
            "jours_reunion": _nombre_json(jours_reunion),
            "jours_preparation": _nombre_json(jours_preparation),
            "jours_travailles": _nombre_json(total_jours),
            "paie_totale": _montant(total_jours, animateur.paie_jour),
            "centres": ventilation,
            "jours": [
                {
                    "date": jour.isoformat(),
                    "lieux": list(details_par_animateur[animateur.id][jour].values()),
                }
                for jour in sorted(jours_totaux)
            ],
        })

    lignes.sort(key=lambda ligne: (ligne["prenom"].casefold(), ligne["nom"].casefold()))
    total_paie = sum(
        (Decimal(ligne["paie_totale"]) for ligne in lignes if ligne["paie_totale"] is not None),
        Decimal("0.00"),
    )

    return {
        "dates": [jour.isoformat() for jour in sorted(jours_autorises)],
        "centres": [{key: value for key, value in centre.items() if key != "ordre"} for centre in centres_tries],
        "animateurs": lignes,
        "total_jours": _nombre_json(sum((Decimal(str(ligne["jours_travailles"])) for ligne in lignes), Decimal("0"))),
        "total_paie_connue": str(total_paie.quantize(Decimal("0.01"))),
        "tarifs_manquants": sum(1 for ligne in lignes if ligne["paie_jour"] is None),
    }


def generer_recapitulatif_paie_pdf(recap, debut: datetime.date, fin: datetime.date) -> bytes:
    """Crée un PDF compact reprenant les totaux de paie de la sélection."""

    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=landscape(A4),
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=f"Récapitulatif de paie du {debut:%d/%m/%Y} au {fin:%d/%m/%Y}",
    )
    styles = getSampleStyleSheet()
    titre = ParagraphStyle(
        "RecapPaieTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=16,
        textColor=colors.HexColor("#1F6F54"),
        alignment=TA_CENTER,
        spaceAfter=5 * mm,
    )

    def euros(valeur):
        if valeur is None:
            return "Tarif manquant"
        return f"{Decimal(valeur):,.2f} €".replace(",", " ").replace(".", ",")

    lignes = [["Animateur", "Affectations", "Réunions", "Télétravail / préparation", "Total", "Tarif / jour", "Paie totale"]]
    for animateur in recap["animateurs"]:
        lignes.append([
            f'{animateur["prenom"]} {animateur["nom"]}',
            str(animateur["jours_affectation"]),
            str(animateur["jours_reunion"]),
            str(animateur["jours_preparation"]),
            str(animateur["jours_travailles"]),
            euros(animateur["paie_jour"]),
            euros(animateur["paie_totale"]),
        ])
    lignes.append(["TOTAL", "", "", "", str(recap["total_jours"]), "", euros(recap["total_paie_connue"])])

    tableau = Table(lignes, colWidths=[55 * mm, 25 * mm, 22 * mm, 43 * mm, 20 * mm, 32 * mm, 35 * mm], repeatRows=1)
    tableau.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F6F54")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E8F3EE")),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D7E2DC")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#F7FAF8")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))

    contenu = [
        Paragraph("Récapitulatif de paie", titre),
        Paragraph(f"Période du {debut:%d/%m/%Y} au {fin:%d/%m/%Y}", styles["Heading2"]),
        Spacer(1, 4 * mm),
    ]
    if recap["animateurs"]:
        contenu.append(tableau)
    else:
        contenu.append(Paragraph("Aucune journée planifiée sur cette période.", styles["Normal"]))
    if recap["tarifs_manquants"]:
        contenu.extend([
            Spacer(1, 4 * mm),
            Paragraph(
                f'{recap["tarifs_manquants"]} tarif(s) journalier(s) manquant(s) : ces montants ne sont pas inclus dans le total.',
                styles["Normal"],
            ),
        ])

    document.build(contenu)
    output.seek(0)
    return output.read()
