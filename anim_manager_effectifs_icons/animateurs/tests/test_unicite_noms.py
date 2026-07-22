import json

from animateurs.models import Animateur, Centre, Qualification
from animateurs.tests.base import ConnexionTestCase


class UniciteNomsTests(ConnexionTestCase):
    def test_employe_doublon_ignore_casse_accents_et_espaces(self):
        Animateur.objects.create(prenom='Élodie', nom='  Martin ')
        r=self.client.post('/api/animateurs/', data=json.dumps({'prenom':'elodie','nom':'MARTIN'}), content_type='application/json')
        self.assertEqual(r.status_code,409)

    def test_lieu_doublon_ignore_casse_accents_et_espaces(self):
        Centre.objects.create(nom='La Pacaudière', code='PAC')
        r=self.client.post('/api/centres/', data=json.dumps({'nom':' la pacaudiere ','code':'LP2'}), content_type='application/json')
        self.assertEqual(r.status_code,409)

    def test_qualification_doublon_ignore_casse_accents_et_espaces(self):
        Qualification.objects.create(nom='BAFA')
        r=self.client.post('/api/qualifications/', data=json.dumps({'nom':' bafa '}), content_type='application/json')
        self.assertEqual(r.status_code,409)

    def test_groupes_meme_nom_interdits_dans_meme_lieu(self):
        c=Centre.objects.create(nom='Saint Forgeux',code='SF')
        payload={'nom':'Maternelles','permanent':True,'effectif_cible':1,'jours_ouverts':[0]}
        self.assertEqual(self.client.post(f'/api/centres/{c.pk}/groupes/',data=json.dumps(payload),content_type='application/json').status_code,201)
        payload['nom']=' maternelles '
        self.assertEqual(self.client.post(f'/api/centres/{c.pk}/groupes/',data=json.dumps(payload),content_type='application/json').status_code,409)
