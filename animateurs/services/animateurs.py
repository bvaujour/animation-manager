"""Règles de mise à jour des lieux et du groupe préféré d'un animateur."""

from animateurs.models import Centre, Evenement, PreferenceCentre

from .flottants import est_groupe_flottants


def _normaliser_id_centre(valeur, libelle):
    if valeur in (None, ""):
        return None, None
    try:
        return int(valeur), None
    except (TypeError, ValueError):
        return None, f"{libelle} est invalide."


def normaliser_centres_hierarchises(payload):
    """Lit plusieurs centres préférés et plusieurs centres interdits.

    Les centres sans option restent neutres et sont autorisés. Les anciens
    champs sont acceptés pour compatibilité avec les écrans déjà en cache.
    """
    champs_modernes = "centres_preferes" in payload or "centres_interdits" in payload
    champs_anciens = "centre_prefere" in payload or "centres_secondaires" in payload
    if not champs_modernes and not champs_anciens and "centres_autorises" not in payload and "preferences" not in payload:
        return None, None, None

    if champs_modernes:
        preferes_raw = payload.get("centres_preferes") or []
        interdits_raw = payload.get("centres_interdits") or []
    else:
        # Compatibilité avec l’ancien formulaire : le premier lieu reste le
        # préféré principal et les anciens « centres secondaires » deviennent
        # des lieux préférés supplémentaires. La migration 0053 autorise
        # désormais plusieurs préférences, sans perdre les données envoyées
        # par une page restée en cache.
        ancien_prefere = payload.get("centre_prefere")
        anciens_secondaires = payload.get("centres_secondaires") or []
        if not isinstance(anciens_secondaires, list):
            return None, None, "Les lieux secondaires sont invalides."
        preferes_raw = (
            ([ancien_prefere] if ancien_prefere not in (None, "") else [])
            + anciens_secondaires
        )
        interdits_raw = []

    if not isinstance(preferes_raw, list) or not isinstance(interdits_raw, list):
        return None, None, "Les lieux préférés ou interdits sont invalides."

    def normaliser_liste(valeurs, libelle):
        resultat, vus = [], set()
        for brut in valeurs:
            centre_id, erreur = _normaliser_id_centre(brut, libelle)
            if erreur or centre_id is None:
                return None, erreur or f"{libelle} est invalide."
            if centre_id not in vus:
                vus.add(centre_id)
                resultat.append(centre_id)
        return resultat, None

    preferes, erreur = normaliser_liste(preferes_raw, "Un lieu préféré")
    if erreur:
        return None, None, erreur
    interdits, erreur = normaliser_liste(interdits_raw, "Un lieu interdit")
    if erreur:
        return None, None, erreur
    if set(preferes) & set(interdits):
        return None, None, "Un même lieu ne peut pas être préféré et interdit."
    tous_ids = set(preferes) | set(interdits)
    existants = set(Centre.objects.filter(pk__in=tous_ids).values_list("id", flat=True))
    if tous_ids != existants:
        return None, None, "Un des lieux renseignés est introuvable."
    return preferes, interdits, None


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
        evenement = Evenement.objects.select_related("centre", "groupe").get(pk=evenement_id)
    except Evenement.DoesNotExist:
        return None, True, "Le groupe préféré est introuvable."
    if est_groupe_flottants(evenement):
        return None, True, "Le groupe préféré est introuvable."

    if centre_prefere_id is None:
        return None, True, "Choisis d'abord un centre préféré."
    if evenement.centre_id != centre_prefere_id:
        return None, True, "Le groupe préféré doit appartenir au centre préféré."

    return evenement, True, None


def appliquer_centres_hierarchises(animateur, centres_preferes_ids, centres_interdits_ids):
    """Remplace les préférences et interdictions de lieux de l'animateur."""
    if centres_preferes_ids is None and centres_interdits_ids is None:
        return
    animateur.preferences.all().delete()
    relations = [
        PreferenceCentre(animateur=animateur, centre_id=centre_id, est_prefere=True, est_interdit=False)
        for centre_id in (centres_preferes_ids or [])
    ] + [
        PreferenceCentre(animateur=animateur, centre_id=centre_id, est_prefere=False, est_interdit=True)
        for centre_id in (centres_interdits_ids or [])
    ]
    PreferenceCentre.objects.bulk_create(relations)
