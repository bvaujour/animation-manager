from django import forms

from .models import PeriodeScolaire, TypeAccueil


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
