import datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from animateurs.models import (
    ActiviteTravailComplementaire,
    Affectation,
    Animateur,
    Centre,
    Disponibilite,
    Document,
    EffectifEnfantsJour,
    Evenement,
    HoraireAffectationJour,
    ParticipationTravailComplementaire,
    PublicationPlanning,
    Sortie,
    SortieParticipation,
)


class TableauDeBordAnimateurTests(TestCase):
    def setUp(self):
        self.lundi = datetime.date(2026, 8, 24)
        self.user = get_user_model().objects.create_user(
            username="marine",
            first_name="Marine",
            last_name="Lefevre",
            password="secret-test",
        )
        self.animateur = Animateur.objects.create(
            prenom="Marine",
            nom="Lefevre",
            email="marine@example.com",
            telephone="06 11 22 33 44",
            utilisateur=self.user,
        )
        self.collegue = Animateur.objects.create(prenom="Ambre", nom="Equipe")
        self.collegue.telephone = "06 55 66 77 88"
        self.collegue.email = "ambre@example.com"
        self.collegue.save(update_fields=["telephone", "email"])
        self.centre = Centre.objects.create(
            nom="Saint-Martin-d'Estréaux",
            code="SM",
            couleur="#2368e8",
        )
        self.groupe = Evenement.objects.create(
            centre=self.centre,
            nom="Groupe 3/5 ans",
            permanent=True,
            jours_ouverts=[0, 1, 2, 3, 4],
            ferme_jours_feries=False,
        )
        debut = timezone.make_aware(datetime.datetime.combine(self.lundi, datetime.time.min))
        fin = debut + datetime.timedelta(days=1)
        self.affectation = Affectation.objects.create(
            animateur=self.animateur,
            centre=self.centre,
            evenement=self.groupe,
            debut=debut,
            fin=fin,
        )
        PublicationPlanning.objects.create(semaine_debut=self.lundi, publie=True)
        Affectation.objects.create(
            animateur=self.collegue,
            centre=self.centre,
            evenement=self.groupe,
            debut=debut,
            fin=fin,
        )
        HoraireAffectationJour.objects.create(
            affectation=self.affectation,
            date=self.lundi,
            heure_arrivee=datetime.time(8, 0),
            heure_depart=datetime.time(17, 30),
        )
        EffectifEnfantsJour.objects.create(
            evenement=self.groupe,
            date=self.lundi,
            nombre=19,
        )
        Disponibilite.objects.create(
            animateur=self.animateur,
            debut=self.lundi,
            fin=self.lundi + datetime.timedelta(days=4),
        )
        sortie = Sortie.objects.create(
            nom="Piscine",
            date=self.lundi,
            destination="Piscine de Roanne",
            heure_depart_site=datetime.time(9, 0),
            heure_arrivee_retour=datetime.time(17, 0),
        )
        SortieParticipation.objects.create(sortie=sortie, evenement=self.groupe)
        reunion = ActiviteTravailComplementaire.objects.create(
            type=ActiviteTravailComplementaire.TYPE_REUNION,
            intitule="Réunion d'équipe",
            date=self.lundi,
            remarque="À 18h",
        )
        ParticipationTravailComplementaire.objects.create(
            activite=reunion,
            animateur=self.animateur,
        )
        Document.objects.create(
            titre="Livret animateur",
            fichier=SimpleUploadedFile("livret.pdf", b"pdf", content_type="application/pdf"),
            permanent=True,
            publie=True,
        )
        self.client.force_login(self.user)

    @patch("animateurs.services.animateur_dashboard.timezone.localdate")
    def test_accueil_affiche_le_tableau_de_bord_hebdomadaire_reel(self, localdate):
        localdate.return_value = self.lundi

        response = self.client.get(reverse("accueil"), {"semaine": self.lundi.isoformat()})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tableau de bord")
        self.assertContains(response, "Mon planning")
        self.assertNotContains(response, "Bonjour Marine")
        self.assertContains(response, 'id="home-calendars"')
        self.assertContains(response, 'data-calendar-date="2026-08-24"')
        self.assertContains(response, "Sorties de la semaine")
        self.assertContains(response, "Piscine de Roanne")
        self.assertContains(response, "Réunion d&#x27;équipe")
        self.assertContains(response, "Livret animateur")
        self.assertContains(response, "Tableau de bord")
        self.assertContains(response, 'class="app-rail"')
        self.assertNotContains(response, 'class="animator-sidebar"')

    def test_plannings_expose_programmes_collegues_et_sorties_du_contexte(self):
        autre_centre = Centre.objects.create(nom="Centre annexe", code="CA")
        autre_groupe = Evenement.objects.create(
            centre=autre_centre,
            nom="Groupe annexe",
            permanent=True,
            jours_ouverts=[0, 1, 2, 3, 4],
            ferme_jours_feries=False,
        )
        Affectation.objects.create(
            animateur=self.animateur,
            centre=autre_centre,
            evenement=autre_groupe,
            debut=timezone.make_aware(datetime.datetime.combine(self.lundi + datetime.timedelta(days=1), datetime.time.min)),
            fin=timezone.make_aware(datetime.datetime.combine(self.lundi + datetime.timedelta(days=2), datetime.time.min)),
        )
        Document.objects.create(
            titre="Programme annexe",
            fichier="documents/programme-annexe.jpg",
            type_document=Document.TYPE_PROGRAMME_ACTIVITES,
            permanent=False,
            periode_debut=self.lundi,
            periode_fin=self.lundi + datetime.timedelta(days=4),
            publie=True,
            tous_centres=False,
        ).centres.set([autre_centre])
        programme_tous = Document.objects.create(
            titre="Programme commun",
            fichier="documents/programme-commun.jpg",
            type_document=Document.TYPE_PROGRAMME_ACTIVITES,
            permanent=False,
            periode_debut=self.lundi,
            periode_fin=self.lundi + datetime.timedelta(days=4),
            publie=True,
        )
        programme_centre = Document.objects.create(
            titre="Programme centre",
            fichier="documents/programme-centre.jpg",
            type_document=Document.TYPE_PROGRAMME_ACTIVITES,
            permanent=False,
            periode_debut=self.lundi,
            periode_fin=self.lundi + datetime.timedelta(days=4),
            publie=True,
            tous_centres=False,
        )
        programme_centre.centres.set([self.centre])
        Document.objects.create(
            titre="Programme brouillon",
            fichier="documents/programme-brouillon.jpg",
            type_document=Document.TYPE_PROGRAMME_ACTIVITES,
            permanent=False,
            periode_debut=self.lundi,
            periode_fin=self.lundi + datetime.timedelta(days=4),
            publie=False,
        )
        Affectation.objects.create(
            animateur=self.collegue,
            centre=self.centre,
            evenement=self.groupe,
            debut=timezone.make_aware(datetime.datetime.combine(self.lundi, datetime.time.min)),
            fin=timezone.make_aware(datetime.datetime.combine(self.lundi + datetime.timedelta(days=1), datetime.time.min)),
        )

        response = self.client.get(reverse("plannings_animateur"), {"semaine": self.lundi.isoformat()})
        programmes = response.context["programmes_activites"]
        self.assertEqual({item["titre"] for item in programmes}, {"Programme annexe", "Programme commun", "Programme centre"})
        self.assertEqual(len(programmes), 3)

        collegues = response.context["jours"][0]["collegues_details"]
        self.assertEqual(
            collegues,
            [{
                "id": self.collegue.id,
                "prenom": "Ambre",
                "nom": "Equipe",
                "telephone": "06 55 66 77 88",
                "email": "ambre@example.com",
            }],
        )
        sortie = response.context["jours"][0]["sorties"][0]
        self.assertEqual(sortie["url"], reverse("sorties_animateur") + "?semaine=2026-08-24")

    def test_programme_d_un_autre_centre_et_sortie_d_une_autre_semaine_sont_exclus(self):
        autre_centre = Centre.objects.create(nom="Autre centre", code="AC")
        autre_programme = Document.objects.create(
            titre="Programme autre centre",
            fichier="documents/programme-autre.jpg",
            type_document=Document.TYPE_PROGRAMME_ACTIVITES,
            permanent=False,
            periode_debut=self.lundi,
            periode_fin=self.lundi + datetime.timedelta(days=4),
            publie=True,
            tous_centres=False,
        )
        autre_programme.centres.set([autre_centre])
        sortie = Sortie.objects.create(nom="Sortie suivante", date=self.lundi + datetime.timedelta(days=7))
        SortieParticipation.objects.create(sortie=sortie, evenement=self.groupe)

        response = self.client.get(reverse("plannings_animateur"), {"semaine": self.lundi.isoformat()})
        self.assertEqual(response.context["programmes_activites"], [])
        self.assertEqual([item["nom"] for item in response.context["sorties"]], ["Piscine"])

    @patch("animateurs.services.animateur_dashboard.timezone.localdate")
    def test_navigation_change_la_semaine_affichee(self, localdate):
        localdate.return_value = self.lundi
        semaine_suivante = self.lundi + datetime.timedelta(days=7)

        response = self.client.get(reverse("accueil"), {"semaine": semaine_suivante.isoformat()})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Semaine du 31 août au 4 septembre 2026")
        self.assertContains(response, "Le planning de cette semaine n’est pas encore publié")
        self.assertContains(response, "Cette semaine")

    def test_la_direction_conserve_sa_navigation_compacte(self):
        direction = get_user_model().objects.create_superuser(
            username="direction",
            email="direction@example.com",
            password="secret-test",
        )
        self.client.force_login(direction)

        response = self.client.get(reverse("accueil"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="app-rail"')
        self.assertNotContains(response, 'class="animator-sidebar"')
