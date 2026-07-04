from django.shortcuts import render
from .models import Document
from django.http import JsonResponse
# Create your views here.

def accueil(request):
    return render(request, "accueil.html")

def planning(request):
    return render(request, "planning.html")

def api_planning(request):
    events = [
        {
            "title": "Julie - LP 3/5 ans",
            "start": "2026-07-06T08:00:00",
            "end": "2026-07-06T17:30:00",
        },
        {
            "title": "Lou-Anne - SF 6/10 ans",
            "start": "2026-07-07T08:30:00",
            "end": "2026-07-07T18:00:00",
        },
    ]

    return JsonResponse(events, safe=False)

def documents(request):

    docs = Document.objects.all()

    documents_data = []

    for doc in docs:
        documents_data.append({
            "titre": doc.titre,
            "url": doc.fichier.url,
        })

    return render(
        request,
        "documents.html",
        {
            "documents": documents_data
        }
    )