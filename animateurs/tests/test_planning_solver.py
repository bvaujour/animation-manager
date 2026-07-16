import datetime

from django.test import TestCase
from django.utils import timezone

from animateurs.models import (
    Affectation,
    Animateur,
    Centre,
    Disponibilite,
    PreferenceCentre,
    Qualification,
)
from animateurs.services.planning_solver import generer_planning_auto


class PlanningSolverTests(TestCase):
    def setUp(self):
        self.centre = Centre.objects.create(
            nom="Centre test", code="CT", couleur="#123456", effectif_cible=1
        )
        self.bafa = Qualification.objects.create(nom="BAFA")
        self.qualifie = Animateur.objects.create(prenom="Qualifié", nom="Test")
        self.qualifie.qualifications.add(self.bafa)
        self.non_qualifie = Animateur.objects.create(prenom="Sans", nom="Qualification")
        PreferenceCentre.objects.create(animateur=self.qualifie, centre=self.centre)
        PreferenceCentre.objects.create(animateur=self.non_qualifie, centre=self.centre)
        for animateur in (self.qualifie, self.non_qualifie):
            Disponibilite.objects.create(
                animateur=animateur,
                debut=datetime.date(2026, 7, 6),
                fin=datetime.date(2026, 7, 10),
            )

    def test_respecte_qualification_demandee(self):
        payload = {
            "debut": "2026-07-06",
            "centres": {
                str(self.centre.id): {
                    "effectif": 1,
                    "qualifs": {str(self.bafa.id): 1},
                }
            },
        }
        data, status = generer_planning_auto(payload)
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["created"], 5)
        self.assertFalse(
            Affectation.objects.exclude(animateur=self.qualifie).exists()
        )
        self.assertTrue(
            all(affectation.debut.date().weekday() < 5 for affectation in Affectation.objects.all())
        )

    def test_respecte_les_disponibilites(self):
        # Le qualifié n'est disponible que le lundi. Le reste doit rester vide
        # puisqu'une qualification BAFA est demandée chaque jour.
        self.qualifie.disponibilites.all().delete()
        Disponibilite.objects.create(
            animateur=self.qualifie,
            debut=datetime.date(2026, 7, 6),
            fin=datetime.date(2026, 7, 6),
        )
        payload = {
            "debut": "2026-07-06",
            "centres": {
                str(self.centre.id): {
                    "effectif": 1,
                    "qualifs": {str(self.bafa.id): 1},
                }
            },
        }
        data, status = generer_planning_auto(payload)
        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 1)
        affectation = Affectation.objects.get()
        self.assertEqual(affectation.debut.date(), datetime.date(2026, 7, 6))

    def test_exclut_les_animateurs_sans_disponibilite(self):
        self.qualifie.disponibilites.all().delete()
        self.non_qualifie.disponibilites.all().delete()
        payload = {
            "debut": "2026-07-06",
            "centres": {
                str(self.centre.id): {
                    "effectif": 1,
                    "qualifs": {},
                }
            },
        }

        data, status = generer_planning_auto(payload)

        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 0)
        self.assertEqual(data["unfilled"], 5)
        self.assertFalse(Affectation.objects.exists())

    def test_ne_touche_pas_au_samedi_manuel(self):
        samedi = datetime.date(2026, 7, 11)
        affectation_samedi = Affectation.objects.create(
            animateur=self.non_qualifie,
            centre=self.centre,
            debut=timezone.make_aware(datetime.datetime.combine(samedi, datetime.time.min)),
            fin=timezone.make_aware(datetime.datetime.combine(samedi + datetime.timedelta(days=1), datetime.time.min)),
        )

        payload = {
            "debut": "2026-07-06",
            "centres": {
                str(self.centre.id): {
                    "effectif": 1,
                    "qualifs": {},
                }
            },
        }

        data, status = generer_planning_auto(payload)

        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 5)
        self.assertTrue(Affectation.objects.filter(pk=affectation_samedi.pk).exists())
        self.assertEqual(
            Affectation.objects.filter(debut__date=samedi).count(),
            1,
        )
        self.assertFalse(
            Affectation.objects.filter(debut__date__week_day=1).exists(),
            "Le solveur ne doit jamais créer d'affectation le dimanche.",
        )

    def test_respecte_strictement_les_centres_autorises(self):
        autre_centre = Centre.objects.create(
            nom="Centre interdit", code="CI", couleur="#654321", effectif_cible=1
        )
        payload = {
            "debut": "2026-07-06",
            "centres": {
                str(self.centre.id): {
                    "effectif": 0,
                    "qualifs": {},
                },
                str(autre_centre.id): {
                    "effectif": 1,
                    "qualifs": {},
                },
            },
        }

        data, status = generer_planning_auto(payload)

        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 0)
        self.assertEqual(data["unfilled"], 5)
        self.assertFalse(Affectation.objects.filter(centre=autre_centre).exists())

    def test_conserve_la_meme_evenement_sur_la_semaine(self):
        # Deux animateurs sont autorisés et disponibles pour un poste quotidien.
        # Le solveur doit conserver la même personne toute la semaine plutôt
        # que d'alterner entre les deux.
        payload = {
            "debut": "2026-07-06",
            "centres": {
                str(self.centre.id): {
                    "effectif": 1,
                    "qualifs": {},
                }
            },
        }

        data, status = generer_planning_auto(payload)

        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 5)
        self.assertEqual(data["animateurs_utilises"], 1)
        self.assertEqual(
            Affectation.objects.values_list("animateur_id", flat=True).distinct().count(),
            1,
        )


    def test_priorise_le_centre_prefere(self):
        autre = Centre.objects.create(
            nom="Autre centre", code="AUT", couleur="#abcdef", effectif_cible=1
        )
        # Le qualifié peut travailler dans les deux centres, mais son centre
        # préféré est `self.centre`.
        relation = PreferenceCentre.objects.get(
            animateur=self.qualifie, centre=self.centre
        )
        relation.est_prefere = True
        relation.save(update_fields=["est_prefere"])
        PreferenceCentre.objects.create(
            animateur=self.qualifie, centre=autre, est_prefere=False
        )

        # Un second animateur est uniquement affectable au centre principal.
        autre_anim = Animateur.objects.create(prenom="Autre", nom="Animateur")
        PreferenceCentre.objects.create(
            animateur=autre_anim, centre=self.centre, est_prefere=False
        )
        Disponibilite.objects.create(
            animateur=autre_anim,
            debut=datetime.date(2026, 7, 6),
            fin=datetime.date(2026, 7, 10),
        )

        payload = {
            "debut": "2026-07-06",
            "centres": {
                str(self.centre.id): {"effectif": 1, "qualifs": {}},
                str(autre.id): {"effectif": 0, "qualifs": {}},
            },
        }

        data, status = generer_planning_auto(payload)

        self.assertEqual(status, 200)
        self.assertEqual(data["created"], 5)
        self.assertFalse(
            Affectation.objects.filter(centre=self.centre)
            .exclude(animateur=self.qualifie)
            .exists()
        )
