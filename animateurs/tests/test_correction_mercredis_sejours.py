from datetime import date
from importlib import import_module

from django.apps import apps
from django.urls import reverse

from animateurs.models import (
    Animateur,
    Centre,
    Document,
    EffectifEnfantsJour,
    Evenement,
    ModalitePeriscolaire,
    ParticipantSejour,
    PeriodeCalendrier,
    PeriodeScolaire,
    Sejour,
    TypeAccueil,
)
from animateurs.services.rattachement_types_accueil import lieux_sejours_a_examiner
from animateurs.tests.base import ConnexionTestCase


class CorrectionMercredisSejoursTests(ConnexionTestCase):
    def test_migration_conserve_alias_et_transfere_relations_sans_supprimer(self):
        ancien = TypeAccueil.objects.get(code="mercredis")
        periscolaire = TypeAccueil.objects.get(code="periscolaire")
        centre = Centre.objects.create(nom="Accueil mercredi", code="AM")
        groupe = Evenement.objects.create(centre=centre, nom="Mercredi journée")
        groupe.types_accueil.add(ancien)
        periode = PeriodeScolaire.objects.create(
            nom="Mercredi septembre", annee_scolaire="2038-2039", zone="A",
            debut=date(2038, 9, 1), fin=date(2038, 9, 1), type_accueil=ancien,
        )
        periode.types_accueil.add(ancien)
        effectif = EffectifEnfantsJour.objects.create(
            evenement=groupe, date=date(2038, 9, 1), nombre=18, type_accueil=ancien,
        )
        document = Document.objects.create(titre="Document mercredi", fichier="documents/mercredi.pdf")
        document.types_accueil.add(ancien)

        import_module("animateurs.migrations.0088_modalites_periscolaires_et_structure_sejours").migrer_mercredis(apps, None)

        ancien.refresh_from_db()
        periode.refresh_from_db()
        effectif.refresh_from_db()
        groupe.refresh_from_db()
        self.assertFalse(ancien.actif)
        self.assertEqual(periode.type_accueil, periscolaire)
        self.assertEqual(periode.modalite_periscolaire.code, "mercredi_journee")
        self.assertEqual(effectif.type_accueil, periscolaire)
        self.assertEqual(effectif.modalite_periscolaire.code, "mercredi_journee")
        self.assertTrue(groupe.types_accueil.filter(pk=ancien.pk).exists())
        self.assertTrue(groupe.types_accueil.filter(pk=periscolaire.pk).exists())
        self.assertTrue(document.modalites_periscolaires.filter(code="mercredi_journee").exists())

    def test_sejour_garde_type_dates_participants_equipe_et_avertissement_non_bloquant(self):
        reference = PeriodeCalendrier.objects.create(
            categorie="vacances", nom="Été", annee_scolaire="2038-2039", zone="A",
            debut=date(2039, 7, 9), fin=date(2039, 7, 20),
        )
        responsable = Animateur.objects.create(prenom="Lina", nom="Responsable")
        membre = Animateur.objects.create(prenom="Sam", nom="Équipe")
        document = Document.objects.create(titre="Projet séjour", fichier="documents/sejour.pdf")
        sejour = Sejour.objects.create(
            nom="Séjour montagne", date_debut=date(2039, 7, 6), date_fin=date(2039, 7, 12),
            destination="Alpes", hebergement="Chalet", periode_vacances=reference, responsable=responsable,
        )
        sejour.equipe.add(membre)
        sejour.documents.add(document)
        ParticipantSejour.objects.create(sejour=sejour, prenom="Camille", nom="Enfant")

        self.assertEqual(sejour.type_accueil.code, "sejours")
        self.assertTrue(sejour.avertissement_periode_vacances)
        self.assertEqual(sejour.participants.count(), 1)
        self.assertEqual(sejour.equipe.get(), membre)
        self.assertEqual(sejour.documents.get(), document)

    def test_lieux_historiques_sont_seulement_identifies(self):
        lieu = Centre.objects.create(nom="Camp été historique", code="CEH")

        self.assertEqual(list(lieux_sejours_a_examiner()), [lieu])
        lieu.refresh_from_db()
        self.assertEqual(lieu.nom, "Camp été historique")
        self.assertFalse(hasattr(lieu, "sejour_migre") and lieu.sejour_migre is not None)

    def test_selecteur_principal_ne_propose_plus_mercredis(self):
        response = self.client.get(reverse("gestion"), {"onglet": "periodes-scolaires"})

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '<option value="mercredis">', html=False)
        self.assertContains(response, '<option value="periscolaire">', html=False)
