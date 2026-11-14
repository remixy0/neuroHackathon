"""Ustawienia serwera: co robi każdy gest w każdej grze Arcade, progi pewności, adres Arcade.

Plik settings.json (zapis atomowy). Brakujące pola uzupełniane domyślnymi, więc stary/niepełny plik działa.
"""
from __future__ import annotations

import copy
import json
import os
import tempfile
from pathlib import Path

from .protocol import BUTTONS

GESTURES = ["head_left", "head_right", "head_up", "head_down", "jaw", "frown", "blink", "look_left", "look_right"]
PROFILES = ["menu", "tetris", "pong", "runner"]
GESTURE_PL = {
    "head_left": "Głowa w lewo", "head_right": "Głowa w prawo", "head_up": "Głowa w górę",
    "head_down": "Głowa w dół", "jaw": "Zaciśnięcie szczęki", "frown": "Zmarszczenie czoła",
    "blink": "Mrugnięcie", "look_left": "Spojrzenie w lewo", "look_right": "Spojrzenie w prawo",
}
PROFILE_PL = {"menu": "Menu", "tetris": "Tetris", "pong": "Pong", "runner": "Runner"}
DEFAULT_ARCADE_URL = "ws://localhost:8787"
TAP_MS = 120
MS_RANGE = (30, 2000)
THRESHOLD_RANGE = (0.05, 0.99)
DEFAULT_THRESHOLD = 0.5
DEFAULT_GAP_S = 0.8          # odstęp między powtórzeniami tego samego gestu (aplikacja macOS: 1,5 s)
GAP_RANGE = (0.3, 3.0)

# gest -> (przycisk, ms); brak gestu = wyłączony
_DEFAULTS: dict[str, dict[str, tuple[str, int]]] = {
    "menu": {"head_left": ("left", TAP_MS), "head_right": ("right", TAP_MS), "head_up": ("up", TAP_MS),
             "head_down": ("down", TAP_MS), "jaw": ("a", TAP_MS), "frown": ("b", TAP_MS)},
    "tetris": {"head_left": ("left", TAP_MS), "head_right": ("right", TAP_MS), "head_up": ("up", TAP_MS),
               "head_down": ("down", 400), "jaw": ("a", TAP_MS), "frown": ("b", TAP_MS)},
    "pong": {"head_up": ("up", 300), "head_down": ("down", 300)},
    "runner": {"head_left": ("left", TAP_MS), "head_right": ("right", TAP_MS), "head_up": ("up", TAP_MS),
               "head_down": ("down", TAP_MS), "jaw": ("a", TAP_MS), "frown": ("b", TAP_MS)},
}


def profile_for(state: dict | None) -> str:
    """Profil mapowania dla bieżącego stanu Arcade: gra tylko na ekranie gry, inaczej menu."""
    if not isinstance(state, dict) or state.get("screen") != "game":
        return "menu"
    game = state.get("game")
    return game if game in PROFILES and game != "menu" else "menu"


def default_settings(model_thresholds: dict[str, float]) -> dict:
    profiles = {}
    for p in PROFILES:
        profiles[p] = {}
        for g in GESTURES:
            button, ms = _DEFAULTS[p].get(g, (None, TAP_MS))
            profiles[p][g] = {"button": button, "ms": ms}
    thresholds = {g: round(float(model_thresholds.get(g, DEFAULT_THRESHOLD)), 3) for g in GESTURES}
    return {"arcade_url": DEFAULT_ARCADE_URL, "refractory_s": DEFAULT_GAP_S, "thresholds": thresholds,
            "profiles": profiles}


def validate(data: dict, defaults: dict) -> dict:
    """Sprawdza ustawienia i uzupełnia braki z defaults. ValueError przy złych wartościach."""
    if not isinstance(data, dict):
        raise ValueError("ustawienia muszą być obiektem")
    out = copy.deepcopy(defaults)

    if "arcade_url" in data:
        url = data["arcade_url"]
        if not isinstance(url, str) or not url.startswith(("ws://", "wss://")) or len(url) > 300:
            raise ValueError("adres Arcade musi zaczynać się od ws:// albo wss://")
        out["arcade_url"] = url.strip()

    if "refractory_s" in data:
        gap = data["refractory_s"]
        if isinstance(gap, bool) or not isinstance(gap, (int, float)) or not GAP_RANGE[0] <= gap <= GAP_RANGE[1]:
            raise ValueError(f"odstęp między gestami musi być w zakresie {GAP_RANGE[0]}-{GAP_RANGE[1]} s")
        out["refractory_s"] = round(float(gap), 2)

    thr = data.get("thresholds", {})
    if not isinstance(thr, dict):
        raise ValueError("thresholds musi być obiektem")
    for g, v in thr.items():
        if g not in GESTURES:
            raise ValueError(f"nieznany gest {g!r}")
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not THRESHOLD_RANGE[0] <= v <= THRESHOLD_RANGE[1]:
            raise ValueError(f"próg {g} musi być w zakresie {THRESHOLD_RANGE}")
        out["thresholds"][g] = round(float(v), 3)

    profiles = data.get("profiles", {})
    if not isinstance(profiles, dict):
        raise ValueError("profiles musi być obiektem")
    for p, mapping in profiles.items():
        if p not in PROFILES:
            raise ValueError(f"nieznany profil {p!r}")
        if not isinstance(mapping, dict):
            raise ValueError(f"profil {p} musi być obiektem")
        for g, entry in mapping.items():
            if g not in GESTURES:
                raise ValueError(f"nieznany gest {g!r}")
            if not isinstance(entry, dict):
                raise ValueError(f"{p}/{g}: wpis musi być obiektem")
            button = entry.get("button")
            if button is not None and button not in BUTTONS:
                raise ValueError(f"{p}/{g}: nieznany przycisk {button!r}")
            ms = entry.get("ms", TAP_MS)
            if isinstance(ms, bool) or not isinstance(ms, int) or not MS_RANGE[0] <= ms <= MS_RANGE[1]:
                raise ValueError(f"{p}/{g}: czas musi być liczbą całkowitą {MS_RANGE[0]}-{MS_RANGE[1]} ms")
            out["profiles"][p][g] = {"button": button, "ms": ms}
    return out


class SettingsStore:
    def __init__(self, path: Path | str, model_thresholds: dict[str, float]):
        self.path = Path(path)
        self.defaults = default_settings(model_thresholds)
        self.data = self._load()

    def _load(self) -> dict:
        try:
            return validate(json.loads(self.path.read_text(encoding="utf-8")), self.defaults)
        except (OSError, ValueError):
            return copy.deepcopy(self.defaults)

    def replace(self, new: dict) -> dict:
        data = validate(new, self.defaults)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".settings-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        self.data = data
        return data

    def action(self, profile: str, gesture: str) -> tuple[str, int] | None:
        entry = self.data["profiles"].get(profile, {}).get(gesture)
        if not entry or entry["button"] is None:
            return None
        return entry["button"], entry["ms"]
