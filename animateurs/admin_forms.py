from django import forms

from .models import AnneeScolaire, PeriodeScolaire, TypeAccueil


class AnneeScolaireAdminForm(forms.ModelForm):
    class Meta:
        model = AnneeScolaire
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "statut" in self.fields:
            self.fields["statut"].choices = [
                choix for choix in AnneeScolaire.Statut.choices
                if choix[0] != AnneeScolaire.Statut.CLOTUREE
            ]

    def clean_statut(self):
        statut = self.cleaned_data["statut"]
        if statut == AnneeScolaire.Statut.CLOTUREE:
            raise forms.ValidationError("Utilise le bouton Clôturer l’année.")
        return statut


class ClassificationPeriodesForm(forms.Form):
    periode_ids = forms.ModelMultipleChoiceField(
        label="Périodes à classer",
        queryset=PeriodeScolaire.objects.none(),
        widget=forms.CheckboxSelectMultiple,
    )
    type_accueil = forms.ModelChoiceField(
        label="Type d'accueil",
        queryset=TypeAccueil.objects.none(),
        empty_label="Sélectionner un type",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["periode_ids"].queryset = PeriodeScolaire.objects.filter(
            type_accueil__isnull=True
        ).order_by("-debut", "nom")
        self.fields["type_accueil"].queryset = TypeAccueil.objects.filter(
            actif=True,
            code__in=(
                TypeAccueil.VACANCES,
                TypeAccueil.MERCREDIS,
                TypeAccueil.PERISCOLAIRE,
                TypeAccueil.SEJOURS,
            ),
        ).order_by("ordre", "nom")
