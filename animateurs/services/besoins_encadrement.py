"""Résolution des besoins d'encadrement selon le contexte de travail."""

from __future__ import annotations

from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction

from animateurs.models import (
    BesoinEncadrement,
    BesoinQualification,
    Evenement,
    ModalitePeriscolaire,
    PeriodeCalendrier,
    Qualification,
    TypeAccueil,
)

from .accueils import valider_contexte_accueil


@dataclass(frozen=True)
class BesoinEffectif:
    effectif_cible: int
    qualifications: tuple[BesoinQualification, ...]
    regle: BesoinEncadrement | None = None
    configure: bool = True

    @property
    def personnalise(self):
        return self.regle is not None

    @property
    def mode_calcul(self):
        return self.regle.mode_calcul if self.regle is not None else BesoinEncadrement.MODE_MANUEL

    @property
    def renforts_souhaites(self):
        return int(getattr(self.regle, "renforts_souhaites", 0) or 0)


def _meme_fk(objet, champ, valeur):
    return getattr(objet, f"{champ}_id") == (getattr(valeur, "pk", valeur) if valeur is not None else None)


def _score_regle(regle, *, modalite=None, periode_calendrier=None):
    """Priorité : période précise, puis créneau précis, puis règle de type."""

    if regle.periode_calendrier_id is not None:
        if periode_calendrier is None or not _meme_fk(regle, "periode_calendrier", periode_calendrier):
            return None
        score_periode = 2
    else:
        score_periode = 0

    if regle.modalite_periscolaire_id is not None:
        if modalite is None or not _meme_fk(regle, "modalite_periscolaire", modalite):
            return None
        score_modalite = 1
    else:
        score_modalite = 0
    return score_periode + score_modalite


def regle_encadrement_effective(
    evenement: Evenement,
    *,
    type_accueil: TypeAccueil | None = None,
    modalite: ModalitePeriscolaire | None = None,
    periode_calendrier: PeriodeCalendrier | None = None,
):
    if type_accueil is None:
        return None
    regles_prefetches = getattr(evenement, "_centres_payload_besoins_encadrement", None)
    if regles_prefetches is None:
        regles_prefetches = getattr(evenement, "_prefetched_objects_cache", {}).get("besoins_encadrement")
    regles = (
        [regle for regle in regles_prefetches if regle.type_accueil_id == type_accueil.pk]
        if regles_prefetches is not None
        else list(
            evenement.besoins_encadrement.filter(type_accueil=type_accueil)
            .select_related("type_accueil", "modalite_periscolaire", "periode_calendrier")
        )
    )
    candidates = []
    for regle in regles:
        score = _score_regle(
            regle,
            modalite=modalite if type_accueil.code == TypeAccueil.PERISCOLAIRE else None,
            periode_calendrier=periode_calendrier,
        )
        if score is not None:
            candidates.append((score, regle.pk, regle))
    return max(candidates, default=(None, None, None))[2]


def _qualifications_exactes(evenement, *, type_accueil, modalite, periode_calendrier):
    besoins_prefetches = getattr(evenement, "_prefetched_objects_cache", {}).get("besoins_qualifications")
    if besoins_prefetches is not None:
        resultat = [
            besoin for besoin in besoins_prefetches
            if besoin.type_accueil_id == type_accueil.pk
            and besoin.modalite_periscolaire_id == getattr(modalite, "pk", modalite)
            and besoin.periode_calendrier_id == getattr(periode_calendrier, "pk", periode_calendrier)
        ]
        return tuple(sorted(resultat, key=lambda besoin: (besoin.qualification.nom, besoin.qualification_id)))
    return tuple(
        evenement.besoins_qualifications.select_related("qualification")
        .filter(
            type_accueil=type_accueil,
            modalite_periscolaire=modalite,
            periode_calendrier=periode_calendrier,
        )
        .order_by("qualification__nom", "qualification_id")
    )


def _qualifications_effectives(evenement, *, type_accueil, regle, modalite, periode_calendrier):
    """Hérite seulement à l'intérieur du même type d'accueil.

    Un créneau Périscolaire peut reprendre les exigences du Périscolaire par
    défaut. Il ne reprend jamais celles des Vacances.
    """

    if regle is None:
        return ()

    # La règle d'encadrement effective porte aussi la sémantique des
    # qualifications. Si elle est spécifique à un créneau/période et qu'aucune
    # qualification n'est enregistrée, cette liste vide est volontaire : elle
    # signifie « aucune qualification minimale » et ne doit pas hériter du
    # défaut Périscolaire. Lorsqu'aucune surcharge n'existe, ``regle`` est déjà
    # la règle Périscolaire par défaut et ses qualifications sont donc reprises.
    return _qualifications_exactes(
        evenement,
        type_accueil=regle.type_accueil,
        modalite=regle.modalite_periscolaire,
        periode_calendrier=regle.periode_calendrier,
    )


