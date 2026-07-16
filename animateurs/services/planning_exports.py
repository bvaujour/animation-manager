"""Exports calendrier du planning en Excel et PDF.

Le rendu reprend la structure du planning manuel :

    Centre -> Evenement -> animateurs par date

Les événements actives sont toujours affichées. Une événement inactive reste visible
si elle possède au moins une affectation sur la période exportée, afin de ne
pas masquer l'historique.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from io import BytesIO

from django.db.models import Q
from django.utils import timezone

from ..models import Affectation, Evenement


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
    """Retourne les dates incluses de la période, en masquant le dimanche."""
    dates = []
    courant = debut
    while courant <= fin:
        if courant.weekday() != 6:
            dates.append(courant)
        courant += timedelta(days=1)
    return dates


def libelle_evenement(evenement: Evenement) -> str:
    """Nom lisible de l'événement, complété par ses horaires éventuels."""
    libelle = evenement.nom
    if not evenement.active:
        libelle += "\n(inactive)"
    return libelle


def _planning_matrix(debut: date, fin: date):
    """Construit les lignes et les cellules communes aux exports.

    La clé d'une cellule est désormais ``(evenement_id, date)`` et non plus
    ``(centre_id, date)``. Cela évite de mélanger deux événements du même centre.
    """
    dates = dates_visibles(debut, fin)
    affectations = list(
        Affectation.objects.select_related("animateur", "centre", "evenement")
        .filter(debut__date__lte=fin, fin__date__gt=debut)
        .order_by(
            "centre__nom",
            "evenement__ordre",
            "evenement__nom",
            "animateur__prenom",
            "animateur__nom",
        )
    )

    evenements_affectees = {affectation.evenement_id for affectation in affectations}
    evenements = list(
        Evenement.objects.select_related("centre")
        .filter(Q(active=True) | Q(id__in=evenements_affectees))
        .order_by("centre__nom", "centre_id", "ordre", "nom", "id")
    )

    noms_par_case: dict[tuple[int, date], list[str]] = defaultdict(list)
    couleurs_par_case: dict[tuple[int, date], list[str]] = defaultdict(list)

    for affectation in affectations:
        debut_local = timezone.localtime(affectation.debut).date()
        fin_local = timezone.localtime(affectation.fin).date()
        for jour in dates:
            if debut_local <= jour < fin_local:
                key = (affectation.evenement_id, jour)
                nom = f"{affectation.animateur.prenom} {affectation.animateur.nom}"
                if nom not in noms_par_case[key]:
                    noms_par_case[key].append(nom)
                    couleurs_par_case[key].append(
                        affectation.animateur.couleur or "#1f6f54"
                    )

    return dates, evenements, noms_par_case, couleurs_par_case


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


def generer_planning_excel(debut: date, fin: date) -> bytes:
    import xlsxwriter

    dates, evenements, noms_par_case, _ = _planning_matrix(debut, fin)
    output = BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    sheet = workbook.add_worksheet("Calendrier")

    title = workbook.add_format({
        "bold": True,
        "font_size": 16,
        "font_color": "#FFFFFF",
        "bg_color": "#1F6F54",
        "align": "center",
        "valign": "vcenter",
    })
    header = workbook.add_format({
        "bold": True,
        "font_color": "#FFFFFF",
        "bg_color": "#355C7D",
        "align": "center",
        "valign": "vcenter",
        "border": 1,
        "text_wrap": True,
    })
    evenement_format = workbook.add_format({
        "bold": True,
        "font_color": "#1E2A22",
        "bg_color": "#EDF3F1",
        "align": "left",
        "valign": "vcenter",
        "border": 1,
        "text_wrap": True,
    })
    cell = workbook.add_format({
        "align": "center",
        "valign": "vcenter",
        "border": 1,
        "text_wrap": True,
        "font_size": 10,
    })

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
    sheet.write(1, 1, "Événement", header)
    for col, jour in enumerate(dates, start=2):
        sheet.write(1, col, f"{JOURS_FR[jour.weekday()]}\n{jour:%d/%m}", header)

    first_data_row = 2
    for row_offset, evenement in enumerate(evenements):
        row = first_data_row + row_offset
        sheet.write(row, 1, libelle_evenement(evenement), evenement_format)
        max_lines = max(1, libelle_evenement(evenement).count("\n") + 1)
        for col, jour in enumerate(dates, start=2):
            noms = noms_par_case.get((evenement.id, jour), [])
            max_lines = max(max_lines, len(noms))
            sheet.write(row, col, "\n".join(noms), cell)
        sheet.set_row(row, max(38, 18 * max_lines))

    for debut_index, fin_index, centre in _groupes_centres(evenements):
        start_row = first_data_row + debut_index
        end_row = first_data_row + fin_index
        centre_fmt = workbook.add_format({
            "bold": True,
            "font_color": "#FFFFFF",
            "bg_color": centre.couleur or "#1F6F54",
            "align": "center",
            "valign": "vcenter",
            "border": 1,
            "text_wrap": True,
        })
        if start_row == end_row:
            sheet.write(start_row, 0, centre.nom, centre_fmt)
        else:
            sheet.merge_range(start_row, 0, end_row, 0, centre.nom, centre_fmt)

    if not evenements:
        empty_format = workbook.add_format({
            "italic": True,
            "font_color": "#64748B",
            "align": "center",
            "valign": "vcenter",
            "border": 1,
        })
        sheet.merge_range(2, 0, 2, last_col, "Aucune événement à afficher", empty_format)

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


def _chunks(items, size):
    for index in range(0, len(items), size):
        yield items[index:index + size]


def generer_planning_pdf(debut: date, fin: date) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Table, TableStyle

    dates, evenements, noms_par_case, couleurs_par_case = _planning_matrix(debut, fin)
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
    pages = list(_chunks(dates, 6)) or [[]]
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

        data = [[Paragraph("Centre", header_style), Paragraph("Événement", header_style)]]
        for jour in jours_page:
            data[0].append(
                Paragraph(f"{JOURS_FR[jour.weekday()]}<br/>{jour:%d/%m}", header_style)
            )

        for index, evenement in enumerate(evenements):
            centre_texte = evenement.centre.nom if index in first_team_index_by_centre else ""
            row = [Paragraph(centre_texte, centre_style)]

            evenement_html = evenement.nom
            if not evenement.active:
                evenement_html += '<br/><font name="Helvetica-Oblique" size="7">inactive</font>'
            row.append(Paragraph(evenement_html, evenement_style))

            for jour in jours_page:
                noms = noms_par_case.get((evenement.id, jour), [])
                couleurs_anim = couleurs_par_case.get((evenement.id, jour), [])
                lignes = []
                for nom, couleur in zip(noms, couleurs_anim):
                    lignes.append(f'<font color="{couleur}"><b>●</b></font> {nom}')
                row.append(Paragraph("<br/>".join(lignes) if lignes else "", name_style))
            data.append(row)

        if not evenements:
            data.append([
                Paragraph("Aucune événement à afficher", empty_style),
                "",
                *([""] * len(jours_page)),
            ])

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
                table_style.append(
                    ("LINEABOVE", (0, index), (-1, index), 1.4, centre_color)
                )

        if not evenements:
            table_style.extend([
                ("SPAN", (0, 1), (-1, 1)),
                ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#F8FAFC")),
            ])

        table.setStyle(TableStyle(table_style))
        story.append(table)

    doc.build(story)
    output.seek(0)
    return output.read()
