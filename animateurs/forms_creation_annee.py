from datetime import date

from django import forms
from django.core.exceptions import ValidationError

from .models import AnneeScolaire, Centre, PeriodeCalendrier
from .services.creation_annee import CATEGORIES, accueils_reutilisables, preparer_copie


class SourceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.libelle} — {obj.get_statut_display()}"


class NouvelleAnneeForm(forms.ModelForm):
    mode = forms.ChoiceField(label="Comment souhaitez-vous créer cette année scolaire ?", choices=(
        ("copie", "À partir d’une année existante"), ("vierge", "Créer une année vierge")), widget=forms.RadioSelect)
    source = SourceField(label="Année source (mode reprise uniquement)", queryset=AnneeScolaire.objects.all(), required=False)

    class Meta:
        model = AnneeScolaire
        fields = ("libelle", "date_debut", "date_fin")
        widgets = {champ: forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d") for champ in ("date_debut", "date_fin")}

    def clean(self):
        data = super().clean()
        if data.get("mode") == "copie":
            source = data.get("source")
            if not source and data.get("date_debut"):
                source = AnneeScolaire.objects.filter(date_debut__lt=data["date_debut"]).order_by("-date_debut").first()
                data["source"] = source
            if not source:
                self.add_error("source", "Sélectionnez une année source.")
            elif data.get("date_debut") and source.date_fin >= data["date_debut"]:
                self.add_error("source", "La nouvelle année doit commencer après la fin de l’année source.")
        return data


class RepriseAnneeForm(forms.Form):
    centres = forms.ModelMultipleChoiceField(label="Lieux / centres réutilisés", queryset=Centre.objects.all(), required=False, widget=forms.CheckboxSelectMultiple)
    accueils = forms.ModelMultipleChoiceField(label="Accueils réutilisés dans les centres sélectionnés", queryset=None, required=False, widget=forms.CheckboxSelectMultiple)
    categories = forms.MultipleChoiceField(label="Configurations annuelles à copier", choices=[(code, valeur[1]) for code, valeur in CATEGORIES.items()], required=False, widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, cible, source, **kwargs):
        super().__init__(*args, **kwargs)
        self.cible, self.source = cible, source
        self.fields["accueils"].queryset = accueils_reutilisables(source, cible)
        self.periodes = list(PeriodeCalendrier.objects.filter(annee_scolaire=source.libelle).order_by("debut", "pk"))
        self.champs_dates = []
        decalage = cible.date_debut.year - source.date_debut.year
        for periode in self.periodes:
            noms = []
            for borne in ("debut", "fin"):
                valeur = getattr(periode, borne)
                try:
                    proposition = valeur.replace(year=valeur.year + decalage)
                except ValueError:
                    proposition = date(valeur.year + decalage, 2, 28)
                nom = f"periode_{periode.pk}_{borne}"
                self.fields[nom] = forms.DateField(label=f"{periode.nom} · zone {periode.zone} · {borne}", initial=proposition, required=False, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
                noms.append(self[nom])
            self.champs_dates.append(noms)

    def clean(self):
        data = super().clean()
        if self.errors:
            return data
        dates = {p.pk: (data.get(f"periode_{p.pk}_debut"), data.get(f"periode_{p.pk}_fin")) for p in self.periodes}
        # Les dates ne sont obligatoires que pour les périodes effectivement reprises.
        try:
            self.plan = preparer_copie(self.cible, self.source,
                [c.pk for c in data["centres"]], [a.pk for a in data["accueils"]], data["categories"], dates)
        except TypeError:
            raise ValidationError("Renseignez les dates des périodes utilisées par les configurations sélectionnées.")
        return data
