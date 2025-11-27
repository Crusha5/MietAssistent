import json
import os
from functools import lru_cache


@lru_cache(maxsize=1)
def load_project_profile():
    """Lade die Projektbeschreibung aus der Datei ``Projekt_ziel.txt``.

    Falls die Datei fehlt oder nicht gelesen werden kann, wird ein schlanker
    Standardwert zurückgegeben, damit die Anwendung weiterläuft.
    """
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
    profile_path = os.path.join(base_dir, "Projekt_ziel.txt")

    default_profile = {
        "project": {
            "display_name": "MietAssistent",
            "version": "unbekannt",
            "tagline": "Digitale Mietverwaltung"
        },
        "branding": {
            "color_scheme": {
                "primary": "#1e40af",
                "secondary": "#0f766e",
                "accent": "#dc2626",
                "background": "#f8fafc",
                "surface": "#ffffff"
            }
        }
    }

    if not os.path.exists(profile_path):
        return default_profile

    try:
        with open(profile_path, "r", encoding="utf-8") as profile_file:
            profile = json.load(profile_file)
            merged = default_profile
            merged.update(profile)
            merged.setdefault("branding", default_profile["branding"])
            merged.setdefault("project", default_profile["project"])
            return merged
    except (json.JSONDecodeError, OSError):
        return default_profile
