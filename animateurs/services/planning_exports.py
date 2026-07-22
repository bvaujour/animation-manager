"""Exports calendrier du planning en Excel et PDF.

Le rendu reprend la structure du planning manuel :

    Lieu -> Groupe -> animateurs par date

Seuls les groupes rattachés à au moins une période sont affichés, sauf si une affectation historique doit rester visible.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from io import BytesIO

from django.db.models import Q
from django.utils import timezone

from ..models import Affectation, EffectifEnfantsJour, Evenement
from .flottants import est_groupe_flottants
from .status_colors import statut_payload

JOURS_FR = [
    "Lundi",
    "Mardi",
    "Mercredi",
    "Jeudi",
    "Vendredi",
    "Samedi",
    "Dimanche",
]


def dates_visibles(debut: date, fin: date) -> list[date]:
    """Retourne toutes les dates incluses ; chaque groupe gère ses jours ouverts."""
    dates = []
    courant = debut
    while courant <= fin:
        dates.append(courant)
        courant += timedelta(days=1)
    return dates


def libelle_evenement(evenement: Evenement) -> str:
    """Nom lisible du groupe, y compris la ligne flottante du lieu."""
    return "Animateurs flottants" if est_groupe_flottants(evenement) else evenement.nom


def libelle_affectation(affectation: Affectation) -> str:
    """Nom de l'animateur affecté ; les horaires appartiennent à la journée."""
    return f"{affectation.animateur.prenom} {affectation.animateur.nom}"


def _journees_par_case(groupes, dates):
    return {
        (ligne.evenement_id, ligne.date): ligne
        for ligne in EffectifEnfantsJour.objects.filter(
            evenement__in=groupes,
            date__in=dates,
        )
    }


def horaires_manquants_export(
    debut: date,
    fin: date,
    jours_selectionnes: set[date] | None = None,
) -> list[dict]:
    """Liste les animateurs affectés sans plage horaire journalière."""
    dates, _, _, _ = _planning_matrix(debut, fin, jours_selectionnes)
    affectations = Affectation.objects.filter(
        debut__date__lte=fin,
        fin__date__gt=debut,
    ).select_related("animateur", "centre", "evenement").prefetch_related("horaires_journaliers")
    manquants = []
    for affectation in affectations:
        horaires = {horaire.date for horaire in affectation.horaires_journaliers.all()}
        debut_affectation = timezone.localtime(affectation.debut).date()
        fin_affectation = timezone.localtime(affectation.fin).date()
        for jour in dates:
            if not (debut_affectation <= jour < fin_affectation) or jour in horaires:
                continue
            manquants.append({
                "date": jour.isoformat(),
                "centre": affectation.centre.nom,
                "groupe": libelle_evenement(affectation.evenement),
                "animateur": f"{affectation.animateur.prenom} {affectation.animateur.nom}",
            })
    return manquants


