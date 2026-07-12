"""Règles de mise à jour des relations d'un animateur."""

from animateurs.models import Centre, PreferenceCentre


def normaliser_centres_autorises(payload):
    if "centres_autorises" in payload:
        centres_raw = payload.get("centres_autorises") or []
    elif "preferences" in payload:
        centres_raw = [item.get("centre_id") for item in (payload.get("preferences") or [])]
    else:
        return None, None

    if not isinstance(centres_raw, list):
        return None, "Les centres autorisés sont invalides."

    centres_ids = []
    vus = set()
    for brut in centres_raw:
        try:
            centre_id = int(brut)
        except (TypeError, ValueError):
            return None, "Les centres autorisés sont invalides."
        if centre_id in vus:
            return None, "Un même centre ne peut pas être ajouté deux fois."
        vus.add(centre_id)
        centres_ids.append(centre_id)

    existants = set(Centre.objects.filter(pk__in=vus).values_list("id", flat=True))
    if vus != existants:
        return None, "Un des centres autorisés est introuvable."
    return centres_ids, None


def appliquer_centres_autorises(animateur, centres_ids):
    if centres_ids is None:
        return
    animateur.preferences.all().delete()
    PreferenceCentre.objects.bulk_create([
        PreferenceCentre(animateur=animateur, centre_id=centre_id)
        for centre_id in centres_ids
    ])
