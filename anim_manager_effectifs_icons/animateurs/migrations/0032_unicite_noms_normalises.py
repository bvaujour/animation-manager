import re
import unicodedata
from django.db import migrations, models


def normaliser(*valeurs):
    texte = " ".join(str(v or "").strip() for v in valeurs)
    texte = unicodedata.normalize("NFKD", texte)
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    texte = texte.casefold()
    texte = re.sub(r"[^a-z0-9]+", " ", texte)
    return " ".join(texte.split())


def remplir_cles(apps, schema_editor):
    configs = [
        (apps.get_model('animateurs','Qualification'), lambda o: normaliser(o.nom)),
        (apps.get_model('animateurs','Animateur'), lambda o: normaliser(o.prenom, o.nom)),
        (apps.get_model('animateurs','Centre'), lambda o: normaliser(o.nom)),
    ]
    for Model, calc in configs:
        vus = set()
        for obj in Model.objects.order_by('pk'):
            cle = calc(obj) or f'objet-{obj.pk}'
            if cle in vus:
                cle = f'{cle} doublon {obj.pk}'
            vus.add(cle)
            obj.cle_unique = cle
            obj.save(update_fields=['cle_unique'])
    Groupe = apps.get_model('animateurs','Evenement')
    vus = set()
    for obj in Groupe.objects.order_by('centre_id','pk'):
        cle = normaliser(obj.nom) or f'groupe-{obj.pk}'
        paire=(obj.centre_id,cle)
        if paire in vus:
            cle=f'{cle} doublon {obj.pk}'
        vus.add((obj.centre_id,cle))
        obj.cle_unique=cle
        obj.save(update_fields=['cle_unique'])


class Migration(migrations.Migration):
    dependencies=[('animateurs','0031_qualification_equivalences')]
    operations=[
        migrations.AddField(model_name='qualification',name='cle_unique',field=models.CharField(blank=True,editable=False,max_length=120,null=True)),
        migrations.AddField(model_name='animateur',name='cle_unique',field=models.CharField(blank=True,editable=False,max_length=240,null=True)),
        migrations.AddField(model_name='centre',name='cle_unique',field=models.CharField(blank=True,editable=False,max_length=120,null=True)),
        migrations.AddField(model_name='evenement',name='cle_unique',field=models.CharField(blank=True,default='',editable=False,max_length=120)),
        migrations.RunPython(remplir_cles,migrations.RunPython.noop),
        migrations.AlterField(model_name='qualification',name='cle_unique',field=models.CharField(editable=False,max_length=120,unique=True)),
        migrations.AlterField(model_name='animateur',name='cle_unique',field=models.CharField(editable=False,max_length=240,unique=True)),
        migrations.AlterField(model_name='centre',name='cle_unique',field=models.CharField(editable=False,max_length=120,unique=True)),
        migrations.RemoveConstraint(model_name='evenement',name='unique_evenement_lieu_periode'),
        migrations.AddConstraint(model_name='evenement',constraint=models.UniqueConstraint(fields=('centre','cle_unique'),name='unique_groupe_nom_normalise_par_lieu')),
    ]