def _planning_matrix(debut: date, fin: date, jours_selectionnes: set[date] | None = None):
    """Construit les lignes et cellules communes aux exports.

    Seules les dates réellement ouvertes pour au moins un groupe sont
    conservées. Une date portant une affectation historique reste toutefois
    visible, même si le groupe n'a plus de période configurée.
    """
    affectations = list(
        Affectation.objects.select_related("animateur", "centre", "evenement").prefetch_related(
            "animateur__qualifications", "horaires_journaliers"
        )
        .filter(debut__date__lte=fin, fin__date__gt=debut)
        .order_by(
            "centre__nom",
            "evenement__ordre",
            "evenement__nom",
            "animateur__prenom",
            "animateur__nom",
        )
    )

    groupes_affectes = {affectation.evenement_id for affectation in affectations}
    groupes = list(
        Evenement.objects.select_related("centre")
        .prefetch_related("periodes_scolaires", "dates_exclues")
        .filter(Q(permanent=True) | Q(periodes_scolaires__isnull=False) | Q(id__in=groupes_affectes))
        .distinct()
        .order_by("centre__nom", "centre_id", "ordre", "nom", "id")
    )

    intervalles_affectes = []
    for affectation in affectations:
        intervalles_affectes.append(
            (
                timezone.localtime(affectation.debut).date(),
                timezone.localtime(affectation.fin).date(),
            )
        )

    dates_exclues = {groupe.id: set(groupe.dates_exclues.values_list("date", flat=True)) for groupe in groupes}
    dates = []
    for jour in dates_visibles(debut, fin):
        if jours_selectionnes is not None and jour not in jours_selectionnes:
            continue
        groupe_ouvert = any(
            not est_groupe_flottants(groupe)
            and groupe.est_ouvert_le(jour, dates_exclues[groupe.id])
            for groupe in groupes
        )
        affectation_historique = any(debut_aff <= jour < fin_aff for debut_aff, fin_aff in intervalles_affectes)
        if groupe_ouvert or affectation_historique:
            dates.append(jour)

    noms_par_case: dict[tuple[int, date], list[str]] = defaultdict(list)
    couleurs_par_case: dict[tuple[int, date], list[str]] = defaultdict(list)

    for affectation in affectations:
        debut_local = timezone.localtime(affectation.debut).date()
        fin_local = timezone.localtime(affectation.fin).date()
        horaires = {horaire.date: horaire for horaire in affectation.horaires_journaliers.all()}
        for jour in dates:
            if debut_local <= jour < fin_local:
                key = (affectation.evenement_id, jour)
                nom = libelle_affectation(affectation)
                horaire = horaires.get(jour)
                if horaire:
                    nom += f" · {horaire.heure_arrivee:%H:%M}–{horaire.heure_depart:%H:%M}"
                if nom not in noms_par_case[key]:
                    noms_par_case[key].append(nom)
                    couleurs_par_case[key].append(
                        statut_payload(affectation.animateur.qualifications.all())["couleur_statut"]
                    )

    return dates, groupes, noms_par_case, couleurs_par_case


def _groupes_centres(evenements: list[Evenement]):
    """Retourne les indices de début/fin de chaque centre dans la liste."""
    groupes = []
    index = 0
    while index < len(evenements):
        centre_id = evenements[index].centre_id
        fin_index = index
        while fin_index + 1 < len(evenements) and evenements[fin_index + 1].centre_id == centre_id:
            fin_index += 1
        groupes.append((index, fin_index, evenements[index].centre))
        index = fin_index + 1
    return groupes


