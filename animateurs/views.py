from django.shortcuts import render

# Create your views here.

def accueil(request):
    return render(request, "accueil.html")

def documents(request):
    return render(request, "documents.html")