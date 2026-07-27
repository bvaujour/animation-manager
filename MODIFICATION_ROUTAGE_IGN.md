# Remplacement du calcul d’itinéraire par la Géoplateforme IGN

## Modifications

- fournisseur par défaut : `geoplateforme` ;
- géocodage : `https://data.geopf.fr/geocodage/search` ;
- itinéraire : `https://data.geopf.fr/navigation/itineraire` ;
- ressource routière : `bdtopo-osrm` ;
- aucune clé API nécessaire ;
- calcul effectué côté serveur et tronçon par tronçon pour respecter l’ordre des lieux ;
- addition des durées routières, puis ajout du temps d’arrêt par site ;
- libellé de source mis à jour dans la page Sorties ;
- une adresse, une commune ou un code postal peuvent servir au géocodage lorsqu’aucune coordonnée n’est enregistrée.

## Configuration

```env
ROUTING_PROVIDER=geoplateforme
ROUTING_API_URL=https://data.geopf.fr/navigation/itineraire
ROUTING_GEOCODING_URL=https://data.geopf.fr/geocodage/search
ROUTING_RESOURCE=bdtopo-osrm
ROUTING_TIMEOUT_SECONDS=8
```

Aucune migration de base de données n’est nécessaire pour ce changement.

## Vérifications effectuées

- syntaxe Python des fichiers modifiés : OK ;
- syntaxe JavaScript : OK ;
- absence de référence restante à OpenRouteService dans le code actif : OK.

La suite Django n’a pas pu être exécutée dans l’environnement d’analyse, où Django n’est pas installé.