def generer_planning_excel(
    debut: date,
    fin: date,
    jours_selectionnes: set[date] | None = None,
) -> bytes:
    import xlsxwriter

    dates, evenements, noms_par_case, _ = _planning_matrix(debut, fin, jours_selectionnes)
    journees_par_case = _journees_par_case(evenements, dates)
    output = BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    sheet = workbook.add_worksheet("Calendrier")

    title = workbook.add_format(
        {
            "bold": True,
            "font_size": 16,
            "font_color": "#FFFFFF",
            "bg_color": "#1F6F54",
            "align": "center",
            "valign": "vcenter",
        }
    )
    header = workbook.add_format(
        {
            "bold": True,
            "font_color": "#FFFFFF",
            "bg_color": "#355C7D",
            "align": "center",
            "valign": "vcenter",
            "border": 1,
            "text_wrap": True,
        }
    )
    evenement_format = workbook.add_format(
        {
            "bold": True,
            "font_color": "#1E2A22",
            "bg_color": "#EDF3F1",
            "align": "left",
            "valign": "vcenter",
            "border": 1,
            "text_wrap": True,
        }
    )
    cell = workbook.add_format(
        {
            "align": "center",
            "valign": "vcenter",
            "border": 1,
            "text_wrap": True,
            "font_size": 10,
        }
    )

    last_col = max(2, len(dates) + 1)
    sheet.merge_range(
        0,
        0,
        0,
        last_col,
        f"Planning du {debut:%d/%m/%Y} au {fin:%d/%m/%Y}",
        title,
    )
    sheet.set_row(0, 28)

    sheet.write(1, 0, "Centre", header)
    sheet.write(1, 1, "Groupe", header)
    for col, jour in enumerate(dates, start=2):
        sheet.write(1, col, f"{JOURS_FR[jour.weekday()]}\n{jour:%d/%m}", header)

    first_data_row = 2
    for row_offset, evenement in enumerate(evenements):
        row = first_data_row + row_offset
        sheet.write(row, 1, libelle_evenement(evenement), evenement_format)
        max_lines = max(1, libelle_evenement(evenement).count("\n") + 1)
        for col, jour in enumerate(dates, start=2):
            noms = noms_par_case.get((evenement.id, jour), [])
            journee = journees_par_case.get((evenement.id, jour))
            lignes = []
            if journee:
                lignes.append(f"{journee.nombre} enfants")
            lignes.extend(noms)
            max_lines = max(max_lines, len(lignes))
            sheet.write(row, col, "\n".join(lignes), cell)
        sheet.set_row(row, max(38, 18 * max_lines))

    for debut_index, fin_index, centre in _groupes_centres(evenements):
        start_row = first_data_row + debut_index
        end_row = first_data_row + fin_index
        centre_fmt = workbook.add_format(
            {
                "bold": True,
                "font_color": "#FFFFFF",
                "bg_color": centre.couleur or "#1F6F54",
                "align": "center",
                "valign": "vcenter",
                "border": 1,
                "text_wrap": True,
            }
        )
        if start_row == end_row:
            sheet.write(start_row, 0, centre.nom, centre_fmt)
        else:
            sheet.merge_range(start_row, 0, end_row, 0, centre.nom, centre_fmt)

    if not evenements:
        empty_format = workbook.add_format(
            {
                "italic": True,
                "font_color": "#64748B",
                "align": "center",
                "valign": "vcenter",
                "border": 1,
            }
        )
        sheet.merge_range(2, 0, 2, last_col, "Aucun groupe à afficher", empty_format)

    sheet.set_column(0, 0, 22)
    sheet.set_column(1, 1, 24)
    if dates:
        sheet.set_column(2, len(dates) + 1, 18)
    sheet.freeze_panes(2, 2)
    sheet.hide_gridlines(2)
    sheet.set_landscape()
    sheet.set_paper(9)  # A4
    sheet.fit_to_pages(1, 0)
    sheet.repeat_rows(0, 1)
    sheet.set_margins(0.25, 0.25, 0.35, 0.35)

    workbook.close()
    output.seek(0)
    return output.read()


def _dates_par_semaine(dates: list[date]) -> list[list[date]]:
    """Regroupe les seuls jours ouverts par semaine civile pour le PDF."""
    semaines: dict[date, list[date]] = {}
    for jour in dates:
        lundi = jour - timedelta(days=jour.weekday())
        semaines.setdefault(lundi, []).append(jour)
    return list(semaines.values())