def besoin_encadrement_effectif(
    evenement: Evenement,
    *,
    type_accueil: TypeAccueil | None = None,
    modalite: ModalitePeriscolaire | None = None,
    periode_calendrier: PeriodeCalendrier | None = None,
):
    """Retourne le besoin du contexte sans croiser Vacances et Périscolaire.

    Les appels historiques sans type d'accueil conservent le fonctionnement
    antérieur. Dès qu'un type est explicitement fourni, l'absence de règle est
    considérée comme « non configuré » plutôt que de reprendre silencieusement
    une valeur d'un autre contexte.
    """

    if type_accueil is not None:
        regle = regle_encadrement_effective(
            evenement,
            type_accueil=type_accueil,
            modalite=modalite,
            periode_calendrier=periode_calendrier,
        )
        if regle is None:
            return BesoinEffectif(0, (), None, configure=False)
        qualifications = _qualifications_effectives(
            evenement,
            type_accueil=type_accueil,
            regle=regle,
            modalite=modalite,
            periode_calendrier=periode_calendrier,
        )
        return BesoinEffectif(int(regle.effectif_cible), qualifications, regle, configure=True)

    # Compatibilité des anciennes API/tests qui ne transmettent pas encore le
    # contexte : elles restent basées sur les champs historiques du groupe.
    besoins_prefetches = getattr(evenement, "_prefetched_objects_cache", {}).get("besoins_qualifications")
    if besoins_prefetches is not None:
        qualifications = tuple(
            besoin for besoin in besoins_prefetches
            if besoin.type_accueil_id is None
            and besoin.modalite_periscolaire_id is None
            and besoin.periode_calendrier_id is None
        )
    else:
        qualifications = tuple(
            evenement.besoins_qualifications.select_related("qualification")
            .filter(type_accueil__isnull=True, modalite_periscolaire__isnull=True, periode_calendrier__isnull=True)
            .order_by("qualification__nom", "qualification_id")
        )
    return BesoinEffectif(int(evenement.effectif_cible), qualifications, None, configure=True)


def besoins_contextuels_payload(evenement: Evenement):
    """Sérialise les règles explicites Vacances/Périscolaire pour Configuration."""

    cache = getattr(evenement, "_prefetched_objects_cache", {})
    regles_prefetches = cache.get("besoins_encadrement")
    regles = list(regles_prefetches) if regles_prefetches is not None else list(
        evenement.besoins_encadrement.select_related(
            "type_accueil", "modalite_periscolaire", "periode_calendrier"
        ).order_by("type_accueil__ordre", "modalite_periscolaire__ordre", "periode_calendrier__debut", "id")
    )
    qualifications_prefetches = cache.get("besoins_qualifications")
    besoins_qualification = [
        besoin for besoin in (qualifications_prefetches if qualifications_prefetches is not None else
            evenement.besoins_qualifications.select_related("qualification").order_by(
                "qualification__nom", "qualification_id"
            ))
        if besoin.type_accueil_id is not None
    ]

    def qualifs(regle):
        return {
            str(item.qualification_id): int(item.nombre_minimum)
            for item in besoins_qualification
            if item.type_accueil_id == regle.type_accueil_id
            and item.modalite_periscolaire_id == regle.modalite_periscolaire_id
            and item.periode_calendrier_id == regle.periode_calendrier_id
        }

    return [
        {
            "type_accueil": regle.type_accueil.code,
            "type_accueil_nom": regle.type_accueil.nom,
            "modalite_periscolaire": regle.modalite_periscolaire.code if regle.modalite_periscolaire_id else None,
            "modalite_periscolaire_nom": regle.modalite_periscolaire.nom if regle.modalite_periscolaire_id else None,
            "periode_calendrier_id": regle.periode_calendrier_id,
            "effectif_cible": int(regle.effectif_cible),
            "mode_calcul": regle.mode_calcul,
            "effectif_enfants_reference": regle.effectif_enfants_reference,
            "renforts_souhaites": int(regle.renforts_souhaites or 0),
            "qualifications_requises": qualifs(regle),
        }
        for regle in regles
    ]


