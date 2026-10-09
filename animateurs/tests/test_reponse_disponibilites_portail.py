import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from animateurs.models import (
    Animateur,
    CampagneDisponibilite,
    CampagneDisponibiliteBloc,
    CampagneDisponibiliteDate,
    DemandeDisponibilite,
    Disponibilite,
    PropositionDisponibiliteDate,
)
from animateurs.services.demandes_disponibilites import cloturer_campagne, ouvrir_campagne


class ReponseDisponibilitesPortailTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.direction = user_model.objects.create_superuser(
            username="direction", password="secret", email="direction@example.test"
        )
        self.alice_user = user_model.objects.create_user(username="alice", password="secret")
        self.bob_user = user_model.objects.create_user(username="bob", password="secret")
        self.alice = Animateur.objects.create(prenom="Alice", nom="Martin", utilisateur=self.alice_user)
        self.bob = Animateur.objects.create(prenom="Bob", nom="Durand", utilisateur=self.bob_user)

    def _demande(self, *, validation=True, echeance=None, with_half=True):
        campagne = CampagneDisponibilite.objects.create(
            nom="Disponibilités hiver-printemps 2027", cree_par=self.direction,
            validation_direction_requise=validation, date_limite_reponse=echeance,
        )
        hiver = CampagneDisponibiliteBloc.objects.create(campagne=campagne, libelle="Vacances d’hiver", ordre=1)
        for index in range(5):
            CampagneDisponibiliteDate.objects.create(
                campagne=campagne, bloc=hiver, date=datetime.date(2027, 2, 8) + datetime.timedelta(days=index), ordre=index
            )
        if with_half:
            mercredis = CampagneDisponibiliteBloc.objects.create(
                campagne=campagne, libelle="Mercredis", ordre=2,
                mode_saisie=CampagneDisponibiliteBloc.DEMI_JOURNEE,
            )
            for index, day in enumerate((datetime.date(2027, 1, 6), datetime.date(2027, 1, 13)), start=1):
                CampagneDisponibiliteDate.objects.create(campagne=campagne, bloc=mercredis, date=day, ordre=index)
        return ouvrir_campagne(campagne, [self.alice, self.bob])[0]

    def _url(self, demande):
        return reverse("demande_disponibilite_repondre", args=[demande.pk])

    def _post_values(self, demande, value=PropositionDisponibiliteDate.INDISPONIBLE, **extra):
        data = {f"creneau_{p.pk}": value for p in demande.propositions.all()}
        data.update(extra)
        return data

    def test_page_multi_blocs_regroupe_les_vacances_et_affiche_les_dates_isolees(self):
        demande = self._demande()
        self.client.force_login(self.alice_user)

        response = self.client.get(self._url(demande))

        self.assertContains(response, "Semaine du 8 février")
        self.assertContains(response, "Disponible toute la semaine")
        self.assertContains(response, "Mercredis")
        self.assertContains(response, "Matin")
        self.assertContains(response, "À renseigner")

    def test_brouillon_incomplet_garde_les_valeurs_et_le_commentaire(self):
        demande = self._demande()
        self.client.force_login(self.alice_user)
        proposition = demande.propositions.order_by("date").first()

        response = self.client.post(self._url(demande), {
            "action": "brouillon", f"creneau_{proposition.pk}": PropositionDisponibiliteDate.JOURNEE,
            "commentaire_animateur": "Disponible après 13h30.",
        })

        self.assertRedirects(response, self._url(demande))
        demande.refresh_from_db()
        proposition.refresh_from_db()
        self.assertEqual(demande.statut, DemandeDisponibilite.BROUILLON)
        self.assertEqual(proposition.creneau, PropositionDisponibiliteDate.JOURNEE)
        self.assertEqual(demande.commentaire_animateur, "Disponible après 13h30.")
        self.assertTrue(demande.propositions.filter(creneau=PropositionDisponibiliteDate.NON_RENSEIGNE).exists())

    def test_envoi_incomplet_est_refuse_et_indisponible_est_distinct(self):
        demande = self._demande()
        self.client.force_login(self.alice_user)
        proposition = demande.propositions.first()

        self.client.post(self._url(demande), {"action": "envoyer", f"creneau_{proposition.pk}": "indisponible"})

        demande.refresh_from_db()
        proposition.refresh_from_db()
        self.assertEqual(demande.statut, DemandeDisponibilite.BROUILLON)
        self.assertEqual(proposition.creneau, PropositionDisponibiliteDate.INDISPONIBLE)
        self.assertTrue(demande.propositions.filter(creneau=PropositionDisponibiliteDate.NON_RENSEIGNE).exists())

    def test_zero_disponibilite_demande_confirmation_puis_est_envoye(self):
        demande = self._demande(with_half=False)
        self.client.force_login(self.alice_user)
        data = self._post_values(demande, action="envoyer")
        self.client.post(self._url(demande), data)
        demande.refresh_from_db()
        self.assertEqual(demande.statut, DemandeDisponibilite.BROUILLON)

        self.client.post(self._url(demande), self._post_values(demande, action="envoyer", confirmer_zero="1"))
        demande.refresh_from_db()
        self.assertEqual(demande.statut, DemandeDisponibilite.ENVOYEE)
        self.assertFalse(Disponibilite.objects.filter(animateur=self.alice).exists())

    def test_reponse_envoyee_est_figee_sans_modifier_l_officiel(self):
        demande = self._demande(with_half=False)
        self.client.force_login(self.alice_user)
        self.client.post(self._url(demande), self._post_values(demande, action="envoyer", confirmer_zero="1"))
        demande.refresh_from_db()
        proposition = demande.propositions.first()

        self.client.post(self._url(demande), {"action": "brouillon", f"creneau_{proposition.pk}": "journee"})
        proposition.refresh_from_db()
        self.assertEqual(proposition.creneau, PropositionDisponibiliteDate.INDISPONIBLE)
        self.assertFalse(Disponibilite.objects.filter(animateur=self.alice).exists())

    def test_demi_journee_est_envoyee_sans_conversion_officielle(self):
        demande = self._demande(with_half=True)
        self.client.force_login(self.alice_user)
        values = self._post_values(demande, action="envoyer")
        demi = demande.propositions.filter(date_campagne__bloc__mode_saisie="demi_journee").first()
        values[f"creneau_{demi.pk}"] = PropositionDisponibiliteDate.MATIN

        self.client.post(self._url(demande), values)
        demande.refresh_from_db()
        self.assertEqual(demande.statut, DemandeDisponibilite.ENVOYEE)
        self.assertFalse(Disponibilite.objects.filter(animateur=self.alice).exists())

    def test_application_automatique_garde_la_reponse_demi_journee_pour_la_direction(self):
        demande = self._demande(validation=False, with_half=True)
        self.client.force_login(self.alice_user)
        values = self._post_values(demande, action="envoyer")
        demi = demande.propositions.filter(date_campagne__bloc__mode_saisie="demi_journee").first()
        values[f"creneau_{demi.pk}"] = PropositionDisponibiliteDate.APRES_MIDI

        self.client.post(self._url(demande), values)

        demande.refresh_from_db()
        self.assertEqual(demande.statut, DemandeDisponibilite.ENVOYEE)
        self.assertFalse(Disponibilite.objects.filter(animateur=self.alice).exists())
        self.assertContains(self.client.get(self._url(demande)), "nécessitent une prise en compte")

    def test_echeance_depassee_ne_bloque_pas_mais_cloture_bloque_le_post(self):
        demande = self._demande(echeance=datetime.date(2020, 1, 1), with_half=False)
        self.client.force_login(self.alice_user)
        response = self.client.get(self._url(demande))
        self.assertContains(response, "Échéance dépassée")

        cloturer_campagne(demande.campagne)
        response = self.client.post(self._url(demande), self._post_values(demande, action="brouillon"))
        self.assertRedirects(response, self._url(demande))
        demande.refresh_from_db()
        self.assertEqual(demande.statut, DemandeDisponibilite.A_RENSEIGNER)

    def test_autre_animateur_est_inaccessible_et_apercu_direction_est_lecture_seule(self):
        demande = self._demande(with_half=False)
        self.client.force_login(self.bob_user)
        self.assertEqual(self.client.get(self._url(demande)).status_code, 404)

        self.client.force_login(self.direction)
        preview_url = f"{self._url(demande)}?apercu_portail=1&animateur_id={self.alice.pk}"
        response = self.client.get(preview_url)
        self.assertContains(response, "lecture seule")
        response = self.client.post(preview_url, self._post_values(demande, action="brouillon"))
        self.assertEqual(response.status_code, 403)

    def test_correction_historique_sans_bloc_reste_a_la_journee(self):
        originale = self._demande(with_half=False)
        correction = DemandeDisponibilite.objects.create(
            animateur=self.alice, nature=DemandeDisponibilite.MODIFICATION,
            statut=DemandeDisponibilite.BROUILLON, demande_precedente=originale,
        )
        proposition = PropositionDisponibiliteDate.objects.create(
            demande=correction, date=datetime.date(2027, 2, 8),
            creneau=PropositionDisponibiliteDate.JOURNEE, etait_disponible=False,
        )
        self.client.force_login(self.alice_user)
        html = self.client.get(self._url(correction)).content.decode()
        controles = html.split(f'name="creneau_{proposition.pk}"', 1)[1].split("</article>", 1)[0]
        self.assertIn("Indisponible", controles)
        self.assertIn("Journée entière", controles)
        self.assertNotIn("Matin", controles)
        self.assertNotIn("Après-midi", controles)
