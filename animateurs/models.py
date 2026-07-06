from django.db import models

# Create your models here.

class Qualification(models.Model):

	nom = models.CharField(max_length=100)

	def __str__(self):
		return self.nom

class Animateur(models.Model):
	prenom = models.CharField(max_length=100)
	nom = models.CharField(max_length=100)
	qualifications = models.ManyToManyField(Qualification, blank=True)

	def __str__(self):
		return f"{self.prenom} {self.nom}"


class Centre(models.Model):
	nom = models.CharField(max_length=100)
	code = models.CharField(
		max_length=10,
		unique=True,
		help_text="Abréviation courte affichée dans les badges, ex: PAC",
	)
	couleur = models.CharField(
		max_length=7,
		default="#e03c00",
		help_text="Couleur hexadécimale utilisée pour les badges, ex: #e03c00",
	)

	class Meta:
		ordering = ["nom"]

	def __str__(self):
		return self.nom


class PreferenceCentre(models.Model):
	animateur = models.ForeignKey(
		Animateur,
		on_delete=models.CASCADE,
		related_name="preferences",
	)
	centre = models.ForeignKey(
		Centre,
		on_delete=models.CASCADE,
		related_name="preferences",
	)
	ordre = models.PositiveSmallIntegerField(
		help_text="1 = centre préféré",
	)

	class Meta:
		ordering = ["ordre"]
		constraints = [
			models.UniqueConstraint(
				fields=["animateur", "centre"],
				name="unique_animateur_centre",
			),
			models.UniqueConstraint(
				fields=["animateur", "ordre"],
				name="unique_animateur_ordre",
			),
		]

	def __str__(self):
		return f"{self.animateur} - {self.ordre}. {self.centre}"


class Disponibilite(models.Model):
	animateur = models.ForeignKey(
		Animateur,
		on_delete=models.CASCADE,
		related_name="disponibilites",
	)
	debut = models.DateField(help_text="Premier jour de disponibilité")
	fin = models.DateField(help_text="Dernier jour de disponibilité (inclus)")

	class Meta:
		ordering = ["debut"]
		constraints = [
			models.CheckConstraint(
				condition=models.Q(fin__gte=models.F("debut")),
				name="dispo_fin_apres_debut",
			),
		]

	def __str__(self):
		return f"{self.animateur} disponible du {self.debut:%d/%m/%Y} au {self.fin:%d/%m/%Y}"


class Affectation(models.Model):
	animateur = models.ForeignKey(
		Animateur,
		on_delete=models.CASCADE,
		related_name="affectations",
	)
	centre = models.ForeignKey(
		Centre,
		on_delete=models.CASCADE,
		related_name="affectations",
	)
	debut = models.DateTimeField()
	fin = models.DateTimeField()

	class Meta:
		ordering = ["debut"]

	def __str__(self):
		return f"{self.animateur} @ {self.centre} ({self.debut:%d/%m/%Y})"


class Document(models.Model):
	titre = models.CharField(max_length=150)
	fichier = models.FileField(upload_to="documents/")
	date_ajout = models.DateTimeField(auto_now_add=True)

	def __str__(self):
		return self.titre
