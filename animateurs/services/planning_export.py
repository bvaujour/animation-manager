"""Génération des exports Excel du planning."""

from __future__ import annotations

import datetime
from io import BytesIO

import xlsxwriter
from django.utils import timezone

from animateurs.models import Affectation, Centre


JOURS_FR = [
    "Lundi",
    "Mardi",
    "Mercredi",
    "Jeudi",
    "Vendredi",
    "Samedi",
    "Dimanche",
]


def _couleur_texte(hex_color: str) -> str:
    """Retourne une couleur de texte lisible sur un fond hexadécimal."""
    value = (hex_color or "#FFFFFF").lstrip("#")
    if len(value) != 6:
        return "#000000"
    try:
        r, g, b = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    except ValueError:
        return "#000000"
    luminance = (0.299 * r) + (0.587 * g) + (0.114 * b)
    return "#000000" if luminance > 165 else "#FFFFFF"


def _jours_affectation(affectation: Affectation, debut: datetime.date, fin: datetime.date):
    """Produit les jours inclus dans l'affectation et la période demandée."""
    debut_local = timezone.localtime(affectation.debut).date()
    fin_exclusive = timezone.localtime(affectation.fin).date()

    jour = max(debut_local, debut)
    limite = min(fin_exclusive, fin + datetime.timedelta(days=1))
    while jour < limite:
        yield jour
        jour += datetime.timedelta(days=1)


def generer_export_planning_xlsx(debut: datetime.date, fin: datetime.date) -> bytes:
    """Crée un classeur XLSX contenant le planning détaillé de la période."""
    output = BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    workbook.set_properties({
        "title": "Export du planning",
        "subject": f"Planning du {debut:%d/%m/%Y} au {fin:%d/%m/%Y}",
        "author": "Gestion animation",
    })

    header_fmt = workbook.add_format({
        "bold": True,
        "font_color": "#FFFFFF",
        "bg_color": "#1F6F54",
        "border": 1,
        "align": "center",
        "valign": "vcenter",
    })
    date_fmt = workbook.add_format({"num_format": "dd/mm/yyyy", "align": "center"})
    center_fmt = workbook.add_format({"align": "center", "valign": "vcenter"})
    text_fmt = workbook.add_format({"valign": "vcenter"})
    title_fmt = workbook.add_format({
        "bold": True,
        "font_size": 16,
        "font_color": "#14503C",
    })
    subtitle_fmt = workbook.add_format({"font_color": "#5C6B60"})

    sheet = workbook.add_worksheet("Planning détaillé")
    sheet.hide_gridlines(2)
    sheet.write("A1", "Planning des événements", title_fmt)
    sheet.write("A2", f"Période : du {debut:%d/%m/%Y} au {fin:%d/%m/%Y}", subtitle_fmt)

    headers = [
        "Date",
        "Jour",
        "Centre",
        "Code centre",
        "Animateur",
        "Téléphone",
        "E-mail",
        "Qualifications",
    ]
    header_row = 3
    for col, label in enumerate(headers):
        sheet.write(header_row, col, label, header_fmt)

    affectations = (
        Affectation.objects
        .filter(debut__lt=timezone.make_aware(datetime.datetime.combine(fin + datetime.timedelta(days=1), datetime.time.min)))
        .filter(fin__gt=timezone.make_aware(datetime.datetime.combine(debut, datetime.time.min)))
        .select_related("animateur", "centre")
        .prefetch_related("animateur__qualifications")
        .order_by("debut", "centre__nom", "animateur__nom", "animateur__prenom")
    )

    lignes = []
    for affectation in affectations:
        animateur = affectation.animateur
        qualifications = ", ".join(q.nom for q in animateur.qualifications.all())
        for jour in _jours_affectation(affectation, debut, fin):
            lignes.append((
                jour,
                JOURS_FR[jour.weekday()],
                affectation.centre.nom,
                affectation.centre.code,
                f"{animateur.prenom} {animateur.nom}",
                animateur.telephone,
                animateur.email,
                qualifications,
            ))

    lignes.sort(key=lambda row: (row[0], row[2].lower(), row[4].lower()))
    first_data_row = header_row + 1
    for index, row in enumerate(lignes, start=first_data_row):
        sheet.write_datetime(index, 0, datetime.datetime.combine(row[0], datetime.time.min), date_fmt)
        sheet.write(index, 1, row[1], center_fmt)
        sheet.write(index, 2, row[2], text_fmt)
        sheet.write(index, 3, row[3], center_fmt)
        sheet.write(index, 4, row[4], text_fmt)
        sheet.write(index, 5, row[5], text_fmt)
        sheet.write(index, 6, row[6], text_fmt)
        sheet.write(index, 7, row[7], text_fmt)

    if lignes:
        sheet.autofilter(header_row, 0, header_row + len(lignes), len(headers) - 1)
        sheet.freeze_panes(first_data_row, 0)
    else:
        sheet.write(first_data_row, 0, "Aucune affectation sur cette période.", subtitle_fmt)

    sheet.set_row(header_row, 24)
    sheet.set_column("A:A", 12)
    sheet.set_column("B:B", 12)
    sheet.set_column("C:C", 22)
    sheet.set_column("D:D", 13)
    sheet.set_column("E:E", 24)
    sheet.set_column("F:F", 17)
    sheet.set_column("G:G", 30)
    sheet.set_column("H:H", 34)

    # Vue synthétique : une colonne par centre et une ligne par date.
    synthese = workbook.add_worksheet("Vue par jour")
    synthese.hide_gridlines(2)
    synthese.write("A1", "Planning par jour et par centre", title_fmt)
    synthese.write("A2", f"Du {debut:%d/%m/%Y} au {fin:%d/%m/%Y}", subtitle_fmt)

    centres = list(Centre.objects.order_by("nom"))
    synthese.write(3, 0, "Date", header_fmt)
    synthese.write(3, 1, "Jour", header_fmt)
    for col, centre in enumerate(centres, start=2):
        centre_fmt = workbook.add_format({
            "bold": True,
            "bg_color": centre.couleur,
            "font_color": _couleur_texte(centre.couleur),
            "border": 1,
            "align": "center",
            "valign": "vcenter",
        })
        synthese.write(3, col, centre.nom, centre_fmt)

    par_jour_centre: dict[tuple[datetime.date, int], list[str]] = {}
    for row in lignes:
        centre = next((c for c in centres if c.code == row[3]), None)
        if centre:
            par_jour_centre.setdefault((row[0], centre.id), []).append(row[4])

    row_idx = 4
    jour = debut
    wrap_fmt = workbook.add_format({"text_wrap": True, "valign": "top"})
    while jour <= fin:
        synthese.write_datetime(row_idx, 0, datetime.datetime.combine(jour, datetime.time.min), date_fmt)
        synthese.write(row_idx, 1, JOURS_FR[jour.weekday()], center_fmt)
        for col, centre in enumerate(centres, start=2):
            noms = par_jour_centre.get((jour, centre.id), [])
            synthese.write(row_idx, col, "\n".join(noms), wrap_fmt)
        synthese.set_row(row_idx, max(24, 15 * max([1] + [len(par_jour_centre.get((jour, c.id), [])) for c in centres])))
        row_idx += 1
        jour += datetime.timedelta(days=1)

    synthese.freeze_panes(4, 2)
    synthese.set_column("A:A", 12)
    synthese.set_column("B:B", 12)
    if centres:
        synthese.set_column(2, 1 + len(centres), 24)

    workbook.close()
    return output.getvalue()