@transaction.atomic
def enregistrer_besoins_contextuels(evenement: Evenement, lignes):
    """Remplace les règles générales explicites Vacances/Périscolaire du groupe."""

    if lignes is None:
        return
    if not isinstance(lignes, list):
        raise ValidationError("Les besoins d'encadrement sont invalides.")

    normalisees = []
    cles = set()
    for ligne in lignes:
        if not isinstance(ligne, dict):
            raise ValidationError("Un besoin d'encadrement est invalide.")
        code_type = str(ligne.get("type_accueil", "")).strip()
        try:
            type_accueil = TypeAccueil.objects.get(code=code_type, actif=True)
        except TypeAccueil.DoesNotExist as exc:
            raise ValidationError("Le type d'accueil d'un besoin est invalide.") from exc
        if type_accueil.code not in (TypeAccueil.VACANCES, TypeAccueil.PERISCOLAIRE):
            raise ValidationError("Seuls Vacances et Périscolaire sont configurables ici.")

        # Une instance rattachée à AccueilCentre ne peut enregistrer des besoins
        # que pour cet accueil précis. Les instances legacy restent compatibles.
        valider_contexte_accueil(evenement, type_accueil)

        code_modalite = str(ligne.get("modalite_periscolaire") or "").strip()
        modalite = None
        if code_modalite:
            if type_accueil.code != TypeAccueil.PERISCOLAIRE:
                raise ValidationError("Un créneau ne peut être défini qu'en Périscolaire.")
            try:
                modalite = ModalitePeriscolaire.objects.get(code=code_modalite, actif=True)
            except ModalitePeriscolaire.DoesNotExist as exc:
                raise ValidationError("Le créneau périscolaire d'un besoin est invalide.") from exc

        periode_id = ligne.get("periode_calendrier_id") or None
        periode = None
        if periode_id is not None:
            try:
                periode = PeriodeCalendrier.objects.get(pk=int(periode_id))
            except (TypeError, ValueError, PeriodeCalendrier.DoesNotExist) as exc:
                raise ValidationError("La période d'un besoin d'encadrement est invalide.") from exc

        mode_calcul = str(ligne.get("mode_calcul") or BesoinEncadrement.MODE_MANUEL).strip()
        if mode_calcul not in dict(BesoinEncadrement.MODES_CALCUL):
            raise ValidationError("Le mode de calcul du besoin est invalide.")
        try:
            effectif = int(ligne.get("effectif_cible", 0) or 0)
            renforts = int(ligne.get("renforts_souhaites", 0) or 0)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Le nombre de postes d'un besoin est invalide.") from exc
        reference = ligne.get("effectif_enfants_reference")
        if reference in (None, ""):
            reference = None
        else:
            try:
                reference = int(reference)
            except (TypeError, ValueError) as exc:
                raise ValidationError("La fréquentation de référence est invalide.") from exc
        if mode_calcul == BesoinEncadrement.MODE_MANUEL and effectif < 1:
            raise ValidationError("Le nombre de postes doit être d'au moins 1 en mode manuel.")
        if reference is not None and reference < 0:
            raise ValidationError("La fréquentation de référence ne peut pas être négative.")
        if renforts < 0:
            raise ValidationError("Le nombre de renforts ne peut pas être négatif.")

        cle = (type_accueil.pk, modalite.pk if modalite else None, periode.pk if periode else None)
        if cle in cles:
            raise ValidationError("Un même contexte d'encadrement est renseigné plusieurs fois.")
        cles.add(cle)

        qualifications = {}
        for qualification_id, nombre in (ligne.get("qualifications_requises") or {}).items():
            try:
                qualification_id = int(qualification_id)
                nombre = int(nombre)
            except (TypeError, ValueError):
                continue
            if nombre > 0:
                qualifications[qualification_id] = nombre
        ids_valides = set(Qualification.objects.filter(pk__in=qualifications).values_list("pk", flat=True))
        qualifications = {qid: nombre for qid, nombre in qualifications.items() if qid in ids_valides}
        normalisees.append((type_accueil, modalite, periode, mode_calcul, effectif, reference, renforts, qualifications))

    # L'écran pilote les règles générales (sans période précise). Les futures
    # surcharges annuelles restent intactes.
    evenement.besoins_encadrement.filter(
        type_accueil__code__in=(TypeAccueil.VACANCES, TypeAccueil.PERISCOLAIRE),
        periode_calendrier__isnull=True,
    ).delete()
    evenement.besoins_qualifications.filter(
        type_accueil__code__in=(TypeAccueil.VACANCES, TypeAccueil.PERISCOLAIRE),
        periode_calendrier__isnull=True,
    ).delete()

    for type_accueil, modalite, periode, mode_calcul, effectif, reference, renforts, qualifications in normalisees:
        if periode is not None:
            evenement.besoins_encadrement.filter(
                type_accueil=type_accueil,
                modalite_periscolaire=modalite,
                periode_calendrier=periode,
            ).delete()
            evenement.besoins_qualifications.filter(
                type_accueil=type_accueil,
                modalite_periscolaire=modalite,
                periode_calendrier=periode,
            ).delete()
        regle = BesoinEncadrement(
            evenement=evenement,
            type_accueil=type_accueil,
            modalite_periscolaire=modalite,
            periode_calendrier=periode,
            effectif_cible=max(1, effectif),
            mode_calcul=mode_calcul,
            effectif_enfants_reference=reference,
            renforts_souhaites=renforts,
        )
        regle.full_clean()
        regle.save()
        for qualification_id, nombre in qualifications.items():
            besoin = BesoinQualification(
                evenement=evenement,
                qualification_id=qualification_id,
                nombre_minimum=nombre,
                type_accueil=type_accueil,
                modalite_periscolaire=modalite,
                periode_calendrier=periode,
            )
            besoin.full_clean()
            besoin.save()
