import datetime

from animateurs.models import Evenement, PeriodeScolaire


def creer_periode(*, debut=datetime.date(2026, 7, 6), nom=None, zone="A"):
    """Retourne une semaine de bibliothèque du lundi au vendredi.

    Plusieurs groupes peuvent naturellement partager la même période ; le
    helper réutilise donc la ligne existante quand les bornes sont identiques.
    """
    if debut.weekday() != 0:
        debut = debut - datetime.timedelta(days=debut.weekday())
    fin = debut + datetime.timedelta(days=4)
    periode, _ = PeriodeScolaire.objects.get_or_create(
        annee_scolaire=f"{debut.year}-{debut.year + 1}",
        zone=zone,
        debut=debut,
        fin=fin,
        defaults={"nom": nom or f"Semaine du {debut:%d/%m/%Y}"},
    )
    return periode


def creer_groupe(
    centre,
    *,
    nom="Groupe test",
    debut=datetime.date(2026, 7, 6),
    effectif_cible=1,
    jours_ouverts=None,
    ferme_jours_feries=False,
    ordre=0,
    avec_periode=True,
):
    jours = list(jours_ouverts if jours_ouverts is not None else [0, 1, 2, 3, 4])
    periode = creer_periode(debut=debut, nom=f"{nom} — période") if avec_periode else None
    groupe = Evenement.objects.create(
        centre=centre,
        nom=nom,
        debut=periode.debut if periode else None,
        fin=(periode.fin + datetime.timedelta(days=2 if 6 in jours else 1)) if periode and (5 in jours or 6 in jours) else (periode.fin if periode else None),
        effectif_cible=effectif_cible,
        jours_ouverts=jours,
        ferme_jours_feries=ferme_jours_feries,
        ordre=ordre,
    )
    if periode:
        groupe.periodes_scolaires.add(periode)
    return groupe, periode
