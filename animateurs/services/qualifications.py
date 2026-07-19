"""Outils liés aux qualifications et à leurs règles d'équivalence."""

from collections import defaultdict, deque

from animateurs.models import EquivalenceQualification, Qualification


def couvertures_qualifications():
    """Retourne les qualifications satisfaites par chaque qualification détenue.

    Une règle ``A → B`` permet à une personne possédant A de couvrir un besoin
    B, sans rendre automatiquement B équivalent à A. Les règles restent
    transitives : avec ``A → B`` puis ``B → C``, A couvre aussi C. Une règle à
    double sens ajoute naturellement les deux directions.
    """

    ids = set(Qualification.objects.values_list("id", flat=True))
    adjacency = defaultdict(set)
    for qualification_id in ids:
        adjacency[qualification_id].add(qualification_id)

    relations = EquivalenceQualification.objects.all().only(
        "qualification_a_id", "qualification_b_id", "sens"
    )
    for relation in relations:
        a_id = relation.qualification_a_id
        b_id = relation.qualification_b_id
        if relation.sens in (
            EquivalenceQualification.SENS_A_VERS_B,
            EquivalenceQualification.SENS_DOUBLE,
        ):
            adjacency[a_id].add(b_id)
        if relation.sens in (
            EquivalenceQualification.SENS_B_VERS_A,
            EquivalenceQualification.SENS_DOUBLE,
        ):
            adjacency[b_id].add(a_id)

    couvertures = {}
    for qualification_id in ids:
        atteignables = set()
        file = deque([qualification_id])
        while file:
            courant = file.popleft()
            if courant in atteignables:
                continue
            atteignables.add(courant)
            file.extend(adjacency[courant] - atteignables)
        couvertures[qualification_id] = atteignables

    return couvertures


def classes_equivalence_qualifications():
    """Alias conservé pour le solveur et les éventuels appels existants.

    Le résultat n'est plus forcément une classe symétrique : il représente
    désormais les qualifications couvertes dans le sens autorisé.
    """

    return couvertures_qualifications()
