import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from animateurs.models import (
    AccueilCentre, Affectation, Animateur, BesoinEncadrement, Centre, Disponibilite,
    FonctionOperationnelle, HoraireAffectationJour, Qualification,
    ResponsabiliteOperationnelle, TypeAccueil,
)
from animateurs.services.affectations import creer_affectation, modifier_affectation
from animateurs.services.planning_solver import generer_planning_auto
from animateurs.services.responsabilites import (
    affectation_active_responsabilite, membres_encadrement_uniques, membres_quotas_uniques,
)
from animateurs.services.serializers import affectation_to_event
from animateurs.services.statuts import categorie_encadrement_du_statut, statut_pour_date
from animateurs.services.temps_travail import intervalles_travail_pour_animateur
from animateurs.tests.factories import creer_groupe


LUNDI = datetime.date(2026, 7, 6)


class ResponsabilitesOperationnellesTests(TestCase):
    def setUp(self):
        self.centre = Centre.objects.create(nom="Site", code="SF", couleur="#aaccee", effectif_cible=1)
        self.groupe, _ = creer_groupe(self.centre, nom="Maternelle", effectif_cible=1)
        self.julie = Animateur.objects.create(prenom="Julie", nom="Martin")
        self.betty = Animateur.objects.create(prenom="Betty", nom="Test")
        for animateur in (self.julie, self.betty):
            Disponibilite.objects.create(
                animateur=animateur, debut=LUNDI, fin=LUNDI + datetime.timedelta(days=4)
            )
        self.debut = timezone.make_aware(datetime.datetime.combine(LUNDI, datetime.time(8)))
        self.fin = timezone.make_aware(datetime.datetime.combine(LUNDI, datetime.time(18)))
        self.adjointe = FonctionOperationnelle.objects.get(code=FonctionOperationnelle.DIRECTEUR_ADJOINT)
        self.directrice = FonctionOperationnelle.objects.get(code=FonctionOperationnelle.DIRECTEUR)

    def test_api_drag_drop_ordinaire_reste_inchangee(self):
        user = get_user_model().objects.create_superuser(username="direction", password="secret")
        self.client.force_login(user)
        response = self.client.post(
            reverse("api_affectation_create"),
            data={
                "animateur_id": self.julie.id, "centre_id": self.centre.id,
                "evenement_id": self.groupe.id, "debut": LUNDI.isoformat(),
                "fin": (LUNDI + datetime.timedelta(days=1)).isoformat(),
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Affectation.objects.get().evenement, self.groupe)
        self.assertEqual(ResponsabiliteOperationnelle.objects.count(), 0)

    def test_responsabilite_liee_affiche_badge_sans_deuxieme_affectation(self):
        affectation = creer_affectation(
            animateur=self.julie, centre=self.centre, evenement=self.groupe,
            debut=timezone.make_aware(datetime.datetime.combine(LUNDI, datetime.time.min)),
            fin=timezone.make_aware(datetime.datetime.combine(LUNDI + datetime.timedelta(days=1), datetime.time.min)),
        )
        responsabilite = ResponsabiliteOperationnelle.objects.create(
            animateur=self.julie, fonction=self.adjointe, debut=affectation.debut, fin=affectation.fin,
            perimetre="groupe", evenement=self.groupe, affectation_source_id=affectation.id,
            fournit_temps_travail=False, bloque_affectation_animation=False,
        )
        affectation._responsabilites_planning = [responsabilite]
        payload = affectation_to_event(affectation)
        self.assertEqual(payload["extendedProps"]["responsabilite"]["fonction_code"], "directeur_adjoint")
        self.assertEqual(Affectation.objects.count(), 1)

    def test_responsabilite_standalone_existe_sans_groupe_et_compte_dix_heures(self):
        responsabilite = ResponsabiliteOperationnelle.objects.create(
            animateur=self.betty, fonction=self.directrice, debut=self.debut, fin=self.fin,
            perimetre="site", centre=self.centre, bloque_affectation_animation=True,
        )
        self.assertIsNone(responsabilite.evenement_id)
        intervalles = intervalles_travail_pour_animateur(self.betty, self.debut, self.fin)
        self.assertEqual(sum((fin - debut for debut, fin in intervalles), datetime.timedelta()), datetime.timedelta(hours=10))

    def test_affectation_et_responsabilite_superposees_ne_doublent_pas_le_temps(self):
        affectation = creer_affectation(
            animateur=self.julie, centre=self.centre, evenement=self.groupe,
            debut=timezone.make_aware(datetime.datetime.combine(LUNDI, datetime.time.min)),
            fin=timezone.make_aware(datetime.datetime.combine(LUNDI + datetime.timedelta(days=1), datetime.time.min)),
        )
        HoraireAffectationJour.objects.create(
            affectation=affectation, date=LUNDI, heure_arrivee=datetime.time(8), heure_depart=datetime.time(18)
        )
        ResponsabiliteOperationnelle.objects.create(
            animateur=self.julie, fonction=self.directrice, debut=self.debut, fin=self.fin,
            perimetre="site", centre=self.centre, bloque_affectation_animation=False,
        )
        intervalles = intervalles_travail_pour_animateur(self.julie, self.debut, self.fin)
        self.assertEqual(len(intervalles), 1)
        self.assertEqual(intervalles[0][1] - intervalles[0][0], datetime.timedelta(hours=10))

    def test_suppression_responsabilite_ne_touche_pas_affectation(self):
        affectation = creer_affectation(
            animateur=self.julie, centre=self.centre, evenement=self.groupe,
            debut=timezone.make_aware(datetime.datetime.combine(LUNDI, datetime.time.min)),
            fin=timezone.make_aware(datetime.datetime.combine(LUNDI + datetime.timedelta(days=1), datetime.time.min)),
        )
        item = ResponsabiliteOperationnelle.objects.create(
            animateur=self.julie, fonction=self.adjointe, debut=affectation.debut, fin=affectation.fin,
            perimetre="groupe", evenement=self.groupe, affectation_source_id=affectation.id,
            fournit_temps_travail=False, bloque_affectation_animation=False,
        )
        item.delete()
        self.assertTrue(Affectation.objects.filter(pk=affectation.id).exists())

    def test_deplacement_et_redimensionnement_actualisent_le_contexte_lie(self):
        autre_groupe, _ = creer_groupe(self.centre, nom="Elementaire", effectif_cible=1)
        affectation = creer_affectation(
            animateur=self.julie, centre=self.centre, evenement=self.groupe,
            debut=timezone.make_aware(datetime.datetime.combine(LUNDI, datetime.time.min)),
            fin=timezone.make_aware(datetime.datetime.combine(LUNDI + datetime.timedelta(days=1), datetime.time.min)),
        )
        item = ResponsabiliteOperationnelle.objects.create(
            animateur=self.julie, fonction=self.adjointe, debut=affectation.debut, fin=affectation.fin,
            perimetre="groupe", evenement=self.groupe, affectation_source_id=affectation.id,
            fournit_temps_travail=False, bloque_affectation_animation=False,
        )
        nouvelle_fin = affectation.fin + datetime.timedelta(days=1)

        modifier_affectation(affectation, evenement=autre_groupe, fin=nouvelle_fin)

        item.refresh_from_db()
        self.assertEqual(item.evenement, autre_groupe)
        self.assertEqual(item.fin, nouvelle_fin)
        self.assertEqual(affectation_active_responsabilite(item).id, affectation.id)

    def test_suppression_affectation_rend_la_responsabilite_liee_inactive(self):
        affectation = creer_affectation(
            animateur=self.julie, centre=self.centre, evenement=self.groupe,
            debut=timezone.make_aware(datetime.datetime.combine(LUNDI, datetime.time.min)),
            fin=timezone.make_aware(datetime.datetime.combine(LUNDI + datetime.timedelta(days=1), datetime.time.min)),
        )
        item = ResponsabiliteOperationnelle.objects.create(
            animateur=self.julie, fonction=self.adjointe, debut=affectation.debut, fin=affectation.fin,
            perimetre="groupe", evenement=self.groupe, affectation_source_id=affectation.id,
            fournit_temps_travail=False, bloque_affectation_animation=False,
        )
        affectation.delete()

        self.assertIsNone(affectation_active_responsabilite(item))
        self.assertFalse(item.fournit_temps_travail)

    def test_encadrement_et_quotas_sont_explicites_et_dedoublonnes(self):
        diplome = Qualification.objects.create(nom="Diplômé", est_statut=True)
        self.betty.qualifications.add(diplome)
        compte = ResponsabiliteOperationnelle.objects.create(
            animateur=self.betty, fonction=self.directrice, debut=self.debut, fin=self.fin,
            perimetre="site", centre=self.centre, bloque_affectation_animation=False,
            compte_dans_encadrement=True, compte_dans_quotas_qualification=True,
        )
        ignoree = ResponsabiliteOperationnelle.objects.create(
            animateur=self.julie, fonction=self.adjointe, debut=self.debut, fin=self.fin,
            perimetre="site", centre=self.centre, bloque_affectation_animation=False,
            compte_dans_encadrement=False, compte_dans_quotas_qualification=False,
        )
        self.assertEqual([item.id for item in membres_encadrement_uniques([], [compte, ignoree])], [self.betty.id])
        self.assertEqual([item.id for item in membres_encadrement_uniques([self.betty], [compte])], [self.betty.id])
        quotas = membres_quotas_uniques([], [compte, ignoree])
        self.assertEqual([item.id for item in quotas], [self.betty.id])
        self.assertEqual(categorie_encadrement_du_statut(statut_pour_date(self.betty, LUNDI)), "diplome")


class ResponsabilitesSolveurTests(TestCase):
    def setUp(self):
        self.centre = Centre.objects.create(nom="Site", code="S", couleur="#abcdef", effectif_cible=1)
        self.groupe, _ = creer_groupe(self.centre, nom="Groupe", effectif_cible=1)
        self.animateur = Animateur.objects.create(prenom="Alex", nom="Test")
        Disponibilite.objects.create(
            animateur=self.animateur, debut=LUNDI, fin=LUNDI + datetime.timedelta(days=4)
        )
        self.fonction = FonctionOperationnelle.objects.get(code=FonctionOperationnelle.DIRECTEUR)

    def lancer(self):
        return generer_planning_auto({"debut": LUNDI.isoformat()})

    def creer_responsabilite(self, bloque):
        return ResponsabiliteOperationnelle.objects.create(
            animateur=self.animateur, fonction=self.fonction,
            debut=timezone.make_aware(datetime.datetime.combine(LUNDI, datetime.time(8))),
            fin=timezone.make_aware(datetime.datetime.combine(LUNDI, datetime.time(18))),
            perimetre="site", centre=self.centre,
            bloque_affectation_animation=bloque,
        )

    def test_sans_responsabilite_le_solveur_produit_les_affectations_ordinaires(self):
        data, status = self.lancer()
        self.assertEqual((status, data["created"], Affectation.objects.count()), (200, 5, 5))

    def test_responsabilite_bloquante_exclut_uniquement_son_intervalle(self):
        self.creer_responsabilite(True)
        data, status = self.lancer()
        self.assertEqual((status, data["created"]), (200, 4))

    def test_direction_standalone_couvre_reellement_un_poste_du_site(self):
        vacances, _ = TypeAccueil.objects.get_or_create(
            code=TypeAccueil.VACANCES,
            defaults={"nom": "Vacances", "ordre": 10, "actif": True},
        )
        accueil = AccueilCentre.objects.create(centre=self.centre, type_accueil=vacances)
        self.groupe.accueil_centre = accueil
        self.groupe.jours_ouverts = [0]
        self.groupe.save(update_fields=["accueil_centre", "jours_ouverts"])
        self.groupe.types_accueil.set([vacances])
        BesoinEncadrement.objects.create(
            evenement=self.groupe, type_accueil=vacances,
            mode_calcul=BesoinEncadrement.MODE_MANUEL, effectif_cible=6,
        )
        statut_diplome = Qualification.objects.create(nom="Diplômé direction", est_statut=True)
        self.animateur.qualifications.add(statut_diplome)
        for index in range(5):
            animateur = Animateur.objects.create(prenom=f"Anim{index}", nom="Equipe")
            animateur.qualifications.add(statut_diplome)
            Disponibilite.objects.create(animateur=animateur, debut=LUNDI, fin=LUNDI)
        ResponsabiliteOperationnelle.objects.create(
            animateur=self.animateur, fonction=self.fonction,
            debut=timezone.make_aware(datetime.datetime.combine(LUNDI, datetime.time(8))),
            fin=timezone.make_aware(datetime.datetime.combine(LUNDI, datetime.time(18))),
            perimetre="site", centre=self.centre, bloque_affectation_animation=True,
            compte_dans_encadrement=True,
        )

        data, status = generer_planning_auto({
            "debut": LUNDI.isoformat(), "type_accueil": TypeAccueil.VACANCES,
        })

        self.assertEqual(status, 200)
        self.assertEqual(data["total_places"], 6)
        self.assertEqual(data["created"], 5)
        self.assertEqual(data["postes_couverts_par_responsabilites"], 1)
        self.assertEqual(data["unfilled"], 0)
        self.assertEqual(data["non_conformites_reglementaires"], 0)

    def test_responsabilite_non_bloquante_ne_change_pas_la_disponibilite(self):
        self.creer_responsabilite(False)
        data, status = self.lancer()
        self.assertEqual((status, data["created"]), (200, 5))

    def test_solveur_ne_modifie_ni_ne_supprime_responsabilite(self):
        responsabilite = self.creer_responsabilite(False)
        valeurs = {
            "fonction_id": responsabilite.fonction_id, "debut": responsabilite.debut,
            "fin": responsabilite.fin, "centre_id": responsabilite.centre_id,
        }
        self.lancer()
        responsabilite.refresh_from_db()
        self.assertEqual(ResponsabiliteOperationnelle.objects.count(), 1)
        self.assertEqual(
            {nom: getattr(responsabilite, nom) for nom in valeurs}, valeurs
        )

    def test_solveur_preserve_aussi_une_responsabilite_liee(self):
        affectation = Affectation.objects.create(
            animateur=self.animateur, centre=self.centre, evenement=self.groupe,
            debut=timezone.make_aware(datetime.datetime.combine(LUNDI, datetime.time.min)),
            fin=timezone.make_aware(datetime.datetime.combine(LUNDI + datetime.timedelta(days=1), datetime.time.min)),
        )
        responsabilite = ResponsabiliteOperationnelle.objects.create(
            animateur=self.animateur, fonction=self.fonction,
            debut=affectation.debut, fin=affectation.fin,
            perimetre="groupe", evenement=self.groupe,
            affectation_source_id=affectation.id, fournit_temps_travail=False,
            bloque_affectation_animation=False,
        )
        source_id = responsabilite.affectation_source_id
        self.lancer()
        responsabilite.refresh_from_db()
        self.assertEqual(responsabilite.affectation_source_id, source_id)
        self.assertEqual(ResponsabiliteOperationnelle.objects.count(), 1)
        active = affectation_active_responsabilite(responsabilite)
        self.assertIsNotNone(active)
        self.assertNotEqual(active.id, source_id)

    def test_responsabilite_liee_devient_inactive_si_lanimateur_nest_plus_affecte(self):
        affectation = Affectation.objects.create(
            animateur=self.animateur, centre=self.centre, evenement=self.groupe,
            debut=timezone.make_aware(datetime.datetime.combine(LUNDI, datetime.time.min)),
            fin=timezone.make_aware(datetime.datetime.combine(LUNDI + datetime.timedelta(days=1), datetime.time.min)),
        )
        responsabilite = ResponsabiliteOperationnelle.objects.create(
            animateur=self.animateur, fonction=self.fonction,
            debut=affectation.debut, fin=affectation.fin,
            perimetre="groupe", evenement=self.groupe,
            affectation_source_id=affectation.id, fournit_temps_travail=False,
            bloque_affectation_animation=False,
        )
        self.animateur.disponibilites.all().delete()
        remplacement = Animateur.objects.create(prenom="Remplacement", nom="Test")
        Disponibilite.objects.create(
            animateur=remplacement, debut=LUNDI, fin=LUNDI + datetime.timedelta(days=4)
        )

        self.lancer()
        responsabilite.refresh_from_db()

        self.assertIsNone(affectation_active_responsabilite(responsabilite))
        self.assertEqual(ResponsabiliteOperationnelle.objects.count(), 1)
