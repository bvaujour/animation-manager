from django.test import SimpleTestCase
from django.urls import Resolver404, resolve, reverse


class RoutesNettoyeesTests(SimpleTestCase):
    def test_routes_groupes_canoniques(self):
        self.assertEqual(reverse("api_groupes", args=[1]), "/api/centres/1/groupes/")
        self.assertEqual(reverse("api_groupes_reordonner", args=[1]), "/api/centres/1/groupes/reordonner/")
        self.assertEqual(reverse("api_groupe_detail", args=[2]), "/api/groupes/2/")

    def test_anciennes_routes_ne_sont_plus_exposees(self):
        for url in (
            "/evenement/",
            "/equipe/",
            "/groupes-accueil/",
            "/api/centres/1/evenements/",
            "/api/centres/1/groupes-accueil/",
            "/api/evenements/1/",
            "/api/groupes-accueil/1/",
        ):
            with self.assertRaises(Resolver404, msg=url):
                resolve(url)
