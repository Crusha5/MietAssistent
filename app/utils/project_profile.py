import json
import os
from functools import lru_cache


def _profile_signature(profile_path: str) -> float:
    """Bestimmt eine Signatur für den Profil-Cache basierend auf dem MTime."""
    try:
        return os.path.getmtime(profile_path)
    except OSError:
        return 0.0


def load_project_profile():
    """Lade die Projektbeschreibung aus der Datei ``Projekt_ziel.txt``.

    Falls die Datei fehlt oder nicht gelesen werden kann, wird ein schlanker
    Standardwert zurückgegeben, damit die Anwendung weiterläuft. Über den
    MTime des Files wird ein Light-Cache genutzt, der Änderungen automatisch
    neu einliest.
    """
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
    profile_path = os.path.join(base_dir, "Projekt_ziel.txt")
    signature = _profile_signature(profile_path)
    return _load_profile_cached(profile_path, signature)


@lru_cache(maxsize=1)
def _load_profile_cached(profile_path: str, signature: float):
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
