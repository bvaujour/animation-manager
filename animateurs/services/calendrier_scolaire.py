"""Import isolé des vacances scolaires officielles.

Ce module ne touche volontairement ni au planning, ni aux disponibilités,
ni aux groupes. Il transforme simplement les périodes publiées
par l'Éducation nationale en semaines complètes du lundi au vendredi.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

API_URL = (
    "https://data.education.gouv.fr/api/explore/v2.1/catalog/datasets/"
    "fr-en-calendrier-scolaire/records"
)


class CalendrierScolaireError(Exception):
    """Erreur lisible par l'utilisateur pendant l'import officiel."""


@dataclass(frozen=True)
class SemaineVacances:
    nom: str
    debut: dt.date
    fin: dt.date
    description_source: str
    numero: int

    def to_dict(self) -> dict:
        return {
            "nom": self.nom,
            "debut": self.debut.isoformat(),
            "fin": self.fin.isoformat(),
            "description_source": self.description_source,
            "numero": self.numero,
        }


def _date(value) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _sans_accents(value: str) -> str:
    return "".join(
        caractere
        for caractere in unicodedata.normalize("NFD", value or "")
        if unicodedata.category(caractere) != "Mn"
    ).casefold()


def _nom_vacances(description: str) -> str | None:
    texte = re.sub(r"\s+", " ", (description or "").strip())
    normalise = _sans_accents(texte)
    correspondances = (
        ("toussaint", "Toussaint"),
        ("noel", "Noël"),
        ("hiver", "Hiver"),
        ("printemps", "Printemps"),
        ("ete", "Été"),
    )
    for fragment, libelle in correspondances:
        if fragment in normalise:
            return libelle
    return None


def _premier_lundi_de_vacances(depart_apres_classe: dt.date) -> dt.date:
    """Retourne le premier lundi complet après le départ officiel.

    Le jeu de données indique un départ après la classe. On commence donc au
    jour suivant, puis on avance jusqu'au lundi suivant (ou on conserve ce
    jour s'il est déjà un lundi).
    """
    premier_jour = depart_apres_classe + dt.timedelta(days=1)
    return premier_jour + dt.timedelta(days=(7 - premier_jour.weekday()) % 7)


def decouper_en_semaines(
    description: str,
    debut_officiel: dt.date,
    reprise_officielle: dt.date,
) -> list[SemaineVacances]:
    """Découpe une vacance officielle en semaines complètes lundi-vendredi.

    La date de reprise n'est jamais incluse. Les périodes courtes qui ne
    contiennent aucune semaine complète (par exemple un simple pont) ne sont
    pas transformées en fausse semaine.
    """
    vacances = _nom_vacances(description)
    if not vacances or reprise_officielle <= debut_officiel:
        return []

    lundi = _premier_lundi_de_vacances(debut_officiel)
    resultat: list[SemaineVacances] = []
    numero = 1

    while lundi < reprise_officielle:
        vendredi = lundi + dt.timedelta(days=4)
        if vendredi >= reprise_officielle:
            break
        resultat.append(
            SemaineVacances(
                nom=f"{vacances} — Semaine {numero}",
                debut=lundi,
                fin=vendredi,
                description_source=(description or "").strip(),
                numero=numero,
            )
        )
        numero += 1
        lundi += dt.timedelta(days=7)

    return resultat


def _valider_parametres(annee_scolaire: str, zone: str) -> tuple[str, str]:
    annee_scolaire = (annee_scolaire or "").strip()
    if not re.fullmatch(r"\d{4}-\d{4}", annee_scolaire):
        raise CalendrierScolaireError(
            "L’année scolaire doit être au format 2026-2027."
        )
    debut, fin = map(int, annee_scolaire.split("-"))
    if fin != debut + 1:
        raise CalendrierScolaireError(
            "L’année scolaire doit contenir deux années consécutives."
        )

    zone = (zone or "").strip().upper()
    if zone not in {"A", "B", "C"}:
        raise CalendrierScolaireError("La zone doit être A, B ou C.")
    return annee_scolaire, zone


def recuperer_semaines(
    annee_scolaire: str,
    zone: str,
    *,
    timeout: int = 15,
) -> list[SemaineVacances]:
    """Récupère et déduplique les semaines d'une année et d'une zone."""
    annee_scolaire, zone = _valider_parametres(annee_scolaire, zone)
    params = [
        ("limit", "100"),
        ("lang", "fr"),
        ("timezone", "Europe/Paris"),
        ("refine", f'zones:"Zone {zone}"'),
        ("refine", f'annee_scolaire:"{annee_scolaire}"'),
    ]
    url = f"{API_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "AnimationManager/1.0 (+calendrier scolaire)"},
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (
        urllib.error.URLError,
        TimeoutError,
        OSError,
        json.JSONDecodeError,
    ) as exc:
        raise CalendrierScolaireError(
            "Le calendrier scolaire officiel est momentanément indisponible. "
            "Réessaie un peu plus tard."
        ) from exc

    records = payload.get("results") or payload.get("records") or []
    semaines: list[SemaineVacances] = []
    deja_vues: set[tuple[dt.date, dt.date]] = set()

    for record in records:
        fields = record.get("fields", record)
        description = (
            fields.get("description")
            or fields.get("summary")
            or fields.get("libelle")
            or ""
        )
        debut = _date(
            fields.get("start_date")
            or fields.get("start")
            or fields.get("date_debut")
        )
        fin = _date(
            fields.get("end_date")
            or fields.get("end")
            or fields.get("date_fin")
        )
        if not debut or not fin:
            continue

        for semaine in decouper_en_semaines(description, debut, fin):
            cle = (semaine.debut, semaine.fin)
            if cle in deja_vues:
                continue
            deja_vues.add(cle)
            semaines.append(semaine)

    semaines.sort(key=lambda semaine: (semaine.debut, semaine.nom))
    if not semaines:
        raise CalendrierScolaireError(
            "Aucune semaine de vacances complète n’a été trouvée pour cette "
            "année scolaire et cette zone. L’année n’est peut-être pas encore publiée."
        )
    return semaines
