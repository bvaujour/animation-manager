from datetime import date

from django import forms
from django.core.exceptions import ValidationError

from .models import AnneeScolaire, Centre, PeriodeCalendrier
from .services.creation_annee import (
    CATEGORIES, accueils_reutilisables, preparer_copie, calendrier_officiel,
    proposer_periodes_cibles, proposer_semaines_ete,
)
from .services.multisite import multisite_actif
from .services.calendrier_scolaire import CalendrierScolaireError


def _date_affichage(valeur):
    """Formate les dates des libellés, sans modifier leur valeur métier."""
    valeur = valeur if isinstance(valeur, date) else date.fromisoformat(valeur)
    return valeur.strftime("%d/%m/%Y")


class SourceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.libelle} — {obj.get_statut_display()}"


class NouvelleAnneeForm(forms.ModelForm):
    zone = forms.ChoiceField(label="Zone scolaire", choices=(("A", "Zone A"), ("B", "Zone B"), ("C", "Zone C")), initial="A", required=False)
    mode = forms.ChoiceField(label="Comment souhaitez-vous créer cette année scolaire ?", choices=(
        ("copie", "À partir d’une année existante"), ("vierge", "Créer une année vierge")), widget=forms.RadioSelect)
    source = SourceField(label="Année source (mode reprise uniquement)", queryset=AnneeScolaire.objects.all(), required=False)

    class Meta:
        model = AnneeScolaire
        fields = ("libelle", "date_debut", "date_fin", "zone")
        widgets = {champ: forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d") for champ in ("date_debut", "date_fin")}

    def clean(self):
        data = super().clean()
        if not data.get("zone"):
            data["zone"] = "A"
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

    def __init__(self, *args, cible, source, zone="A", **kwargs):
        super().__init__(*args, **kwargs)
        self.cible, self.source = cible, source
        if not multisite_actif():
            self.fields["centres"].queryset = self.fields["centres"].queryset.filter(pk=Centre.objects.order_by("pk").values_list("pk", flat=True).first())
        self.fields["accueils"].queryset = accueils_reutilisables(source, cible)
        self.periodes = list(PeriodeCalendrier.objects.filter(annee_scolaire=source.libelle).order_by("debut", "pk"))
        self.champs_dates = []
        decalage = cible.date_debut.year - source.date_debut.year
        self.zone = zone
        self.semaines_ete = []
        self.champs_ete = []
        self.periodes_scolaires = []
        self.vacances_courtes = []
        self.champs_periscolaires = []
        self.champs_vacances = []
        self.calendrier_officiel = None
        try:
            self.calendrier_officiel = calendrier_officiel(cible.libelle, self.zone)
        except CalendrierScolaireError as erreur:
            self.calendrier_erreur = erreur
        else:
            evenements = __import__("animateurs.models", fromlist=["Evenement"]).Evenement.objects.filter(
                groupe__type_groupe="structure").prefetch_related("periodes_scolaires")
            self.periodes_scolaires, self.vacances_courtes = proposer_periodes_cibles(
                source, self.calendrier_officiel, evenements)
            for periode in self.periodes_scolaires:
                nom_champ = f"scolaire_{periode['id']}"
                self.fields[nom_champ] = forms.BooleanField(
                    label=f"{periode['nom']} · {_date_affichage(periode['debut'])} au {_date_affichage(periode['fin'])}",
                    required=False, initial=periode["suggeree"])
                self.champs_periscolaires.append(self[nom_champ])
            for vacance in self.vacances_courtes:
                champs = []
                for semaine in vacance["semaines"]:
                    nom_champ = f"vacance_{vacance['id']}_{semaine['id']}"
                    self.fields[nom_champ] = forms.BooleanField(
                        label=f"{semaine['nom']} · {_date_affichage(semaine['debut'])} au {_date_affichage(semaine['fin'])}",
                        required=False, initial=semaine["suggeree"])
                    champs.append(self[nom_champ])
                self.champs_vacances.append({"nom": vacance["nom"], "champs": champs})
            self.semaines_ete = proposer_semaines_ete(source, cible, evenements, self.calendrier_officiel["debut_ete"])
            for semaine in self.semaines_ete:
                nom_champ = f"ete_{semaine['id']}"
                self.fields[nom_champ] = forms.BooleanField(
                    label=f"{semaine['nom']} · {_date_affichage(semaine['debut'])} au {_date_affichage(semaine['fin'])}",
                    required=False, initial=semaine["suggeree"])
                self.champs_ete.append(self[nom_champ])
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
        if hasattr(self, "calendrier_erreur"):
            raise ValidationError(f"Calendrier officiel indisponible : {self.calendrier_erreur}")
        dates = {p.pk: (data.get(f"periode_{p.pk}_debut"), data.get(f"periode_{p.pk}_fin")) for p in self.periodes}
        # Les dates ne sont obligatoires que pour les périodes effectivement reprises.
        try:
            self.plan = preparer_copie(self.cible, self.source,
                [c.pk for c in data["centres"]], [a.pk for a in data["accueils"]], data["categories"], dates)
        except TypeError:
            raise ValidationError("Renseignez les dates des périodes utilisées par les configurations sélectionnées.")
        self.plan["zone"] = self.zone
        self.plan["calendrier_officiel"] = self.calendrier_officiel
        self.plan["periodes_scolaires"] = [periode for periode in self.periodes_scolaires
                                            if data.get(f"scolaire_{periode['id']}")]
        self.plan["vacances_courtes"] = [
            {**vacance, "semaines": [semaine for semaine in vacance["semaines"]
                if data.get(f"vacance_{vacance['id']}_{semaine['id']}")]}
            for vacance in self.vacances_courtes
            if any(data.get(f"vacance_{vacance['id']}_{semaine['id']}") for semaine in vacance["semaines"])
        ]
        selection = {identifiant for identifiant in (semaine["id"] for semaine in self.semaines_ete)
                     if data.get(f"ete_{identifiant}")}
        evenement_ids = {evenement.pk for evenement in self.plan["evenements"]}
        self.plan["semaines_ete"] = [candidate for candidate in (
            {**semaine, "evenement_ids": [pk for pk in semaine["evenement_ids"] if pk in evenement_ids]}
            for semaine in self.semaines_ete if semaine["id"] in selection
        )]
        return data
