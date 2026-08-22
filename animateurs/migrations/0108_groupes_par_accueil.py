from django.db import migrations, models
import django.db.models.deletion


def _accueil_principal(AccueilCentre, centre_id, type_accueil_id):
    qs = AccueilCentre.objects.filter(centre_id=centre_id, type_accueil_id=type_accueil_id).order_by("libelle", "id")
    return qs.filter(libelle="").first() or qs.first()


def _copier_instance(apps, source, accueil, type_accueil):
    Evenement = apps.get_model("animateurs", "Evenement")
    DateExclueEvenement = apps.get_model("animateurs", "DateExclueEvenement")
    BesoinEncadrement = apps.get_model("animateurs", "BesoinEncadrement")
    BesoinQualification = apps.get_model("animateurs", "BesoinQualification")
    EffectifEnfantsJour = apps.get_model("animateurs", "EffectifEnfantsJour")
    Affectation = apps.get_model("animateurs", "Affectation")
    AffiniteGroupeAnimateur = apps.get_model("animateurs", "AffiniteGroupeAnimateur")

    clone = Evenement.objects.create(
        groupe_id=source.groupe_id,
        centre_id=source.centre_id,
        accueil_centre_id=accueil.id,
        nom=source.nom,
        cle_unique=source.cle_unique,
        permanent=source.permanent,
        modalite_periscolaire_id=source.modalite_periscolaire_id,
        ferme_jours_feries=source.ferme_jours_feries,
        effectif_cible=source.effectif_cible,
        enfants_par_animateur_defaut=source.enfants_par_animateur_defaut,
        jours_ouverts=source.jours_ouverts,
        ordre=source.ordre,
    )
    clone.types_accueil.add(type_accueil)

    # Ne recopier que les semaines compatibles avec l'accueil cible.
    for periode in source.periodes_scolaires.all():
        ids_types = set(periode.types_accueil.values_list("id", flat=True))
        if periode.type_accueil_id == type_accueil.id or type_accueil.id in ids_types:
            clone.periodes_scolaires.add(periode)

    for fermeture in DateExclueEvenement.objects.filter(evenement_id=source.id):
        DateExclueEvenement.objects.get_or_create(
            evenement_id=clone.id,
            date=fermeture.date,
            defaults={"motif": fermeture.motif},
        )

    # Les besoins explicitement liés au type suivent la nouvelle instance.
    BesoinEncadrement.objects.filter(
        evenement_id=source.id,
        type_accueil_id=type_accueil.id,
    ).update(evenement_id=clone.id)

    # Les besoins de qualification génériques sont dupliqués ; les besoins
    # contextualisés sont déplacés vers l'accueil correspondant.
    for besoin in BesoinQualification.objects.filter(evenement_id=source.id):
        if besoin.type_accueil_id == type_accueil.id:
            besoin.evenement_id = clone.id
            besoin.save(update_fields=["evenement"])
        elif besoin.type_accueil_id is None:
            BesoinQualification.objects.get_or_create(
                evenement_id=clone.id,
                qualification_id=besoin.qualification_id,
                type_accueil_id=None,
                modalite_periscolaire_id=besoin.modalite_periscolaire_id,
                periode_calendrier_id=besoin.periode_calendrier_id,
                defaults={"nombre_minimum": besoin.nombre_minimum},
            )

    # Effectifs et affectations déjà contextualisés restent dans le bon accueil.
    EffectifEnfantsJour.objects.filter(
        evenement_id=source.id,
        type_accueil_id=type_accueil.id,
    ).update(evenement_id=clone.id)
    if type_accueil.code == "periscolaire":
        EffectifEnfantsJour.objects.filter(
            evenement_id=source.id,
            type_accueil_id__isnull=True,
            modalite_periscolaire_id__isnull=False,
        ).update(evenement_id=clone.id)

    Affectation.objects.filter(
        evenement_id=source.id,
        type_accueil_id=type_accueil.id,
    ).update(evenement_id=clone.id)
    if type_accueil.code == "periscolaire":
        Affectation.objects.filter(
            evenement_id=source.id,
            type_accueil_id__isnull=True,
            modalite_periscolaire_id__isnull=False,
        ).update(evenement_id=clone.id)

    for affinite in AffiniteGroupeAnimateur.objects.filter(evenement_id=source.id):
        AffiniteGroupeAnimateur.objects.get_or_create(
            animateur_id=affinite.animateur_id,
            evenement_id=clone.id,
            defaults={
                "jours_travailles": affinite.jours_travailles,
                "dernier_jour_travaille": affinite.dernier_jour_travaille,
            },
        )
    return clone


