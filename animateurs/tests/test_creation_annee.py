from datetime import date, datetime, time, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from animateurs.forms_creation_annee import NouvelleAnneeForm, RepriseAnneeForm
from animateurs.models import (
    AccueilCentre, Affectation, Animateur, AnneeScolaire, BesoinEncadrement,
    BesoinQualification, Centre, Contrat, Evenement, Groupe, ModalitePeriscolaire,
    OuvertureCentrePeriode, PeriodeCalendrier, PeriodeScolaire, Qualification, TypeAccueil,
)
from animateurs.services.creation_annee import accueils_reutilisables, creer_annee, preparer_copie
from animateurs.tests.base import ConnexionTestCase
from animateurs.services.calendrier_scolaire import CalendrierScolaireError, SemaineVacances


class CreationAnneeTests(ConnexionTestCase):
    def setUp(self):
        # Seule la récupération réseau est simulée : le calcul du calendrier
        # et le parcours de prévisualisation/confirmation restent réels.
        semaines = [
            SemaineVacances(f"{nom} — Semaine {numero + 1}", debut + timedelta(days=7 * numero),
                debut + timedelta(days=7 * numero + 4), nom, numero + 1)
            for nom, debut in (("Toussaint", date(2026, 10, 19)), ("Noël", date(2026, 12, 21)),
                               ("Hiver", date(2027, 2, 15)), ("Printemps", date(2027, 4, 12)))
            for numero in range(2)
        ]
        semaines.append(SemaineVacances("Été — début officiel", date(2027, 7, 3), date(2027, 7, 3), "Début des Vacances d'Été", 0))
        patcher = patch("animateurs.services.creation_annee.recuperer_semaines", return_value=semaines)
        self.recuperer_semaines = patcher.start()
        self.addCleanup(patcher.stop)
        self.source = AnneeScolaire.objects.get(libelle="2025-2026")
        self.type, _ = TypeAccueil.objects.get_or_create(code="periscolaire", defaults={"nom": "Périscolaire"})
        self.modalite, _ = ModalitePeriscolaire.objects.get_or_create(code="matin", defaults={"nom": "Matin"})
        self.centre = Centre.objects.create(nom="Lieu partagé", code="LPA")
        self.accueil = AccueilCentre.objects.create(centre=self.centre, type_accueil=self.type)
        self.groupe = Groupe.objects.create(nom="Groupe partagé")
        self.evenement = Evenement.objects.create(centre=self.centre, accueil_centre=self.accueil, groupe=self.groupe, nom="Groupe partagé")
        self.periode = PeriodeCalendrier.objects.create(categorie="scolaire", nom="Automne", zone="A", annee_scolaire="2025-2026", debut=date(2025, 9, 1), fin=date(2025, 10, 17))
        self.periode.types_accueil.add(self.type)
        self.horaire = OuvertureCentrePeriode.objects.create(centre=self.centre, accueil_centre=self.accueil, periode_calendrier=self.periode, modalite_periscolaire=self.modalite, jour_semaine=0, heure_debut=time(7), heure_fin=time(8))
        self.besoin = BesoinEncadrement.objects.create(evenement=self.evenement, type_accueil=self.type, periode_calendrier=self.periode, effectif_cible=2)
        self.qualification = Qualification.objects.create(nom="Diplôme partagé")
        BesoinQualification.objects.create(evenement=self.evenement, qualification=self.qualification, type_accueil=self.type, periode_calendrier=self.periode, nombre_minimum=1)
        self.url = reverse("admin:animateurs_anneescolaire_nouvelle")

    def cible(self):
        return AnneeScolaire(libelle="2026-2027", date_debut=date(2026, 9, 1), date_fin=date(2027, 8, 31))

    def plan(self, categories=("horaires", "besoins", "qualifications"), centres=None, accueils=None):
        return preparer_copie(self.cible(), self.source, centres if centres is not None else [self.centre.pk],
            accueils if accueils is not None else [self.accueil.pk], categories,
            {self.periode.pk: (date(2026, 9, 1), date(2026, 10, 16))})

    def identite(self, mode="copie"):
        return {"libelle": "2026-2027", "date_debut": "2026-09-01", "date_fin": "2027-08-31", "source": self.source.pk, "mode": mode, "action": "continuer"}

    def options(self, jeton):
        return {"action": "previsualiser", "jeton": jeton, "centres": [self.centre.pk], "accueils": [self.accueil.pk], "categories": ["horaires"],
                f"periode_{self.periode.pk}_debut": "2026-09-01", f"periode_{self.periode.pk}_fin": "2026-10-16"}

    @staticmethod
    def selectionner_calendrier(options, formulaire, *, ete=False):
        for periode in formulaire.periodes_scolaires:
            options[f"scolaire_{periode['id']}"] = "on"
        for vacance in formulaire.vacances_courtes:
            options[f"vacance_{vacance['id']}"] = "on"
        if ete:
            for semaine in formulaire.semaines_ete:
                options[f"ete_{semaine['id']}"] = "on"

    def test_annee_vierge_et_doublon(self):
        counts = (Centre.objects.count(), PeriodeCalendrier.objects.count(), OuvertureCentrePeriode.objects.count())
        cible = creer_annee(self.cible())
        self.assertEqual(cible.statut, "PREPARATION")
        self.assertEqual(counts, (Centre.objects.count(), PeriodeCalendrier.objects.count(), OuvertureCentrePeriode.objects.count()))
        with self.assertRaises(ValidationError):
            creer_annee(self.cible())

    def test_copie_structure_annuelle_sans_historique(self):
        salarie = Animateur.objects.create(prenom="Global", nom="Salarié")
        Contrat.objects.create(animateur=salarie, type_contrat="cee", date_debut=date(2025, 9, 1), date_fin=date(2026, 8, 31), taux_journalier_reference=50)
        Affectation.objects.create(animateur=salarie, centre=self.centre, evenement=self.evenement,
            debut=timezone.make_aware(datetime(2025, 9, 1)), fin=timezone.make_aware(datetime(2025, 9, 2)))
        modeles = (AnneeScolaire, Animateur, Contrat, Affectation, Centre, AccueilCentre, Groupe, Evenement, Qualification)
        avant = {m: list(m.objects.order_by("pk").values()) for m in modeles}
        cible = creer_annee(self.cible(), self.plan())
        self.assertEqual(cible.statut, "PREPARATION")
        for modele in modeles[1:]:
            self.assertEqual(list(modele.objects.order_by("pk").values()), avant[modele])
        self.assertEqual(AnneeScolaire.objects.values().get(pk=self.source.pk), avant[AnneeScolaire][0])
        periode = PeriodeCalendrier.objects.get(annee_scolaire="2026-2027")
        self.assertEqual(periode.fin, date(2026, 10, 16))
        self.assertEqual(list(periode.types_accueil.all()), [self.type])
        self.assertEqual(OuvertureCentrePeriode.objects.get(periode_calendrier=periode).centre_id, self.centre.pk)
        self.assertEqual(BesoinEncadrement.objects.get(periode_calendrier=periode).evenement_id, self.evenement.pk)
        self.assertEqual(BesoinQualification.objects.get(periode_calendrier=periode).qualification_id, self.qualification.pk)

    def test_uniquement_categories_selectionnees(self):
        creer_annee(self.cible(), self.plan(("horaires",)))
        self.assertEqual(OuvertureCentrePeriode.objects.count(), 2)
        self.assertEqual(BesoinEncadrement.objects.count(), 1)
        self.assertEqual(BesoinQualification.objects.count(), 1)

    def test_selection_centres_et_accueils_et_categorie_vide(self):
        self.assertFalse(self.plan(centres=[])["periodes"])
        self.assertFalse(self.plan(accueils=[])["periodes"])
        BesoinQualification.objects.all().delete()
        creer_annee(self.cible(), self.plan(("qualifications",)))
        self.assertEqual(PeriodeCalendrier.objects.count(), 1)

    def test_regles_generales_non_copiees(self):
        BesoinEncadrement.objects.create(evenement=self.evenement, type_accueil=self.type, effectif_cible=3)
        creer_annee(self.cible(), self.plan(("besoins",)))
        self.assertEqual(BesoinEncadrement.objects.filter(periode_calendrier__isnull=True).count(), 1)

    def test_rollback_si_erreur(self):
        with patch("animateurs.services.creation_annee.OuvertureCentrePeriode.save", side_effect=ValidationError("Erreur simulée")):
            with self.assertRaises(ValidationError):
                creer_annee(self.cible(), self.plan())
        self.assertFalse(AnneeScolaire.objects.filter(libelle="2026-2027").exists())
        self.assertEqual(PeriodeCalendrier.objects.count(), 1)
        self.assertEqual(OuvertureCentrePeriode.objects.count(), 1)

    def test_dates_cibles_hors_annee_refusees(self):
        data = self.options("")
        data[f"periode_{self.periode.pk}_fin"] = "2028-01-01"
        form = RepriseAnneeForm(data, cible=self.cible(), source=self.source)
        self.assertFalse(form.is_valid())

    def test_accueil_termine_non_reutilise(self):
        self.accueil.date_fin = date(2026, 8, 31)
        self.accueil.save()
        self.assertFalse(accueils_reutilisables(self.source, self.cible()).filter(pk=self.accueil.pk).exists())

    def test_parcours_vierge_confirmation_obligatoire_et_double_clic(self):
        self.assertContains(self.client.get(self.url), "Créer une nouvelle année scolaire")
        response = self.client.post(self.url, self.identite("vierge"))
        self.assertEqual(response.context["etape"], "preview")
        self.assertFalse(AnneeScolaire.objects.filter(libelle="2026-2027").exists())
        data = {"action": "creer", "jeton": response.context["jeton"]}
        response = self.client.post(self.url, data, follow=True)
        self.assertContains(response, "Configuration de 2026-2027")
        self.assertContains(response, "PREPARATION")
        self.client.post(self.url, data)
        self.assertEqual(AnneeScolaire.objects.filter(libelle="2026-2027").count(), 1)

    def test_parcours_copie_avec_preview(self):
        response = self.client.post(self.url, self.identite())
        self.assertEqual(response.context["etape"], "options")
        self.assertTrue(response.context["mode_multisite"])
        self.assertContains(response, "finalisation du module responsabilités")
        response = self.client.post(self.url, self.options(response.context["jeton"]))
        self.assertEqual(response.context["etape"], "preview")
        self.assertEqual(response.context["plan"]["resume"], [("Horaires d’ouverture", 1)])
        self.assertFalse(AnneeScolaire.objects.filter(libelle="2026-2027").exists())
        response = self.client.post(self.url, {"action": "creer", "jeton": response.context["jeton"]})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(AnneeScolaire.objects.get(libelle="2026-2027").statut, "PREPARATION")
        self.source.refresh_from_db()
        self.assertEqual(self.source.statut, "ACTIVE")

    def test_source_changee_apres_preview_refusee(self):
        response = self.client.post(self.url, self.identite())
        response = self.client.post(self.url, self.options(response.context["jeton"]))
        self.horaire.heure_debut = time(6)
        self.horaire.save()
        response = self.client.post(self.url, {"action": "creer", "jeton": response.context["jeton"]})
        self.assertContains(response, "configuration source a changé")
        self.assertFalse(AnneeScolaire.objects.filter(libelle="2026-2027").exists())

    def test_permissions(self):
        user = get_user_model().objects.create_user(username="lecture", is_staff=True)
        user.user_permissions.add(Permission.objects.get(codename="view_anneescolaire"))
        self.client.force_login(user)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, self.identite("vierge")).status_code, 403)
        user.user_permissions.add(Permission.objects.get(codename="add_anneescolaire"))
        response = self.client.post(self.url, self.identite())
        self.assertEqual(self.client.post(self.url, self.options(response.context["jeton"])).status_code, 403)

    def test_jeton_altere_et_saut_preview_refuses(self):
        response = self.client.post(self.url, {"action": "creer", "jeton": "invalide"})
        self.assertContains(response, "expiré ou invalide")
        response = self.client.post(self.url, self.identite())
        self.client.post(self.url, {"action": "creer", "jeton": response.context["jeton"]})
        self.assertFalse(AnneeScolaire.objects.filter(libelle="2026-2027").exists())

    def test_source_precedente_par_defaut(self):
        data = self.identite()
        data.pop("source")
        form = NouvelleAnneeForm(data)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["source"], self.source)

    def test_calendrier_visible_avec_compteurs_nuls_et_regles_globales_conservees(self):
        OuvertureCentrePeriode.objects.all().delete()
        BesoinEncadrement.objects.update(periode_calendrier=None)
        BesoinQualification.objects.update(periode_calendrier=None)
        self.periode.delete()
        regles = {m: list(m.objects.values()) for m in (BesoinEncadrement, BesoinQualification)}
        response = self.client.post(self.url, self.identite())
        data = self.options(response.context["jeton"])
        data["categories"] = ["horaires", "besoins", "qualifications"]
        response = self.client.post(self.url, data)
        self.assertEqual(response.context["etape"], "preview")
        self.assertEqual([n for _, n in response.context["plan"]["resume"]], [0, 0, 0])
        self.assertContains(response, "Périodes source utilisées pour la copie : 0")
        self.assertContains(response, "Périodes officielles cibles : 0")
        self.assertContains(response, "Horaires d’ouverture : 0 (aucun horaire annuel à reprendre)")
        self.assertFalse(AnneeScolaire.objects.filter(libelle="2026-2027").exists())
        response = self.client.post(self.url, {"action": "creer", "jeton": response.context["jeton"]})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(AnneeScolaire.objects.get(libelle="2026-2027").statut, "PREPARATION")
        self.assertEqual(PeriodeCalendrier.objects.filter(annee_scolaire="2026-2027").count(), 0)
        for modele, avant in regles.items():
            self.assertEqual(list(modele.objects.values()), avant)

    def test_zone_conservee_jusqua_confirmation_et_calendrier_existant_reutilise(self):
        identite = self.identite()
        identite["zone"] = "C"
        existante = PeriodeCalendrier.objects.create(categorie="scolaire", nom="Déjà présente", zone="C",
            annee_scolaire="2026-2027", debut=date(2026, 9, 1), fin=date(2026, 10, 16))
        semaine = PeriodeScolaire.objects.create(nom="Nom local", zone="C", annee_scolaire="2026-2027",
            debut=date(2026, 10, 19), fin=date(2026, 10, 23))
        response = self.client.post(self.url, identite)
        data = self.options(response.context["jeton"])
        data["categories"] = []
        self.selectionner_calendrier(data, response.context["options"])
        response = self.client.post(self.url, data)
        self.assertEqual(response.context["plan"]["zone"], "C")
        self.assertContains(response, "Zone C")
        self.recuperer_semaines.assert_called_with("2026-2027", "C", inclure_bornes=True)
        response = self.client.post(self.url, {"action": "creer", "jeton": response.context["jeton"]})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.recuperer_semaines.call_count, 3)
        self.recuperer_semaines.assert_called_with("2026-2027", "C", inclure_bornes=True)
        self.assertEqual(set(PeriodeCalendrier.objects.filter(annee_scolaire="2026-2027").values_list("zone", flat=True)), {"C"})
        self.assertEqual(PeriodeCalendrier.objects.filter(annee_scolaire="2026-2027").count(), 9)
        self.assertEqual(PeriodeScolaire.objects.filter(annee_scolaire="2026-2027").count(), 8)
        existante.refresh_from_db()
        semaine.refresh_from_db()
        self.assertEqual(existante.nom, "Déjà présente")
        self.assertEqual(semaine.nom, "Nom local")

    def test_erreur_calendrier_visible_et_selection_conservee(self):
        response = self.client.post(self.url, self.identite())
        data = self.options(response.context["jeton"])
        self.recuperer_semaines.side_effect = CalendrierScolaireError("Service temporairement indisponible.")
        response = self.client.post(self.url, data)
        self.assertEqual(response.context["etape"], "options")
        self.assertContains(response, "Calendrier officiel indisponible")
        self.assertEqual(response.context["options"]["categories"].value(), ["horaires"])
        self.assertNotContains(response, 'value="creer"')
        self.assertFalse(AnneeScolaire.objects.filter(libelle="2026-2027").exists())

    def test_erreur_calcul_calendrier_visible(self):
        response = self.client.post(self.url, self.identite())
        with patch("animateurs.services.creation_annee.calculer_periodes_scolaires", side_effect=ValueError("dates invalides")):
            response = self.client.post(self.url, self.options(response.context["jeton"]))
        self.assertContains(response, "Le calcul des périodes scolaires officielles a échoué.")
        self.assertEqual(response.context["etape"], "options")

    def test_erreur_calendrier_a_confirmation_ne_cree_rien(self):
        response = self.client.post(self.url, self.identite())
        response = self.client.post(self.url, self.options(response.context["jeton"]))
        self.recuperer_semaines.side_effect = CalendrierScolaireError("Service indisponible.")
        response = self.client.post(self.url, {"action": "creer", "jeton": response.context["jeton"]})
        self.assertContains(response, "Calendrier officiel indisponible")
        self.assertFalse(AnneeScolaire.objects.filter(libelle="2026-2027").exists())

    def test_rattachements_source_exacte_ajoutes_sans_suppression_ni_doublon(self):
        source = PeriodeScolaire.objects.create(nom="Source", zone="A", annee_scolaire="2025-2026",
            debut=date(2026, 2, 9), fin=date(2026, 2, 13))
        autre = PeriodeScolaire.objects.create(nom="Autre année", zone="A", annee_scolaire="2024-2025",
            debut=date(2025, 3, 3), fin=date(2025, 3, 7))
        cible_existante = PeriodeScolaire.objects.create(nom="Libellé cible différent", zone="A", annee_scolaire="2026-2027",
            debut=date(2027, 2, 9), fin=date(2027, 2, 13))
        nouvelle_source = PeriodeScolaire.objects.create(nom="Autre source", zone="A", annee_scolaire="2025-2026",
            debut=date(2026, 4, 6), fin=date(2026, 4, 10))
        self.evenement.periodes_scolaires.add(source, autre, cible_existante, nouvelle_source)
        second = Evenement.objects.create(centre=self.centre, accueil_centre=self.accueil,
            groupe=Groupe.objects.create(nom="Second groupe"), nom="Second")
        second.periodes_scolaires.add(source, nouvelle_source)
        avant = list(PeriodeScolaire.objects.order_by("pk").values())
        annee_source_avant = AnneeScolaire.objects.values().get(pk=self.source.pk)
        plan = self.plan(categories=())
        cible = creer_annee(self.cible(), plan)
        self.assertEqual(cible.statut, "PREPARATION")
        self.assertEqual(AnneeScolaire.objects.values().get(pk=self.source.pk), annee_source_avant)
        self.assertEqual(list(PeriodeScolaire.objects.filter(pk__in=[p["id"] for p in avant]).order_by("pk").values()), avant)
        self.assertEqual(set(self.evenement.periodes_scolaires.values_list("pk", flat=True)),
            {source.pk, autre.pk, cible_existante.pk, nouvelle_source.pk})
        self.assertEqual(set(second.periodes_scolaires.values_list("pk", flat=True)),
            {source.pk, nouvelle_source.pk})
        self.assertEqual(PeriodeScolaire.objects.count(), len(avant))

    def test_semaine_source_sans_equivalent_officiel_n_est_pas_decalee(self):
        self.periode.debut = date(2026, 2, 9)
        self.periode.fin = date(2026, 2, 13)
        self.periode.save()
        semaine = PeriodeScolaire.objects.create(nom="Hiver", zone="A", annee_scolaire="2025-2026",
            debut=self.periode.debut, fin=self.periode.fin)
        self.evenement.periodes_scolaires.add(semaine)
        plan = preparer_copie(self.cible(), self.source, [self.centre.pk], [self.accueil.pk], ["horaires"],
            {self.periode.pk: (date(2027, 2, 9), date(2027, 2, 13))})
        creer_annee(self.cible(), plan)
        self.assertFalse(self.evenement.periodes_scolaires.filter(annee_scolaire="2026-2027").exists())
        self.assertTrue(self.evenement.periodes_scolaires.filter(pk=semaine.pk).exists())

    def test_calendrier_modifie_apres_preview_refuse(self):
        response = self.client.post(self.url, self.identite())
        response = self.client.post(self.url, self.options(response.context["jeton"]))
        self.recuperer_semaines.return_value = self.recuperer_semaines.return_value[:-2]
        response = self.client.post(self.url, {"action": "creer", "jeton": response.context["jeton"]})
        self.assertContains(response, "La configuration source a changé")
        self.assertFalse(AnneeScolaire.objects.filter(libelle="2026-2027").exists())

    def test_vacances_et_periodes_separees_reutilisation_et_confirmation(self):
        scolaire = PeriodeCalendrier.objects.create(categorie="scolaire", nom="Rentrée locale", zone="A",
            annee_scolaire="2026-2027", debut=date(2026, 9, 1), fin=date(2026, 10, 16))
        toussaint = PeriodeCalendrier.objects.create(categorie="vacances", nom="Toussaint", zone="A",
            annee_scolaire="2026-2027", debut=date(2026, 10, 19), fin=date(2026, 10, 30))
        for semaine in self.recuperer_semaines.return_value[:2]:
            PeriodeScolaire.objects.create(nom="Semaine locale", zone="A", annee_scolaire="2026-2027",
                debut=semaine.debut, fin=semaine.fin, periode_calendrier=toussaint)
        # L'été existant mais non sélectionné n'est pas repris automatiquement.
        ete = PeriodeCalendrier.objects.create(categorie="vacances", nom="Été", zone="A",
            annee_scolaire="2026-2027", debut=date(2027, 7, 5), fin=date(2027, 8, 27))
        modeles = (AnneeScolaire, PeriodeCalendrier, PeriodeScolaire)
        avant = {m: list(m.objects.order_by("pk").values()) for m in modeles}
        response = self.client.post(self.url, self.identite())
        options = self.options(response.context["jeton"])
        options["categories"] = []
        self.selectionner_calendrier(options, response.context["options"])
        response = self.client.post(self.url, options)
        preview = response.context["calendrier_preview"]
        self.assertEqual((preview["scolaires_creees"], preview["scolaires_reutilisees"]), (4, 1))
        self.assertEqual((preview["semaines_creees"], preview["semaines_reutilisees"]), (6, 2))
        html = response.content.decode()
        scolaires_html = html.split('id="periodes-scolaires-cibles"')[1].split("</section>")[0]
        vacances_html = html.split('id="vacances-scolaires-cibles"')[1].split("</section>")[0]
        self.assertIn("Rentrée → Toussaint", scolaires_html)
        self.assertNotIn("Rentrée → Toussaint", vacances_html)
        for nom in ("Toussaint", "Noël", "Hiver", "Printemps"):
            self.assertIn(nom, vacances_html)
        self.assertNotIn("2027-08-27", vacances_html)
        self.assertIn("Réutilisée", vacances_html)
        self.assertIn("Créée (semaines)", vacances_html)
        self.assertEqual(len(preview["vacances"]), 4)
        for modele, lignes in avant.items():
            self.assertEqual(list(modele.objects.order_by("pk").values()), lignes)
        response = self.client.post(self.url, {"action": "creer", "jeton": response.context["jeton"]})
        self.assertEqual(response.status_code, 302)
        for modele, lignes in avant.items():
            self.assertEqual(list(modele.objects.filter(pk__in=[r["id"] for r in lignes]).order_by("pk").values()), lignes)
        self.assertEqual(PeriodeCalendrier.objects.count(), len(avant[PeriodeCalendrier]) + 7)
        self.assertEqual(PeriodeScolaire.objects.count(), len(avant[PeriodeScolaire]) + 6)
        self.assertEqual(AnneeScolaire.objects.get(libelle="2026-2027").statut, "PREPARATION")

    def test_vacances_partiellement_existantes_et_ete_genere(self):
        PeriodeScolaire.objects.create(nom="Nom personnalisé", zone="A", annee_scolaire="2026-2027",
            debut=date(2026, 10, 19), fin=date(2026, 10, 23))
        # Une semaine d'une autre zone ne doit pas être annoncée réutilisable.
        PeriodeScolaire.objects.create(nom="Autre zone", zone="B", annee_scolaire="2026-2027",
            debut=date(2027, 7, 5), fin=date(2027, 7, 9))
        response = self.client.post(self.url, self.identite())
        options = self.options(response.context["jeton"])
        options["categories"] = []
        self.selectionner_calendrier(options, response.context["options"])
        response = self.client.post(self.url, options)
        preview = response.context["calendrier_preview"]
        self.assertEqual((preview["semaines_creees"], preview["semaines_reutilisees"]), (7, 1))
        self.assertContains(response, "Réutilisée en partie")
        response = self.client.post(self.url, {"action": "creer", "jeton": response.context["jeton"]})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(PeriodeScolaire.objects.filter(annee_scolaire="2026-2027", zone="A").count(), 8)

    def test_vacances_locales_sans_periode_calendaire_affichees(self):
        vacances, _ = TypeAccueil.objects.get_or_create(code="vacances", defaults={"nom": "Vacances"})
        PeriodeScolaire.objects.create(nom="Été — Semaine 1", zone="A", annee_scolaire="2026-2027",
            debut=date(2027, 7, 5), fin=date(2027, 7, 9), type_accueil=vacances)
        response = self.client.post(self.url, self.identite())
        options = self.options(response.context["jeton"])
        options["ete_0"] = "on"
        response = self.client.post(self.url, options)
        ete = next(v for v in response.context["calendrier_preview"]["vacances"] if v["nom"].startswith("Été"))
        self.assertEqual((ete["creees"], ete["reutilisees"]), (0, 1))
        self.assertContains(response, "2027-07-09")

    def test_semaines_ete_recalculees_selectionnees_et_visibles_avant_confirmation(self):
        semaines_source = [
            PeriodeScolaire.objects.create(nom=f"Été — Semaine {numero}", zone="A", annee_scolaire="2025-2026",
                debut=debut, fin=debut + timedelta(days=4), description_source="Vacances d'Été", ordre=numero)
            for numero, debut in ((1, date(2026, 7, 6)), (2, date(2026, 7, 13)),
                                  (3, date(2026, 7, 20)), (4, date(2026, 7, 27)), (8, date(2026, 8, 24)))
        ]
        self.evenement.periodes_scolaires.add(*semaines_source)
        source_avant = list(PeriodeScolaire.objects.filter(annee_scolaire="2025-2026").order_by("pk").values())
        response = self.client.post(self.url, self.identite())
        self.assertContains(response, "Semaines d’ouverture estivale à reprendre")
        self.assertContains(response, "2027-07-05 au 2027-07-09")
        self.assertContains(response, "2027-08-23 au 2027-08-27")
        options = self.options(response.context["jeton"])
        for semaine in response.context["options"].semaines_ete:
            if semaine["suggeree"]:
                options[f"ete_{semaine['id']}"] = "on"
        # La troisième semaine est explicitement décochée : elle ne peut pas
        # être créée ni rattachée lors de la confirmation.
        options.pop("ete_2")
        response = self.client.post(self.url, options)
        self.assertEqual(response.context["etape"], "preview")
        preview = response.context["calendrier_preview"]
        ete = next(v for v in preview["vacances"] if v["nom"].startswith("Été"))
        self.assertEqual([(s["debut"], s["fin"]) for s in ete["semaines"]], [
            ("2027-07-05", "2027-07-09"), ("2027-07-12", "2027-07-16"),
            ("2027-07-26", "2027-07-30"), ("2027-08-23", "2027-08-27"),
        ])
        self.assertTrue(all(date.fromisoformat(s["debut"]).weekday() == 0
                            and date.fromisoformat(s["fin"]) - date.fromisoformat(s["debut"]) == timedelta(days=4)
                            for s in ete["semaines"]))
        self.assertNotContains(response, "2027-07-19 au 2027-07-23")
        visibles = {(s["debut"], s["fin"]) for s in ete["semaines"]}
        response = self.client.post(self.url, {"action": "creer", "jeton": response.context["jeton"]})
        self.assertEqual(response.status_code, 302)
        creees = PeriodeScolaire.objects.filter(annee_scolaire="2026-2027", description_source="Vacances d'Été")
        self.assertEqual(set(creees.values_list("debut", "fin")),
                         {(date.fromisoformat(d), date.fromisoformat(f)) for d, f in visibles})
        self.assertFalse(creees.filter(debut=date(2027, 7, 19)).exists())
        self.assertTrue(all(s.debut.weekday() == 0 and s.fin == s.debut + timedelta(days=4) for s in creees))
        self.assertEqual(list(PeriodeScolaire.objects.filter(annee_scolaire="2025-2026").order_by("pk").values()), source_avant)
        self.assertEqual(self.evenement.periodes_scolaires.filter(annee_scolaire="2026-2027", description_source="Vacances d'Été").count(), 4)
        # La confirmation rejouée n'ajoute aucun doublon grâce aux mêmes clés de dates.
        self.assertEqual(creees.count(), 4)

    def test_toutes_les_semaines_ete_sont_proposees_et_les_suggestions_seules_sont_cochees(self):
        semaines_source = [
            PeriodeScolaire.objects.create(nom=f"Été — Semaine {numero}", zone="A", annee_scolaire="2025-2026",
                debut=debut, fin=debut + timedelta(days=4), description_source="Vacances d'Été", ordre=numero)
            for numero, debut in ((1, date(2026, 7, 6)), (2, date(2026, 7, 13)),
                                  (3, date(2026, 7, 20)), (4, date(2026, 7, 27)), (8, date(2026, 8, 24)))
        ]
        self.evenement.periodes_scolaires.add(*semaines_source)
        response = self.client.post(self.url, self.identite())
        ete = response.context["options"].semaines_ete
        self.assertEqual([(semaine["debut"], semaine["fin"]) for semaine in ete], [
            (date(2027, 7, 5), date(2027, 7, 9)), (date(2027, 7, 12), date(2027, 7, 16)),
            (date(2027, 7, 19), date(2027, 7, 23)), (date(2027, 7, 26), date(2027, 7, 30)),
            (date(2027, 8, 2), date(2027, 8, 6)), (date(2027, 8, 9), date(2027, 8, 13)),
            (date(2027, 8, 16), date(2027, 8, 20)), (date(2027, 8, 23), date(2027, 8, 27)),
        ])
        self.assertEqual([semaine["id"] for semaine in ete if semaine["suggeree"]], ["0", "1", "2", "3", "7"])
        self.assertEqual([semaine["id"] for semaine in ete if not semaine["suggeree"]], ["4", "5", "6"])
        html = response.content.decode()
        self.assertIn('name="ete_4"', html)
        self.assertNotIn('name="ete_4" id="id_ete_4" checked', html)

    def test_semaine_ete_supplementaire_cochee_est_la_seule_ajoutee(self):
        semaine_source = PeriodeScolaire.objects.create(nom="Été — Semaine 1", zone="A", annee_scolaire="2025-2026",
            debut=date(2026, 7, 6), fin=date(2026, 7, 10), description_source="Vacances d'Été", ordre=1)
        self.evenement.periodes_scolaires.add(semaine_source)
        response = self.client.post(self.url, self.identite())
        options = self.options(response.context["jeton"])
        # La première suggestion reste cochée ; l'utilisateur ajoute la
        # semaine 5, initialement décochée, sans ouvrir les autres semaines.
        options["ete_0"] = "on"
        options["ete_4"] = "on"
        response = self.client.post(self.url, options)
        preview = response.context["calendrier_preview"]
        ete = next(v for v in preview["vacances"] if v["nom"].startswith("Été"))
        self.assertEqual([(s["debut"], s["fin"]) for s in ete["semaines"]], [
            ("2027-07-05", "2027-07-09"), ("2027-08-02", "2027-08-06"),
        ])
        response = self.client.post(self.url, {"action": "creer", "jeton": response.context["jeton"]})
        self.assertEqual(response.status_code, 302)
        creees = PeriodeScolaire.objects.filter(annee_scolaire="2026-2027", description_source="Vacances d'Été")
        self.assertEqual(set(creees.values_list("debut", "fin")), {
            (date(2027, 7, 5), date(2027, 7, 9)), (date(2027, 8, 2), date(2027, 8, 6)),
        })
        self.assertEqual(self.evenement.periodes_scolaires.filter(annee_scolaire="2026-2027").count(), 1)

    def test_periodes_et_vacances_sont_suggerees_mais_selectionnees_explicitement(self):
        rentree = PeriodeCalendrier.objects.create(categorie="scolaire", nom="Rentrée → Toussaint", zone="A",
            annee_scolaire="2025-2026", debut=date(2025, 9, 8), fin=date(2025, 10, 10))
        OuvertureCentrePeriode.objects.create(centre=self.centre, accueil_centre=self.accueil,
            periode_calendrier=rentree, modalite_periscolaire=self.modalite, jour_semaine=0,
            heure_debut=time(7), heure_fin=time(8))
        toussaint = PeriodeCalendrier.objects.create(categorie="vacances", nom="Toussaint", zone="A",
            annee_scolaire="2025-2026", debut=date(2025, 11, 3), fin=date(2025, 11, 14))
        semaines_source = [
            PeriodeScolaire.objects.create(nom=f"Toussaint — Semaine {numero}", zone="A", annee_scolaire="2025-2026",
                debut=debut, fin=debut + timedelta(days=4), description_source="Vacances de la Toussaint",
                ordre=numero, periode_calendrier=toussaint)
            for numero, debut in ((1, date(2025, 11, 3)), (2, date(2025, 11, 10)))
        ]
        self.evenement.periodes_scolaires.add(*semaines_source)
        source_avant = {modele: list(modele.objects.filter(annee_scolaire="2025-2026").order_by("pk").values())
                        for modele in (PeriodeCalendrier, PeriodeScolaire)}

        response = self.client.post(self.url, self.identite())
        form = response.context["options"]
        self.assertEqual([p["suggeree"] for p in form.periodes_scolaires], [True, False, False, False, False])
        self.assertEqual([v["suggeree"] for v in form.vacances_courtes], [True, False, False, False])
        html = response.content.decode()
        self.assertIn('name="scolaire_0"', html)
        self.assertIn('name="vacance_1"', html)
        self.assertNotIn('name="vacance_1" id="id_vacance_1" checked', html)

        options = self.options(response.context["jeton"])
        options["categories"] = []
        options["scolaire_0"] = "on"
        options["vacance_0"] = "on"
        options["vacance_1"] = "on"  # Noël est volontairement ajouté malgré son absence source.
        response = self.client.post(self.url, options)
        self.assertEqual(response.context["etape"], "preview")
        preview = response.context["calendrier_preview"]
        self.assertEqual([p["nom"] for p in preview["scolaires"]], ["Rentrée → Toussaint"])
        self.assertEqual([v["nom"] for v in preview["vacances"]], ["Toussaint", "Noël"])
        self.assertNotContains(response, "Hiver — Semaine 1")
        self.assertNotContains(response, "Printemps — Semaine 1")

        response = self.client.post(self.url, {"action": "creer", "jeton": response.context["jeton"]})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(PeriodeCalendrier.objects.filter(annee_scolaire="2026-2027", categorie="scolaire").count(), 1)
        self.assertEqual(PeriodeCalendrier.objects.filter(annee_scolaire="2026-2027", categorie="vacances").count(), 2)
        self.assertEqual(set(PeriodeScolaire.objects.filter(annee_scolaire="2026-2027").values_list("nom", flat=True)), {
            "Toussaint — Semaine 1", "Toussaint — Semaine 2", "Noël — Semaine 1", "Noël — Semaine 2"})
        self.assertFalse(PeriodeScolaire.objects.filter(annee_scolaire="2026-2027", nom__startswith="Hiver").exists())
        self.assertFalse(PeriodeScolaire.objects.filter(annee_scolaire="2026-2027", nom__startswith="Printemps").exists())
        for modele, avant in source_avant.items():
            self.assertEqual(list(modele.objects.filter(annee_scolaire="2025-2026").order_by("pk").values()), avant)
