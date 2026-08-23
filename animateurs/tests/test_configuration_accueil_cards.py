import datetime

from django.test import TestCase

from animateurs.models import (
    AccueilCentre,
    BesoinEncadrement,
    BesoinQualification,
    Centre,
    Groupe,
    ModalitePeriscolaire,
    OuvertureCentrePeriode,
    PeriodeCalendrier,
    PeriodeScolaire,
    Qualification,
    TypeAccueil,
)
from animateurs.services.evenements import creer_evenement
from animateurs.services.parametres import get_parametres_structure
from animateurs.services.serializers import centre_to_dict


class ConfigurationAccueilCardsTests(TestCase):
    def setUp(self):
        self.vacances, _ = TypeAccueil.objects.get_or_create(
            code=TypeAccueil.VACANCES,
            defaults={"nom": "Vacances", "ordre": 10, "actif": True},
        )
        self.periscolaire, _ = TypeAccueil.objects.get_or_create(
            code=TypeAccueil.PERISCOLAIRE,
            defaults={"nom": "Périscolaire", "ordre": 20, "actif": True},
        )
        self.centre = Centre.objects.create(
            nom="Saint-Forgeux-Lespinasse", code="SF", commune="Saint-Forgeux-Lespinasse",
            code_postal="42640", couleur="#6f8f79",
        )
        self.centre.types_accueil.add(self.vacances, self.periscolaire)
        self.accueil_vacances = AccueilCentre.objects.create(
            centre=self.centre, type_accueil=self.vacances,
            date_debut=datetime.date(2026, 7, 1),
        )
        self.accueil_periscolaire = AccueilCentre.objects.create(
            centre=self.centre, type_accueil=self.periscolaire,
            date_debut=datetime.date(2026, 8, 22), pedt_applicable=True,
        )

    def _groupe(self, nom, categorie, accueil, *, jours=(0, 1, 2, 3, 4), ratio_legacy=99):
        partage = Groupe.objects.create(
            nom=nom,
            categorie_age_reglementaire=categorie,
            enfants_par_animateur_defaut=ratio_legacy,
        )
        partage.types_accueil.add(accueil.type_accueil)
        return creer_evenement(
            centre=self.centre,
            accueil_centre=accueil,
            nom=nom,
            groupe_partage=partage,
            jours_ouverts=list(jours),
            enfants_par_animateur_defaut=ratio_legacy,
        )

    def _payload_accueil(self, accueil):
        return next(item for item in centre_to_dict(self.centre)["accueils"] if item["id"] == accueil.id)

    def test_carte_vacances_separe_periodes_jours_et_taux_contextuel(self):
        groupe = self._groupe("Maternelle", Groupe.AGE_MOINS_6, self.accueil_vacances)
        for numero, debut in ((1, datetime.date(2026, 10, 19)), (2, datetime.date(2026, 10, 26))):
            periode = PeriodeScolaire.objects.create(
                nom=f"Toussaint — Semaine {numero}", annee_scolaire="2026-2027", zone="A",
                debut=debut, fin=debut + datetime.timedelta(days=4), type_accueil=self.vacances,
            )
            periode.types_accueil.add(self.vacances)
            groupe.periodes_scolaires.add(periode)
        BesoinEncadrement.objects.create(
            evenement=groupe, type_accueil=self.vacances,
            mode_calcul=BesoinEncadrement.MODE_REGLEMENTAIRE,
            effectif_enfants_reference=18,
        )
        parametres = get_parametres_structure()
        parametres.ratio_vacances_moins_6 = 7
        parametres.save(update_fields=["ratio_vacances_moins_6"])

        payload = self._payload_accueil(self.accueil_vacances)

        self.assertEqual(payload["periodes_ouvertes"], [{"nom": "Toussaint 2026", "semaines": ["S1", "S2"]}])
        self.assertEqual(payload["jours_ouverts"], [0, 1, 2, 3, 4])
        self.assertEqual(payload["encadrement_groupes"][0]["resume"], "Calcul réglementaire · Taux appliqué : 1 / 7 · Effectif de référence : 18 enfants")
        self.assertNotIn("99", payload["encadrement_groupes"][0]["resume"])

    def test_carte_manuelle_affiche_postes_reference_et_qualification_contextuelle_seulement(self):
        groupe = self._groupe("Élémentaire", Groupe.AGE_6_PLUS, self.accueil_vacances)
        regle = BesoinEncadrement.objects.create(
            evenement=groupe, type_accueil=self.vacances,
            mode_calcul=BesoinEncadrement.MODE_MANUEL,
            effectif_cible=3, effectif_enfants_reference=24,
        )
        historique = Qualification.objects.create(nom="Historique carte")
        bafa = Qualification.objects.create(nom="BAFA carte")
        BesoinQualification.objects.create(
            evenement=groupe, qualification=historique, nombre_minimum=4,
        )
        BesoinQualification.objects.create(
            evenement=groupe, qualification=bafa, nombre_minimum=1,
            type_accueil=self.vacances,
            modalite_periscolaire=regle.modalite_periscolaire,
            periode_calendrier=regle.periode_calendrier,
        )

        ligne = self._payload_accueil(self.accueil_vacances)["encadrement_groupes"][0]

        self.assertEqual(ligne["resume"], "3 postes requis · Effectif de référence : 24 enfants")
        self.assertEqual(ligne["exigences"], ["1 × BAFA carte"])
        self.assertNotIn("Historique", " ".join(ligne["exigences"]))

    def test_periscolaire_utilise_ouvertures_pedt_et_detaille_les_taux_differents(self):
        groupe = self._groupe("Maternelle", Groupe.AGE_MOINS_6, self.accueil_periscolaire, jours=(6,))
        matin = ModalitePeriscolaire.objects.create(code="matin_carte", nom="Accueil du matin")
        mercredi = ModalitePeriscolaire.objects.create(code="mercredi_carte", nom="Mercredi journée entière")
        periode = PeriodeCalendrier.objects.create(
            categorie=PeriodeCalendrier.SCOLAIRE, nom="Rentrée", annee_scolaire="2026-2027",
            zone="A", debut=datetime.date(2026, 9, 1), fin=datetime.date(2026, 10, 16),
        )
        for modalite, debut, fin in (
            (matin, datetime.time(7, 30), datetime.time(9, 0)),
            (mercredi, datetime.time(8, 0), datetime.time(18, 0)),
        ):
            OuvertureCentrePeriode.objects.create(
                centre=self.centre, accueil_centre=self.accueil_periscolaire,
                periode_calendrier=periode, modalite_periscolaire=modalite,
                jour_semaine=2, heure_debut=debut, heure_fin=fin,
            )
        BesoinEncadrement.objects.create(
            evenement=groupe, type_accueil=self.periscolaire,
            mode_calcul=BesoinEncadrement.MODE_REGLEMENTAIRE,
        )
        parametres = get_parametres_structure()
        parametres.ratio_periscolaire_pedt_court_moins_6 = 14
        parametres.ratio_periscolaire_pedt_long_moins_6 = 10
        parametres.save(update_fields=[
            "ratio_periscolaire_pedt_court_moins_6",
            "ratio_periscolaire_pedt_long_moins_6",
        ])

        payload = self._payload_accueil(self.accueil_periscolaire)
        ligne = payload["encadrement_groupes"][0]

        self.assertEqual(set(payload["modalites_noms"]), {"Accueil du matin", "Mercredi journée entière"})
        self.assertEqual(payload["jours_ouverts"], [2])
        self.assertEqual(ligne["resume"], "Calcul réglementaire")
        self.assertEqual(
            {(detail["contexte"], detail["texte"]) for detail in ligne["details"]},
            {
                ("Accueil du matin", "Taux appliqué : 1 / 14"),
                ("Mercredi journée entière", "Taux appliqué : 1 / 10"),
            },
        )

    def test_reference_absente_n_est_pas_affichee(self):
        groupe = self._groupe("Sans référence", Groupe.AGE_6_PLUS, self.accueil_vacances)
        BesoinEncadrement.objects.create(
            evenement=groupe, type_accueil=self.vacances,
            mode_calcul=BesoinEncadrement.MODE_MANUEL, effectif_cible=2,
        )

        resume = self._payload_accueil(self.accueil_vacances)["encadrement_groupes"][0]["resume"]

        self.assertEqual(resume, "2 postes requis")
        self.assertNotIn("référence", resume.lower())
