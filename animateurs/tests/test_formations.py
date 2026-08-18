import json
import datetime
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from animateurs.models import Affectation, Animateur, Centre, Disponibilite, Document, Formation, ParticipationFormation, Qualification
from animateurs.services.affectations import creer_affectation
from animateurs.services.disponibilites import disponibilite_effective
from animateurs.services.planning_solver import generer_planning_auto
from animateurs.tests.base import ConnexionTestCase
from animateurs.tests.factories import creer_groupe


class FormationApiTests(ConnexionTestCase):
    def setUp(self):
        self.bruno = Animateur.objects.create(prenom="Bruno", nom="Vaujour")
        self.julie = Animateur.objects.create(prenom="Julie", nom="Martin")
        self.bafa = Qualification.objects.create(nom="BAFA")
        self.payload = {
            "intitule": "BAFA — Approfondissement grands jeux",
            "animateur_ids": [self.bruno.id, self.julie.id],
            "date_debut": "2026-10-12",
            "date_fin": "2026-10-17",
            "organisme": "UFCV",
            "lieu": "Roanne",
            "statut": Formation.STATUT_PREVUE,
            "qualification_id": self.bafa.id,
            "commentaire": "Formation résidentielle",
        }

    def _post(self, payload=None):
        return self.client.post(
            reverse("api_formations"),
            data=json.dumps(payload or self.payload),
            content_type="application/json",
        )

    def _creer_a_cloturer(self, **changes):
        payload = {**self.payload, "date_debut": "2026-08-01", "date_fin": "2026-08-02", **changes}
        response = self._post(payload)
        self.assertEqual(response.status_code, 201)
        return response.json()["id"]

    def _cloturer(self, formation_id, presents=None):
        presents = set(presents if presents is not None else [self.bruno.id, self.julie.id])
        return self.client.post(
            reverse("api_formation_cloture", args=[formation_id]),
            data=json.dumps({"presences": [
                {"animateur_id": animateur_id, "presence": "present" if animateur_id in presents else "absent"}
                for animateur_id in [self.bruno.id, self.julie.id]
            ]}),
            content_type="application/json",
        )

    def test_creation_avec_plusieurs_animateurs(self):
        response = self._post()

        self.assertEqual(response.status_code, 201)
        formation = Formation.objects.get()
        self.assertEqual(formation.intitule, self.payload["intitule"])
        self.assertEqual(set(formation.animateurs.values_list("id", flat=True)), {self.bruno.id, self.julie.id})
        self.assertEqual(formation.qualification, self.bafa)
        self.assertEqual(len(response.json()["animateurs"]), 2)
        self.assertEqual(
            set(formation.participations.values_list("presence", flat=True)),
            {ParticipationFormation.PRESENCE_A_CONFIRMER},
        )

    def test_statut_est_calcule_selon_la_date_et_annulation_prioritaire(self):
        formation = Formation(
            date_debut=datetime.date(2026, 8, 24),
            date_fin=datetime.date(2026, 8, 26),
            statut=Formation.STATUT_PREVUE,
        )
        self.assertEqual(formation.statut_calcule(datetime.date(2026, 8, 23)), Formation.STATUT_PREVUE)
        self.assertEqual(formation.statut_calcule(datetime.date(2026, 8, 24)), Formation.STATUT_EN_COURS)
        self.assertEqual(formation.statut_calcule(datetime.date(2026, 8, 26)), Formation.STATUT_EN_COURS)
        self.assertEqual(formation.statut_calcule(datetime.date(2026, 8, 27)), Formation.STATUT_A_CLOTURER)
        formation.statut = Formation.STATUT_ANNULEE
        self.assertEqual(formation.statut_calcule(datetime.date(2026, 8, 27)), Formation.STATUT_ANNULEE)

    def test_cloture_enregistre_present_et_absent_et_qualifie_seulement_le_present(self):
        formation_id = self._creer_a_cloturer()

        response = self._cloturer(formation_id, presents=[self.bruno.id])

        self.assertEqual(response.status_code, 200)
        formation = Formation.objects.get(pk=formation_id)
        self.assertEqual(formation.statut, Formation.STATUT_TERMINEE)
        self.assertEqual(formation.participations.get(animateur=self.bruno).presence, ParticipationFormation.PRESENCE_PRESENT)
        self.assertEqual(formation.participations.get(animateur=self.julie).presence, ParticipationFormation.PRESENCE_ABSENT)
        self.assertTrue(self.bruno.qualifications.filter(pk=self.bafa.id).exists())
        self.assertFalse(self.julie.qualifications.filter(pk=self.bafa.id).exists())
        self.assertEqual(response.json()["statut"], Formation.STATUT_TERMINEE)

    def test_cloture_refuse_une_presence_non_confirmee(self):
        formation_id = self._creer_a_cloturer()
        response = self.client.post(
            reverse("api_formation_cloture", args=[formation_id]),
            data=json.dumps({"presences": [{"animateur_id": self.bruno.id, "presence": "present"}]}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Formation.objects.get(pk=formation_id).statut, Formation.STATUT_PREVUE)

    def test_modification(self):
        formation_id = self._post().json()["id"]
        payload = {**self.payload, "intitule": "BAFA perfectionnement", "statut": Formation.STATUT_ANNULEE, "animateur_ids": [self.julie.id]}

        response = self.client.patch(
            reverse("api_formation_detail", args=[formation_id]),
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        formation = Formation.objects.get(pk=formation_id)
        self.assertEqual(formation.intitule, "BAFA perfectionnement")
        self.assertEqual(formation.statut, Formation.STATUT_ANNULEE)
        self.assertEqual(list(formation.animateurs.all()), [self.julie])

    def test_suppression_ne_modifie_ni_animateur_ni_qualification(self):
        formation_id = self._post().json()["id"]

        response = self.client.delete(reverse("api_formation_detail", args=[formation_id]))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Formation.objects.filter(pk=formation_id).exists())
        self.assertTrue(Animateur.objects.filter(pk=self.bruno.id).exists())
        self.assertTrue(Qualification.objects.filter(pk=self.bafa.id).exists())

    def test_refuse_date_de_fin_anterieure(self):
        response = self._post({**self.payload, "date_debut": "2026-10-17", "date_fin": "2026-10-12"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("antérieure", response.json()["error"])
        self.assertFalse(Formation.objects.exists())

    def test_refuse_formation_sans_animateur(self):
        response = self._post({**self.payload, "animateur_ids": []})

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Formation.objects.exists())

    def test_filtre_par_statut(self):
        self._post()
        formation_id = self._creer_a_cloturer(intitule="PSC1")
        self._cloturer(formation_id)

        response = self.client.get(reverse("api_formations"), {"statut": Formation.STATUT_TERMINEE})

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["intitule"] for item in response.json()["formations"]], ["PSC1"])

    def test_coordonnees_hebergement_et_qualification_libre(self):
        response = self._post({
            **self.payload,
            "email_contact": "contact@ufcv.fr",
            "telephone_contact": "+33 4 77 00 00 00",
            "hebergement": Formation.HEBERGEMENT_INTERNAT,
            "qualification_libre": "HACCP",
        })

        self.assertEqual(response.status_code, 201)
        formation = Formation.objects.get()
        self.assertEqual(formation.email_contact, "contact@ufcv.fr")
        self.assertEqual(formation.telephone_contact, "+33 4 77 00 00 00")
        self.assertEqual(formation.hebergement, Formation.HEBERGEMENT_INTERNAT)
        self.assertTrue(Qualification.objects.filter(cle_unique="haccp").exists())
        self.assertFalse(self.bruno.qualifications.filter(cle_unique="haccp").exists())

    def test_externat_et_email_invalide(self):
        externe = self._post({**self.payload, "intitule": "Externat", "hebergement": Formation.HEBERGEMENT_EXTERNAT})
        invalide = self._post({**self.payload, "intitule": "Email invalide", "email_contact": "pas-un-email"})

        self.assertEqual(externe.status_code, 201)
        self.assertEqual(Formation.objects.get(intitule="Externat").hebergement, Formation.HEBERGEMENT_EXTERNAT)
        self.assertEqual(invalide.status_code, 400)

    def test_prevue_et_en_cours_n_attribuent_pas_la_qualification_existante(self):
        self._post()
        self._post({**self.payload, "intitule": "En cours", "date_debut": "2026-08-18", "date_fin": "2026-08-20"})

        self.assertFalse(self.bruno.qualifications.filter(pk=self.bafa.id).exists())
        self.assertFalse(self.julie.qualifications.filter(pk=self.bafa.id).exists())

    def test_terminee_attribue_la_qualification_a_tous_sans_doublon(self):
        self.bruno.qualifications.add(self.bafa)
        formation_id = self._creer_a_cloturer()
        response = self._cloturer(formation_id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.bruno.qualifications.filter(pk=self.bafa.id).count(), 1)
        self.assertEqual(self.julie.qualifications.filter(pk=self.bafa.id).count(), 1)

    def test_qualification_libre_est_creee_reutilisee_et_attribuee(self):
        existante = Qualification.objects.create(nom="PSC1")
        formation_id = self._creer_a_cloturer(
            qualification_id=None,
            qualification_libre="  psc1  ",
        )
        response = self._cloturer(formation_id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Qualification.objects.filter(cle_unique="psc1").count(), 1)
        self.assertTrue(self.bruno.qualifications.filter(pk=existante.id).exists())
        self.assertTrue(self.julie.qualifications.filter(pk=existante.id).exists())

    def test_qualification_libre_distincte_complete_la_qualification_existante(self):
        formation_id = self._creer_a_cloturer(qualification_libre="HACCP")
        self._cloturer(formation_id)

        self.assertEqual(set(self.bruno.qualifications.values_list("cle_unique", flat=True)), {"bafa", "haccp"})

    def test_modifications_repetees_et_sortie_du_statut_terminee_conservent_les_qualifications(self):
        formation_id = self._creer_a_cloturer(qualification_libre="PSC1")
        self._cloturer(formation_id)
        payload = {**self.payload, "qualification_libre": "PSC1", "statut": Formation.STATUT_TERMINEE}
        for _ in range(2):
            self.client.patch(reverse("api_formation_detail", args=[formation_id]), data=json.dumps(payload), content_type="application/json")
        payload["statut"] = Formation.STATUT_ANNULEE
        self.client.patch(reverse("api_formation_detail", args=[formation_id]), data=json.dumps(payload), content_type="application/json")

        self.assertEqual(Qualification.objects.filter(cle_unique="psc1").count(), 1)
        self.assertEqual(self.bruno.qualifications.filter(cle_unique="psc1").count(), 1)

    def test_suppression_formation_conserve_qualification_obtenue(self):
        formation_id = self._creer_a_cloturer()
        self._cloturer(formation_id)
        self.client.delete(reverse("api_formation_detail", args=[formation_id]))

        self.assertTrue(self.bruno.qualifications.filter(pk=self.bafa.id).exists())

    def test_documents_peuvent_etre_rattaches_modifies_et_sont_conserves(self):
        document_1 = Document.objects.create(titre="Convocation", fichier=SimpleUploadedFile("convocation.pdf", b"pdf"), publie=True)
        document_2 = Document.objects.create(titre="Programme", fichier=SimpleUploadedFile("programme.pdf", b"pdf"), publie=False)
        formation_id = self._post({**self.payload, "document_ids": [document_1.id, document_2.id]}).json()["id"]
        formation = Formation.objects.get(pk=formation_id)
        self.assertEqual(set(formation.documents.values_list("id", flat=True)), {document_1.id, document_2.id})

        response = self.client.patch(
            reverse("api_formation_detail", args=[formation_id]),
            data=json.dumps({**self.payload, "document_ids": [document_2.id]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(formation.documents.values_list("id", flat=True)), [document_2.id])
        self.client.delete(reverse("api_formation_detail", args=[formation_id]))
        self.assertEqual(Document.objects.filter(id__in=[document_1.id, document_2.id]).count(), 2)

    def test_page_et_api_sont_accessibles_a_la_direction(self):
        page = self.client.get(reverse("formations"))
        api = self.client.get(reverse("api_formations"))

        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "+ Ajouter une formation")
        self.assertContains(page, 'id="formation-form"')
        self.assertContains(page, 'href="/formations/"')
        self.assertNotContains(page, 'id="app-type-accueil"')
        self.assertEqual(api.status_code, 200)


class FormationAccessTests(TestCase):
    def test_animateur_simple_ne_peut_pas_acceder_aux_formations(self):
        user = get_user_model().objects.create_user(username="animateur", password="secret")
        Animateur.objects.create(prenom="Anne", nom="Test", utilisateur=user)
        self.client.force_login(user)

        page = self.client.get(reverse("formations"))
        api = self.client.get(reverse("api_formations"))

        self.assertRedirects(page, reverse("accueil"))
        self.assertEqual(api.status_code, 403)

    def test_menu_animateur_ne_contient_pas_formations(self):
        user = get_user_model().objects.create_user(username="animateur-menu", password="secret")
        Animateur.objects.create(prenom="Anne", nom="Menu", utilisateur=user)
        self.client.force_login(user)

        response = self.client.get(reverse("accueil"))

        self.assertNotContains(response, 'href="/formations/"')


class FormationDisponibilitePlanningTests(ConnexionTestCase):
    def setUp(self):
        self.animateur = Animateur.objects.create(prenom="Bruno", nom="Vaujour")
        self.disponibilite = Disponibilite.objects.create(
            animateur=self.animateur,
            debut=datetime.date(2026, 8, 24),
            fin=datetime.date(2026, 8, 28),
        )
        self.centre = Centre.objects.create(nom="Centre test", code="CT", couleur="#123456")
        self.groupe, _ = creer_groupe(
            self.centre,
            nom="Groupe test",
            debut=datetime.date(2026, 8, 24),
            effectif_cible=1,
        )

    def _formation(self, statut=Formation.STATUT_PREVUE, debut=None, fin=None):
        formation = Formation.objects.create(
            intitule="BAFA approfondissement",
            date_debut=debut or datetime.date(2026, 8, 24),
            date_fin=fin or datetime.date(2026, 8, 26),
            statut=statut,
        )
        formation.animateurs.add(self.animateur)
        return formation

    def test_disponibilite_effective_sans_formation(self):
        resultat = disponibilite_effective(self.animateur, datetime.date(2026, 8, 25))
        self.assertTrue(resultat.disponible)

    def test_prevue_et_en_cours_bloquent_uniquement_les_dates_de_formation(self):
        formation = self._formation()
        self.assertFalse(disponibilite_effective(self.animateur, datetime.date(2026, 8, 24)).disponible)
        self.assertFalse(disponibilite_effective(self.animateur, datetime.date(2026, 8, 26)).disponible)
        self.assertTrue(disponibilite_effective(self.animateur, datetime.date(2026, 8, 27)).disponible)
        formation.statut = Formation.STATUT_EN_COURS
        formation.save(update_fields=["statut"])
        self.assertFalse(disponibilite_effective(self.animateur, datetime.date(2026, 8, 25)).disponible)

    def test_annulation_et_suppression_restaurent_sans_modifier_la_declaration(self):
        formation = self._formation()
        formation.statut = Formation.STATUT_ANNULEE
        formation.save(update_fields=["statut"])
        self.assertTrue(disponibilite_effective(self.animateur, datetime.date(2026, 8, 25)).disponible)
        formation.statut = Formation.STATUT_PREVUE
        formation.save(update_fields=["statut"])
        formation.delete()
        self.assertTrue(disponibilite_effective(self.animateur, datetime.date(2026, 8, 25)).disponible)
        self.disponibilite.refresh_from_db()
        self.assertEqual((self.disponibilite.debut, self.disponibilite.fin), (datetime.date(2026, 8, 24), datetime.date(2026, 8, 28)))

    def test_affectation_manuelle_est_bloquee_avec_le_motif_formation(self):
        self._formation()
        debut = timezone.make_aware(datetime.datetime(2026, 8, 25))
        with self.assertRaisesMessage(ValueError, "Bruno Vaujour est en formation « BAFA approfondissement » le 25/08/2026"):
            creer_affectation(
                animateur=self.animateur,
                centre=self.centre,
                evenement=self.groupe,
                debut=debut,
                fin=debut + datetime.timedelta(days=1),
            )

        response = self.client.post(
            reverse("api_affectation_create"),
            data=json.dumps({
                "animateur_id": self.animateur.id,
                "centre_id": self.centre.id,
                "evenement_id": self.groupe.id,
                "debut": "2026-08-25",
                "fin": "2026-08-26",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("formation « BAFA approfondissement »", response.json()["error"])

    def test_derogation_manuelle_explicite_cree_l_affectation_et_conserve_le_conflit(self):
        self._formation()
        response = self.client.post(
            reverse("api_affectation_create"),
            data=json.dumps({
                "animateur_id": self.animateur.id,
                "centre_id": self.centre.id,
                "evenement_id": self.groupe.id,
                "debut": "2026-08-25",
                "fin": "2026-08-26",
                "forcer_formation": True,
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(Affectation.objects.exists())
        self.assertEqual(response.json()["extendedProps"]["conflits_formation"][0]["intitule"], "BAFA approfondissement")

    def test_planning_signale_une_affectation_existante_en_formation(self):
        self._formation()
        debut = timezone.make_aware(datetime.datetime(2026, 8, 25))
        Affectation.objects.create(
            animateur=self.animateur,
            centre=self.centre,
            evenement=self.groupe,
            debut=debut,
            fin=debut + datetime.timedelta(days=1),
        )

        response = self.client.get(reverse("api_planning"), {"start": "2026-08-24", "end": "2026-08-29"})

        self.assertEqual(response.status_code, 200)
        event = response.json()[0]
        self.assertIn("⚠ FORMATION", event["title"])
        self.assertEqual(event["extendedProps"]["conflits_formation"][0]["motif"], "Formation — BAFA approfondissement")

    def test_signalement_planning_utilise_une_classe_de_motif_et_conserve_le_detail(self):
        script = Path(settings.BASE_DIR, "static/js/planning.js").read_text(encoding="utf-8")
        styles = Path(settings.BASE_DIR, "static/css/planning.css").read_text(encoding="utf-8")

        self.assertIn("planning-conflict-reason", script)
        self.assertIn("planning-conflict-reason--formation", script)
        self.assertIn("planning-conflict-reason-label", styles)
        self.assertIn("⚠ En formation : ${item.intitule}", script)

    def test_api_planning_expose_le_motif_pour_ne_pas_proposer_l_animateur(self):
        self._formation()
        response = self.client.get(reverse("api_animateurs"), {
            "format": "planning",
            "debut": "2026-08-24",
            "fin": "2026-08-29",
        })

        self.assertEqual(response.status_code, 200)
        animateur = next(item for item in response.json() if item["id"] == self.animateur.id)
        self.assertEqual(animateur["formations_indisponibles"][0]["motif"], "Formation — BAFA approfondissement")

    def test_remplissage_automatique_exclut_l_animateur_en_formation(self):
        self._formation()
        resultat, statut = generer_planning_auto({"debut": "2026-08-24"})

        self.assertEqual(statut, 200)
        self.assertEqual(resultat["created"], 2)
        dates = set(Affectation.objects.values_list("debut__date", flat=True))
        self.assertNotIn(datetime.date(2026, 8, 24), dates)
        self.assertNotIn(datetime.date(2026, 8, 25), dates)
        self.assertNotIn(datetime.date(2026, 8, 26), dates)
        self.assertIn(datetime.date(2026, 8, 27), dates)
        self.assertIn(datetime.date(2026, 8, 28), dates)

    def test_creation_sur_affectation_existante_signale_le_conflit_sans_suppression(self):
        debut = timezone.make_aware(datetime.datetime(2026, 8, 25))
        affectation = Affectation.objects.create(
            animateur=self.animateur,
            centre=self.centre,
            evenement=self.groupe,
            debut=debut,
            fin=debut + datetime.timedelta(days=1),
        )
        response = self.client.post(
            reverse("api_formations"),
            data=json.dumps({
                "intitule": "BAFA approfondissement",
                "animateur_ids": [self.animateur.id],
                "date_debut": "2026-08-24",
                "date_fin": "2026-08-26",
                "statut": Formation.STATUT_PREVUE,
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["conflits"][0]["date"], "2026-08-25")
        self.assertEqual(
            response.json()["conflits"][0]["planning_url"],
            "/planning/?mode=affectations&date=2026-08-25",
        )
        self.assertTrue(Affectation.objects.filter(pk=affectation.id).exists())

    def test_conflits_de_deux_semaines_ont_chacun_leur_lien_planning(self):
        for jour in (datetime.date(2026, 8, 25), datetime.date(2026, 9, 1)):
            debut = timezone.make_aware(datetime.datetime.combine(jour, datetime.time.min))
            Affectation.objects.create(
                animateur=self.animateur,
                centre=self.centre,
                evenement=self.groupe,
                debut=debut,
                fin=debut + datetime.timedelta(days=1),
            )

        response = self.client.post(
            reverse("api_formations"),
            data=json.dumps({
                "intitule": "Formation sur deux semaines",
                "animateur_ids": [self.animateur.id],
                "date_debut": "2026-08-24",
                "date_fin": "2026-09-01",
                "statut": Formation.STATUT_PREVUE,
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        liens = {item["date"]: item["planning_url"] for item in response.json()["conflits"]}
        self.assertEqual(liens["2026-08-25"], "/planning/?mode=affectations&date=2026-08-25")
        self.assertEqual(liens["2026-09-01"], "/planning/?mode=affectations&date=2026-09-01")
        self.assertNotEqual(liens["2026-08-25"], liens["2026-09-01"])

    def test_liste_formations_rend_les_conflits_comme_liens(self):
        script = Path(settings.BASE_DIR, "static/js/formations.js").read_text(encoding="utf-8")
        planning_script = Path(settings.BASE_DIR, "static/js/planning.js").read_text(encoding="utf-8")

        self.assertIn('href="${escapeHtml(conflict.planning_url)}"', script)
        self.assertIn("formation-conflict-links", script)
        self.assertIn('planningQuery.get("date")', planning_script)
        self.assertIn("WeekPicker.getPersistedDate()", planning_script)


class FormationDashboardTests(ConnexionTestCase):
    def setUp(self):
        self.animateur = Animateur.objects.create(prenom="Ambre", nom="Martin")

    def _formation(self, intitule, statut, debut, fin):
        formation = Formation.objects.create(
            intitule=intitule,
            statut=statut,
            date_debut=debut,
            date_fin=fin,
        )
        formation.animateurs.add(self.animateur)
        return formation

    def test_dashboard_affiche_en_cours_prochaine_et_lien_sans_ancienne_terminee(self):
        aujourd_hui = timezone.localdate()
        self._formation("En cours dashboard", Formation.STATUT_EN_COURS, aujourd_hui, aujourd_hui + datetime.timedelta(days=2))
        self._formation("Prochaine dashboard", Formation.STATUT_PREVUE, aujourd_hui + datetime.timedelta(days=5), aujourd_hui + datetime.timedelta(days=6))
        self._formation("Ancienne terminée", Formation.STATUT_TERMINEE, aujourd_hui - datetime.timedelta(days=20), aujourd_hui - datetime.timedelta(days=15))

        api = self.client.get(reverse("api_tableau_de_bord"), {"semaine": aujourd_hui.isoformat()})
        page = self.client.get(reverse("accueil"))

        titres = [item["intitule"] for item in api.json()["formations"]["elements"]]
        self.assertIn("En cours dashboard", titres)
        self.assertIn("Prochaine dashboard", titres)
        self.assertNotIn("Ancienne terminée", titres)
        self.assertContains(page, "Voir les formations")

    def test_dashboard_signale_un_conflit(self):
        aujourd_hui = timezone.localdate()
        formation = self._formation("Formation conflit", Formation.STATUT_EN_COURS, aujourd_hui, aujourd_hui)
        centre = Centre.objects.create(nom="Centre dashboard", code="CD", couleur="#123456")
        groupe, _ = creer_groupe(centre, nom="Dashboard", debut=aujourd_hui)
        debut = timezone.make_aware(datetime.datetime.combine(aujourd_hui, datetime.time.min))
        Affectation.objects.create(animateur=self.animateur, centre=centre, evenement=groupe, debut=debut, fin=debut + datetime.timedelta(days=1))

        response = self.client.get(reverse("api_tableau_de_bord"), {"semaine": aujourd_hui.isoformat()})

        self.assertEqual(response.json()["formations"]["conflits"], 1)

    def test_dashboard_met_une_formation_a_cloturer_en_priorite(self):
        aujourd_hui = timezone.localdate()
        self._formation(
            "À clôturer dashboard",
            Formation.STATUT_PREVUE,
            aujourd_hui - datetime.timedelta(days=3),
            aujourd_hui - datetime.timedelta(days=1),
        )

        response = self.client.get(reverse("api_tableau_de_bord"), {"semaine": aujourd_hui.isoformat()})

        formations = response.json()["formations"]
        self.assertEqual(formations["a_cloturer"], 1)
        self.assertEqual(formations["elements"][0]["statut"], Formation.STATUT_A_CLOTURER)
