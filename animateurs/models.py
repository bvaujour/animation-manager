from django.db import models

# Create your models here.

class Animateur(models.Model):
    prenom = models.CharField(max_length=100)
    nom = models.CharField(max_length=100)


    def __str__(self):
        return f"{self.prenom} {self.nom}"