def generer_planning_pdf(
    debut: date,
    fin: date,
    jours_selectionnes: set[date] | None = None,
) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Table,
        TableStyle,
    )

    dates, evenements, noms_par_case, couleurs_par_case = _planning_matrix(debut, fin, jours_selectionnes)
    journees_par_case = _journees_par_case(evenements, dates)
    output = BytesIO()
    doc = SimpleDocTemplate(
        output,
        pagesize=landscape(A4),
        leftMargin=7 * mm,
        rightMargin=7 * mm,
        topMargin=7 * mm,
        bottomMargin=7 * mm,
        title=f"Planning du {debut:%d/%m/%Y} au {fin:%d/%m/%Y}",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "PlanningTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=17,
        textColor=colors.HexColor("#1F6F54"),
        alignment=TA_CENTER,
        spaceAfter=6,
    )
    header_style = ParagraphStyle(
        "PlanningHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=10,
        textColor=colors.white,
        alignment=TA_CENTER,
    )
    centre_style = ParagraphStyle(
        "Centre",
        parent=header_style,
        fontSize=8.5,
    )
    evenement_style = ParagraphStyle(
        "Evenement",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=9.5,
        alignment=TA_LEFT,
        textColor=colors.HexColor("#1E2A22"),
    )
    name_style = ParagraphStyle(
        "Name",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.6,
        leading=9.2,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#1E2A22"),
    )
    empty_style = ParagraphStyle(
        "Empty",
        parent=styles["Normal"],
        fontName="Helvetica-Oblique",
        fontSize=9,
        leading=11,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#64748B"),
    )

    story = []
    # Un tableau représente une semaine sélectionnée. Il contient exactement
    # les dates ouvertes calculées par la matrice, sans colonne artificielle.
    pages = _dates_par_semaine(dates) or [[]]
    groupes = _groupes_centres(evenements)
    first_team_index_by_centre = {debut_index for debut_index, _, _ in groupes}

    for page_index, jours_page in enumerate(pages):
        if page_index:
            story.append(PageBreak())

        if jours_page:
            plage = f"{jours_page[0]:%d/%m/%Y} - {jours_page[-1]:%d/%m/%Y}"
        else:
            plage = f"{debut:%d/%m/%Y} - {fin:%d/%m/%Y}"
        story.append(Paragraph(f"Planning - {plage}", title_style))

        data = [[Paragraph("Centre", header_style), Paragraph("Groupe", header_style)]]
        for jour in jours_page:
            data[0].append(Paragraph(f"{JOURS_FR[jour.weekday()]}<br/>{jour:%d/%m}", header_style))

        for index, evenement in enumerate(evenements):
            centre_texte = evenement.centre.nom if index in first_team_index_by_centre else ""
            row = [Paragraph(centre_texte, centre_style)]

            evenement_html = evenement.nom
            row.append(Paragraph(evenement_html, evenement_style))

            for jour in jours_page:
                noms = noms_par_case.get((evenement.id, jour), [])
                couleurs_anim = couleurs_par_case.get((evenement.id, jour), [])
                lignes = []
                journee = journees_par_case.get((evenement.id, jour))
                if journee:
                    lignes.append(f"<b>{journee.nombre} enfants</b>")
                for nom, couleur in zip(noms, couleurs_anim, strict=True):
                    lignes.append(f'<font color="{couleur}"><b>●</b></font> {nom}')
                row.append(Paragraph("<br/>".join(lignes) if lignes else "", name_style))
            data.append(row)

        if not evenements:
            data.append(
                [
                    Paragraph("Aucun groupe à afficher", empty_style),
                    "",
                    *([""] * len(jours_page)),
                ]
            )

        usable_width = landscape(A4)[0] - 14 * mm
        centre_col = 36 * mm
        evenement_col = 32 * mm
        date_width = (usable_width - centre_col - evenement_col) / max(1, len(jours_page))
        table = Table(
            data,
            colWidths=[centre_col, evenement_col] + [date_width] * len(jours_page),
            repeatRows=1,
        )

        table_style = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#355C7D")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.55, colors.HexColor("#9CA3AF")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("BACKGROUND", (1, 1), (1, -1), colors.HexColor("#EDF3F1")),
            ("BACKGROUND", (2, 1), (-1, -1), colors.HexColor("#F8FAFC")),
        ]

        for index, evenement in enumerate(evenements, start=1):
            centre_color = colors.HexColor(evenement.centre.couleur or "#1F6F54")
            table_style.append(("BACKGROUND", (0, index), (0, index), centre_color))
            table_style.append(("TEXTCOLOR", (0, index), (0, index), colors.white))
            if (index - 1) in first_team_index_by_centre:
                table_style.append(("LINEABOVE", (0, index), (-1, index), 1.4, centre_color))

        if not evenements:
            table_style.extend(
                [
                    ("SPAN", (0, 1), (-1, 1)),
                    ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#F8FAFC")),
                ]
            )

        table.setStyle(TableStyle(table_style))
        story.append(table)

    doc.build(story)
    output.seek(0)
    return output.read()
