import datetime

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from animateurs.models import (
    Animateur,
    CampagneDisponibilite,
    CampagneDisponibiliteBloc,
    CampagneDisponibiliteDate,
    DemandeDisponibilite,
    Disponibilite,
    PeriodeScolaire,
    PropositionDisponibiliteDate,
    TypeAccueil,
)
from animateurs.services.demandes_disponibilites import (
    ApplicationDemandeDisponibiliteEnConflit,
    ApplicationDemandeDisponibiliteGranulariteNonSupportee,
    DemandeDisponibiliteIncomplete,
    appliquer_demande_validee,
    creer_demande_modification,
    creer_version_correction,
    demander_correction,
    envoyer_demande,
    ouvrir_campagne,
    refuser_demande,
)


class DemandesDisponibilitesServicesTests(TestCase):
    def setUp(self):
        self.direction = get_user_model().objects.create_superuser(
            username="direction", password="secret", email="direction@example.test"
        )
        self.alice = Animateur.objects.create(prenom="Alice", nom="Martin")
        self.bob = Animateur.objects.create(prenom="Bob", nom="Durand")
        self.vacances, _ = TypeAccueil.objects.get_or_create(
            code=TypeAccueil.VACANCES, defaults={"nom": "Vacances", "ordre": 1}
        )

    def _periode(self, nom, debut):
        return PeriodeScolaire.objects.create(
            nom=nom,
            annee_scolaire="2027-2028",
            zone="A",
            debut=debut,
            fin=debut + datetime.timedelta(days=4),
            type_accueil=self.vacances,
        )

    def _campagne_multi_periodes(self):
        hiver = self._periode("Hiver — Semaine 1", datetime.date(2027, 2, 8))
        printemps = self._periode("Printemps — Semaine 1", datetime.date(2027, 4, 12))
        campagne = CampagneDisponibilite.objects.create(
            nom="Disponibilités hiver-printemps 2027", cree_par=self.direction,
            date_limite_reponse=datetime.date(2027, 1, 31),
        )
        bloc_hiver = CampagneDisponibiliteBloc.objects.create(
            campagne=campagne, libelle="Vacances d'hiver", ordre=1
        )
        bloc_printemps = CampagneDisponibiliteBloc.objects.create(
            campagne=campagne, libelle="Vacances de printemps", ordre=2
        )
        dates = [
            (bloc_hiver, hiver, hiver.debut),
            (bloc_hiver, hiver, hiver.debut + datetime.timedelta(days=1)),
            (bloc_printemps, printemps, printemps.debut),
            (bloc_printemps, printemps, printemps.debut + datetime.timedelta(days=2)),
        ]
        for ordre, (bloc, periode, jour) in enumerate(dates, start=1):
            CampagneDisponibiliteDate.objects.create(
                campagne=campagne, bloc=bloc, date=jour, ordre=ordre,
                periode_scolaire_source=periode,
            )
        return campagne, [item[2] for item in dates]

    def _demande_envoyee(self, propositions):
        demande = creer_demande_modification(self.alice, propositions)
        return envoyer_demande(demande)

    def _plages(self):
        return list(
            Disponibilite.objects.filter(animateur=self.alice)
            .order_by("debut", "fin").values_list("debut", "fin")
        )

    def test_campagne_multi_periodes_conserve_dates_et_cree_un_destinataire_par_animateur(self):
        campagne, dates = self._campagne_multi_periodes()

        demandes = ouvrir_campagne(campagne, [self.alice, self.bob])

        campagne.refresh_from_db()
        self.assertEqual(campagne.statut, CampagneDisponibilite.OUVERTE)
        self.assertEqual(len(demandes), 2)
        self.assertEqual(
            list(campagne.dates.order_by("date").values_list("date", flat=True)), sorted(dates)
        )
        for demande in demandes:
            self.assertEqual(demande.statut, DemandeDisponibilite.A_RENSEIGNER)
            self.assertEqual(
                list(demande.propositions.order_by("date").values_list("date", flat=True)), sorted(dates)
            )

    def test_brouillon_est_explicite_et_ne_modifie_jamais_l_officiel(self):
        campagne, _ = self._campagne_multi_periodes()
        demande = ouvrir_campagne(campagne, [self.alice])[0]
        demande.transition_vers(DemandeDisponibilite.BROUILLON)
        demande.save(update_fields=["statut"])

        self.assertEqual(demande.statut, DemandeDisponibilite.BROUILLON)
        self.assertFalse(Disponibilite.objects.filter(animateur=self.alice).exists())

    def test_nouvelle_proposition_est_non_renseignee_et_differe_d_une_indisponibilite(self):
        campagne, _ = self._campagne_multi_periodes()
        demande = ouvrir_campagne(campagne, [self.alice])[0]

        self.assertTrue(demande.propositions.filter(creneau=PropositionDisponibiliteDate.NON_RENSEIGNE).exists())
        self.assertFalse(demande.propositions.filter(creneau=PropositionDisponibiliteDate.INDISPONIBLE).exists())

    def test_envoi_refuse_toute_date_non_renseignee(self):
        campagne, _ = self._campagne_multi_periodes()
        demande = ouvrir_campagne(campagne, [self.alice])[0]

        with self.assertRaises(DemandeDisponibiliteIncomplete):
            envoyer_demande(demande)
        demande.refresh_from_db()
        self.assertEqual(demande.statut, DemandeDisponibilite.A_RENSEIGNER)

    def test_contraintes_de_creneau_suivent_le_mode_du_bloc(self):
        campagne, _ = self._campagne_multi_periodes()
        bloc_journee = campagne.blocs.first()
        demande = ouvrir_campagne(campagne, [self.alice])[0]
        proposition = demande.propositions.filter(date_campagne__bloc=bloc_journee).first()
        proposition.creneau = PropositionDisponibiliteDate.MATIN
        with self.assertRaises(ValidationError):
            proposition.save(update_fields=["creneau"])

        campagne_demi = CampagneDisponibilite.objects.create(nom="Mercredis", cree_par=self.direction)
        bloc_demi = CampagneDisponibiliteBloc.objects.create(
            campagne=campagne_demi,
            libelle="Mercredis",
            mode_saisie=CampagneDisponibiliteBloc.DEMI_JOURNEE,
        )
        CampagneDisponibiliteDate.objects.create(
            campagne=campagne_demi, bloc=bloc_demi, date=datetime.date(2027, 3, 10)
        )
        demande_demi = ouvrir_campagne(campagne_demi, [self.bob])[0]
        proposition_demi = demande_demi.propositions.filter(date_campagne__bloc=bloc_demi).first()
        proposition_demi.creneau = PropositionDisponibiliteDate.MATIN
        proposition_demi.save(update_fields=["creneau"])
        self.assertEqual(proposition_demi.creneau, PropositionDisponibiliteDate.MATIN)

    def test_demi_journee_ne_peut_pas_etre_appliquee_et_une_demande_mixte_reste_intacte(self):
        jour_matin = datetime.date(2027, 3, 5)
        jour_entier = datetime.date(2027, 3, 6)
        demande = self._demande_envoyee({
            jour_matin: PropositionDisponibiliteDate.MATIN,
            jour_entier: PropositionDisponibiliteDate.JOURNEE,
        })

        with self.assertRaises(ApplicationDemandeDisponibiliteGranulariteNonSupportee):
            appliquer_demande_validee(demande, traite_par=self.direction)
        self.assertFalse(Disponibilite.objects.filter(animateur=self.alice).exists())
        demande.refresh_from_db()
        self.assertEqual(demande.statut, DemandeDisponibilite.ENVOYEE)

    def test_reponse_initiale_zero_disponibilite_est_envoyable_sans_modifier_l_officiel(self):
        campagne, _ = self._campagne_multi_periodes()
        demande = ouvrir_campagne(campagne, [self.alice])[0]

        demande.propositions.update(creneau=PropositionDisponibiliteDate.INDISPONIBLE)
        envoyer_demande(demande)

        demande.refresh_from_db()
        self.assertEqual(demande.statut, DemandeDisponibilite.ENVOYEE)
        self.assertFalse(demande.propositions.exclude(creneau=PropositionDisponibiliteDate.INDISPONIBLE).exists())
        self.assertFalse(Disponibilite.objects.filter(animateur=self.alice).exists())

    def test_transition_illegale_est_refusee(self):
        demande = creer_demande_modification(self.alice, {datetime.date(2027, 3, 5): PropositionDisponibiliteDate.INDISPONIBLE})
        with self.assertRaises(ValidationError):
            demande.transition_vers(DemandeDisponibilite.VALIDEE)

    def test_save_ne_permet_pas_de_contourner_les_transitions(self):
        demande = creer_demande_modification(self.alice, {datetime.date(2027, 3, 5): PropositionDisponibiliteDate.INDISPONIBLE})
        demande.statut = DemandeDisponibilite.VALIDEE
        with self.assertRaises(ValidationError):
            demande.save()

    def test_campagne_sans_validation_applique_la_reponse_initiale_a_l_envoi(self):
        campagne, dates = self._campagne_multi_periodes()
        campagne.validation_direction_requise = False
        campagne.save(update_fields=["validation_direction_requise"])
        demande = ouvrir_campagne(campagne, [self.alice])[0]
        proposition = demande.propositions.order_by("date").first()
        demande.propositions.update(creneau=PropositionDisponibiliteDate.INDISPONIBLE)
        proposition.creneau = PropositionDisponibiliteDate.JOURNEE
        proposition.save(update_fields=["creneau"])

        envoyer_demande(demande)

        demande.refresh_from_db()
        self.assertEqual(demande.statut, DemandeDisponibilite.VALIDEE)
        self.assertTrue(Disponibilite.objects.filter(animateur=self.alice, debut=dates[0], fin=dates[0]).exists())

    def test_modification_ciblee_ne_change_pas_l_officiel_avant_validation(self):
        Disponibilite.objects.create(
            animateur=self.alice, debut=datetime.date(2027, 3, 3), fin=datetime.date(2027, 3, 7)
        )
        demande = self._demande_envoyee({datetime.date(2027, 3, 5): PropositionDisponibiliteDate.INDISPONIBLE})

        self.assertEqual(self._plages(), [(datetime.date(2027, 3, 3), datetime.date(2027, 3, 7))])
        self.assertEqual(demande.propositions.get().etait_disponible, True)

    def test_validation_supprime_uniquement_la_date_concernee_et_conserve_les_autres(self):
        Disponibilite.objects.create(
            animateur=self.alice, debut=datetime.date(2027, 3, 3), fin=datetime.date(2027, 3, 7)
        )
        demande = self._demande_envoyee({datetime.date(2027, 3, 5): PropositionDisponibiliteDate.INDISPONIBLE})

        appliquer_demande_validee(demande, traite_par=self.direction)

        demande.refresh_from_db()
        self.assertEqual(demande.statut, DemandeDisponibilite.VALIDEE)
        self.assertEqual(self._plages(), [
            (datetime.date(2027, 3, 3), datetime.date(2027, 3, 4)),
            (datetime.date(2027, 3, 6), datetime.date(2027, 3, 7)),
        ])

    def test_validation_ajoute_une_date_et_recompresse_les_plages_contigues(self):
        Disponibilite.objects.create(
            animateur=self.alice, debut=datetime.date(2027, 3, 3), fin=datetime.date(2027, 3, 4)
        )
        Disponibilite.objects.create(
            animateur=self.alice, debut=datetime.date(2027, 3, 6), fin=datetime.date(2027, 3, 7)
        )
        demande = self._demande_envoyee({datetime.date(2027, 3, 5): PropositionDisponibiliteDate.JOURNEE})

        appliquer_demande_validee(demande, traite_par=self.direction)

        self.assertEqual(self._plages(), [(datetime.date(2027, 3, 3), datetime.date(2027, 3, 7))])

    def test_decoupage_conserve_les_types_accueil_existants(self):
        mercredi, _ = TypeAccueil.objects.get_or_create(
            code=TypeAccueil.MERCREDIS, defaults={"nom": "Mercredis", "ordre": 2}
        )
        officielle = Disponibilite.objects.create(
            animateur=self.alice, debut=datetime.date(2027, 3, 3), fin=datetime.date(2027, 3, 7)
        )
        officielle.types_accueil.add(mercredi)
        demande = self._demande_envoyee({datetime.date(2027, 3, 5): PropositionDisponibiliteDate.INDISPONIBLE})

        appliquer_demande_validee(demande, traite_par=self.direction)

        self.assertEqual(self._plages(), [
            (datetime.date(2027, 3, 3), datetime.date(2027, 3, 4)),
            (datetime.date(2027, 3, 6), datetime.date(2027, 3, 7)),
        ])
        for plage in Disponibilite.objects.filter(animateur=self.alice):
            self.assertEqual(list(plage.types_accueil.values_list("id", flat=True)), [mercredi.id])

    def test_conflit_bloque_la_validation_si_l_officiel_a_change(self):
        Disponibilite.objects.create(
            animateur=self.alice, debut=datetime.date(2027, 3, 3), fin=datetime.date(2027, 3, 7)
        )
        demande = self._demande_envoyee({datetime.date(2027, 3, 5): PropositionDisponibiliteDate.INDISPONIBLE})
        Disponibilite.objects.filter(animateur=self.alice).delete()

        with self.assertRaises(ApplicationDemandeDisponibiliteEnConflit) as erreur:
            appliquer_demande_validee(demande, traite_par=self.direction)

        self.assertEqual(erreur.exception.conflits[0].date, datetime.date(2027, 3, 5))
        demande.refresh_from_db()
        self.assertEqual(demande.statut, DemandeDisponibilite.ENVOYEE)

    def test_historique_conserve_la_demande_envoyee_et_lie_la_nouvelle_version(self):
        premiere = self._demande_envoyee({datetime.date(2027, 3, 5): PropositionDisponibiliteDate.JOURNEE})
        seconde = creer_demande_modification(
            self.alice, {datetime.date(2027, 3, 5): PropositionDisponibiliteDate.INDISPONIBLE}, demande_precedente=premiere
        )

        premiere.refresh_from_db()
        self.assertEqual(premiere.statut, DemandeDisponibilite.ENVOYEE)
        self.assertEqual(seconde.demande_precedente_id, premiere.id)
        self.assertEqual(seconde.statut, DemandeDisponibilite.BROUILLON)
        self.assertEqual(premiere.propositions.get().creneau, PropositionDisponibiliteDate.JOURNEE)
        self.assertEqual(seconde.propositions.get().creneau, PropositionDisponibiliteDate.INDISPONIBLE)

    def test_proposition_envoyee_est_figee_et_correction_cree_une_nouvelle_version(self):
        premiere = self._demande_envoyee({datetime.date(2027, 3, 5): PropositionDisponibiliteDate.JOURNEE})
        proposition = premiere.propositions.get()
        proposition.creneau = PropositionDisponibiliteDate.INDISPONIBLE
        with self.assertRaises(ValidationError):
            proposition.save(update_fields=["creneau"])

        premiere = demander_correction(
            premiere, traite_par=self.direction, commentaire_direction="Précise ce jour."
        )
        correction = creer_version_correction(
            premiere, {datetime.date(2027, 3, 5): PropositionDisponibiliteDate.INDISPONIBLE}, commentaire_animateur="Indisponible finalement."
        )

        premiere.refresh_from_db()
        self.assertEqual(premiere.statut, DemandeDisponibilite.A_CORRIGER)
        self.assertEqual(correction.demande_precedente_id, premiere.id)
        self.assertEqual(correction.statut, DemandeDisponibilite.BROUILLON)

    def test_refus_ne_modifie_pas_l_officiel(self):
        Disponibilite.objects.create(
            animateur=self.alice, debut=datetime.date(2027, 3, 3), fin=datetime.date(2027, 3, 7)
        )
        demande = self._demande_envoyee({datetime.date(2027, 3, 5): PropositionDisponibiliteDate.INDISPONIBLE})

        refuser_demande(demande, traite_par=self.direction, commentaire_direction="À conserver.")

        demande.refresh_from_db()
        self.assertEqual(demande.statut, DemandeDisponibilite.REFUSEE)
        self.assertEqual(self._plages(), [(datetime.date(2027, 3, 3), datetime.date(2027, 3, 7))])
