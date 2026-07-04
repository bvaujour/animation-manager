from django.db import models

# Create your models here.

class Animateur(models.Model):
    prenom = models.CharField(max_length=100)
    nom = models.CharField(max_length=100)


    def __str__(self):
        return f"{self.prenom} {self.nom}"

class Document(models.Model):
    titre = models.CharField(max_length=150)
    fichier = models.FileField(upload_to="documents/")
    date_ajout = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.titre