def separer_groupes_par_accueil(apps, schema_editor):
    Evenement = apps.get_model("animateurs", "Evenement")
    AccueilCentre = apps.get_model("animateurs", "AccueilCentre")
    TypeAccueil = apps.get_model("animateurs", "TypeAccueil")
    BesoinEncadrement = apps.get_model("animateurs", "BesoinEncadrement")
    BesoinQualification = apps.get_model("animateurs", "BesoinQualification")

    types_valides = {
        item.id: item
        for item in TypeAccueil.objects.filter(code__in=("vacances", "periscolaire"))
    }

    for evenement in Evenement.objects.prefetch_related(
        "types_accueil", "periodes_scolaires__types_accueil"
    ).order_by("id"):
        types = [item for item in evenement.types_accueil.all() if item.id in types_valides]
        if not types:
            continue

        # Pour conserver au maximum les identifiants historiques, l'instance
        # existante devient prioritairement l'instance Vacances.
        types.sort(key=lambda item: (0 if item.code == "vacances" else 1, item.id))
        principal = types[0]
        accueil_principal = _accueil_principal(
            AccueilCentre, evenement.centre_id, principal.id
        )
        if accueil_principal is not None:
            evenement.accueil_centre_id = accueil_principal.id
            evenement.save(update_fields=["accueil_centre"])
            evenement.types_accueil.set([principal])

        # Créer d'abord les clones tant que l'instance source porte encore
        # toutes ses périodes. Si l'on nettoyait l'instance principale avant,
        # les semaines Périscolaire seraient perdues au moment de la copie.
        for type_accueil in types[1:]:
            accueil = _accueil_principal(
                AccueilCentre, evenement.centre_id, type_accueil.id
            )
            if accueil is None:
                continue
            _copier_instance(apps, evenement, accueil, type_accueil)

        # Nettoyage des périodes et besoins de l'instance principale : les
        # contextes des autres accueils sont maintenant portés par leurs clones.
        periodes_principales = []
        for periode in evenement.periodes_scolaires.all():
            ids_types = set(periode.types_accueil.values_list("id", flat=True))
            if periode.type_accueil_id == principal.id or principal.id in ids_types:
                periodes_principales.append(periode.id)
        evenement.periodes_scolaires.set(periodes_principales)

        # Après création des clones, l'instance principale ne conserve que ses
        # besoins contextualisés (et les besoins génériques de qualification).
        BesoinEncadrement.objects.filter(evenement_id=evenement.id).exclude(
            type_accueil_id=principal.id
        ).delete()
        BesoinQualification.objects.filter(evenement_id=evenement.id).exclude(
            models.Q(type_accueil_id=principal.id) | models.Q(type_accueil_id__isnull=True)
        ).delete()


def noop_reverse(apps, schema_editor):
    # La séparation crée de vraies instances et déplace des données : une
    # reconstruction automatique inverse risquerait de perdre de l'historique.
    pass


class Migration(migrations.Migration):
    # L'ajout de la clé étrangère diffère la création de son index jusqu'à la
    # fin du schema_editor. Sans commit intermédiaire, les écritures de la
    # migration de données laissent des triggers PostgreSQL en attente et la
    # création de cet index échoue avec « pending trigger events ».
    atomic = False

    dependencies = [("animateurs", "0107_accueils_centres_dates_pedt")]

    operations = [
        migrations.AddField(
            model_name="evenement",
            name="accueil_centre",
            field=models.ForeignKey(
                blank=True,
                help_text="Accueil Vacances ou Périscolaire auquel appartient cette instance de groupe.",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="groupes",
                to="animateurs.accueilcentre",
                verbose_name="accueil",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="evenement",
            name="unique_instance_groupe_par_lieu",
        ),
        # IMPORTANT PostgreSQL : cette migration déplace beaucoup de lignes et
        # déclenche donc des événements de contraintes différées. Les index de
        # contrainte ne doivent pas être créés dans la même transaction après
        # ces écritures (erreur ``pending trigger events``). Ils sont ajoutés
        # dans 0109, une fois cette migration entièrement validée/commitée.
        migrations.RunPython(separer_groupes_par_accueil, noop_reverse),
    ]
