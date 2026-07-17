"""Règles de mise à jour des lieux et du groupe préféré d'un animateur."""

from animateurs.models import Centre, Evenement, PreferenceCentre


def _normaliser_id_centre(valeur, libelle):
    if valeur in (None, ""):
        return None, None
    try:
        return int(valeur), None
    except (TypeError, ValueError):
        return None, f"{libelle} est invalide."


def normaliser_centres_hierarchises(payload):
    """Lit le centre préféré et les centres secondaires depuis le payload.

    Format moderne attendu :
        {
            "centre_prefere": 1,
            "centres_secondaires": [2, 3]
        }

    Compatibilité : si seul ``centres_autorises`` ou ``preferences`` est
    présent, le premier centre devient le centre préféré et les suivants des
    centres secondaires.
    """

    nouveau_format = (
        "centre_prefere" in payload or "centres_secondaires" in payload
    )

    if nouveau_format:
        centre_prefere_raw = payload.get("centre_prefere")
        secondaires_raw = payload.get("centres_secondaires") or []
    elif "centres_autorises" in payload:
        anciens = payload.get("centres_autorises") or []
        centre_prefere_raw = anciens[0] if anciens else None
        secondaires_raw = anciens[1:] if len(anciens) > 1 else []
    elif "preferences" in payload:
        anciens = [
            item.get("centre_id")
            for item in (payload.get("preferences") or [])
            if isinstance(item, dict)
        ]
        centre_prefere_raw = anciens[0] if anciens else None
        secondaires_raw = anciens[1:] if len(anciens) > 1 else []
    else:
        return None, None, None

    centre_prefere, erreur = _normaliser_id_centre(
        centre_prefere_raw, "Le centre préféré"
    )
    if erreur:
        return None, None, erreur

    if not isinstance(secondaires_raw, list):
        return None, None, "Les centres secondaires sont invalides."

    secondaires = []
    vus = set()
    for brut in secondaires_raw:
        centre_id, erreur = _normaliser_id_centre(brut, "Un centre secondaire")
        if erreur or centre_id is None:
            return None, None, erreur or "Un centre secondaire est invalide."
        if centre_id == centre_prefere:
            continue
        if centre_id in vus:
            return None, None, "Un même centre secondaire ne peut pas être ajouté deux fois."
        vus.add(centre_id)
        secondaires.append(centre_id)

    tous_ids = set(secondaires)
    if centre_prefere is not None:
        tous_ids.add(centre_prefere)

    existants = set(
        Centre.objects.filter(pk__in=tous_ids).values_list("id", flat=True)
    )
    if tous_ids != existants:
        return None, None, "Un des centres renseignés est introuvable."

    return centre_prefere, secondaires, None


def normaliser_evenement_preferee(payload, centre_prefere_id):
    """Valide le groupe préféré transmise dans une fiche animateur.

    ``(None, None)`` signifie soit « aucun groupe préféré », soit « ce champ
    n'est pas présent ». Le booléen ``fournie`` permet au code appelant de
    distinguer les deux situations lors d'un PATCH partiel.
    """

    if "evenement_preferee" not in payload and "evenement_preferee_id" not in payload:
        return None, False, None

    brut = payload.get("evenement_preferee", payload.get("evenement_preferee_id"))
    if brut in (None, ""):
        return None, True, None

    try:
        evenement_id = int(brut)
    except (TypeError, ValueError):
        return None, True, "Le groupe préféré est invalide."

    try:
        evenement = Evenement.objects.select_related("centre").get(pk=evenement_id)
    except Evenement.DoesNotExist:
        return None, True, "Le groupe préféré est introuvable."

    if centre_prefere_id is None:
        return None, True, "Choisis d'abord un centre préféré."
    if evenement.centre_id != centre_prefere_id:
        return None, True, "Le groupe préféré doit appartenir au centre préféré."

    return evenement, True, None


def appliquer_centres_hierarchises(animateur, centre_prefere_id, centres_secondaires_ids):
    """Remplace les centres de l'animateur en respectant leur hiérarchie."""

    if centre_prefere_id is None and centres_secondaires_ids is None:
        return

    animateur.preferences.all().delete()

    relations = []
    if centre_prefere_id is not None:
        relations.append(
            PreferenceCentre(
                animateur=animateur,
                centre_id=centre_prefere_id,
                est_prefere=True,
            )
        )

    for centre_id in centres_secondaires_ids or []:
        relations.append(
            PreferenceCentre(
                animateur=animateur,
                centre_id=centre_id,
                est_prefere=False,
            )
        )

    PreferenceCentre.objects.bulk_create(relations)

    # Une préférence de groupe devenue incohérente après un changement de
    # centre préféré est retirée automatiquement plutôt que de conserver une
    # valeur trompeuse.
    if (
        animateur.evenement_preferee_id
        and animateur.evenement_preferee.centre_id != centre_prefere_id
    ):
        animateur.evenement_preferee = None
        animateur.save(update_fields=["evenement_preferee"])
