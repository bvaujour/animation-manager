#!/usr/bin/env python3
"""Contrôles statiques sans dépendance externe pour Animation Manager."""

from __future__ import annotations

import ast
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"
STATIC = ROOT / "static"
ERRORS: list[str] = []


def fail(message: str) -> None:
    ERRORS.append(message)


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def check_python_syntax() -> int:
    count = 0
    ignored = {".git", ".venv", "venv", "staticfiles"}
    for path in ROOT.rglob("*.py"):
        if any(part in ignored for part in path.parts):
            continue
        count += 1
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError) as exc:
            fail(f"Syntaxe Python invalide dans {relative(path)} : {exc}")
    return count


def check_generated_artifacts() -> None:
    forbidden_dirs = [ROOT / "anim_manager_effectifs_icons", ROOT / "staticfiles"]
    for path in forbidden_dirs:
        if path.exists():
            fail(f"Répertoire généré ou historique encore présent : {relative(path)}")

    for pattern in ("__pycache__", "*.pyc", "*.pyo"):
        for path in ROOT.rglob(pattern):
            if ".git" not in path.parts and ".venv" not in path.parts and "venv" not in path.parts:
                fail(f"Artefact Python encore présent : {relative(path)}")


def check_template_references() -> tuple[int, int]:
    template_count = 0
    static_references = 0
    template_ref_pattern = re.compile(r"{%\s*(?:extends|include)\s+[\"']([^\"']+)[\"']")
    static_ref_pattern = re.compile(r"{%\s*static\s+[\"']([^\"']+)[\"']")
    hardcoded_version_pattern = re.compile(r"\?v=(?!{{\s*asset_version\s*}})")

    for path in TEMPLATES.rglob("*.html"):
        template_count += 1
        text = path.read_text(encoding="utf-8")
        for reference in template_ref_pattern.findall(text):
            if not (TEMPLATES / reference).is_file():
                fail(f"Template manquant référencé par {relative(path)} : {reference}")
        for reference in static_ref_pattern.findall(text):
            static_references += 1
            if not (STATIC / reference).is_file():
                fail(f"Fichier statique manquant référencé par {relative(path)} : {reference}")
        if hardcoded_version_pattern.search(text):
            fail(f"Version d'asset codée en dur dans {relative(path)}")

    render_pattern = re.compile(r"render\(\s*[^,]+,\s*[\"']([^\"']+\.html)[\"']", re.DOTALL)
    for path in (ROOT / "animateurs").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for reference in render_pattern.findall(text):
            if not (TEMPLATES / reference).is_file():
                fail(f"Template rendu mais absent dans {relative(path)} : {reference}")

    return template_count, static_references


def imported_names(module: ast.Module, module_name: str) -> set[str]:
    names: set[str] = set()
    for node in module.body:
        if isinstance(node, ast.ImportFrom) and node.module == module_name:
            names.update(alias.asname or alias.name for alias in node.names)
    return names


def check_views_facade() -> int:
    urls_path = ROOT / "animateurs" / "urls.py"
    facade_path = ROOT / "animateurs" / "views.py"
    urls_module = ast.parse(urls_path.read_text(encoding="utf-8"))
    facade_module = ast.parse(facade_path.read_text(encoding="utf-8"))
    route_names = imported_names(urls_module, "views")

    exported_names: set[str] = set()
    for node in facade_module.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets):
                if isinstance(node.value, (ast.List, ast.Tuple)):
                    for element in node.value.elts:
                        if isinstance(element, ast.Constant) and isinstance(element.value, str):
                            exported_names.add(element.value)

    missing = sorted(route_names - exported_names)
    extras = sorted(exported_names - route_names)
    if missing:
        fail(f"Vues utilisées par les routes mais absentes de la façade : {', '.join(missing)}")
    if extras:
        fail(f"Exports de façade sans route correspondante : {', '.join(extras)}")
    return len(route_names)


def check_migrations() -> int:
    migrations_dir = ROOT / "animateurs" / "migrations"
    numbered: list[str] = []
    for path in migrations_dir.glob("[0-9][0-9][0-9][0-9]_*.py"):
        numbered.append(path.name[:4])
    duplicates = [number for number, count in Counter(numbered).items() if count > 1]
    if duplicates:
        fail(f"Numéros de migrations en double : {', '.join(sorted(duplicates))}")
    return len(numbered)


def check_sqlite() -> str:
    database = ROOT / "db.sqlite3"
    if not database.is_file():
        return "absente"
    try:
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
            result = connection.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.Error as exc:
        fail(f"Impossible de contrôler db.sqlite3 : {exc}")
        return "erreur"
    status = str(result[0]) if result else "aucun résultat"
    if status.lower() != "ok":
        fail(f"Intégrité SQLite invalide : {status}")
    return status


def main() -> int:
    python_files = check_python_syntax()
    check_generated_artifacts()
    templates, static_references = check_template_references()
    route_views = check_views_facade()
    migrations = check_migrations()
    sqlite_status = check_sqlite()

    if ERRORS:
        print("Audit statique : ÉCHEC", file=sys.stderr)
        for error in ERRORS:
            print(f"- {error}", file=sys.stderr)
        return 1

    print("Audit statique : OK")
    print(f"- {python_files} fichiers Python analysés")
    print(f"- {templates} templates et {static_references} références statiques contrôlés")
    print(f"- {route_views} vues de façade comparées aux routes")
    print(f"- {migrations} migrations numérotées, sans doublon")
    print(f"- intégrité SQLite : {sqlite_status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
