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

GESTURES = ["head_left", "head_right", "head_up", "head_down", "jaw", "frown", "long_blink", "look_left",
            "look_right"]
# dawne gesty w starych plikach ustawień -> gest, który je zastąpił (przycisk przechodzi, próg nie: inny ruch)
# długie mrugnięcie (oczy zamknięte ~0,5 s, blinks.LongBlink) zastąpiło podwójne (15.11.2026): zwykłe mrugnięcie wygląda
# jak mimowolne, a podwójne trafiało ok. 60%
LEGACY = {"double_blink": "long_blink", "blink": "long_blink"}   # kolejność: nowszy wpis wygrywa
# gesty z reguły na sygnale (nie z modelu): id -> skąd
RULE_GESTURES = {"long_blink": "fp"}
PROFILES = ["menu", "tetris", "pong", "runner"]
GESTURE_PL = {
    "head_left": "Przechył / obrót w lewo", "head_right": "Przechył / obrót w prawo", "head_up": "Głowa w górę",
    "head_down": "Głowa w dół", "jaw": "Zaciśnięcie szczęki", "frown": "Zmarszczenie czoła",
    "long_blink": "Długie mrugnięcie (oczy zamknięte ~0,5 s)", "look_left": "Spojrzenie w lewo",
    "look_right": "Spojrzenie w prawo",
}
PROFILE_PL = {"menu": "Menu", "tetris": "Tetris", "pong": "Pong", "runner": "Runner"}
DEFAULT_ARCADE_URL = "ws://localhost:8787"
TAP_MS = 120
MS_RANGE = (30, 2000)
THRESHOLD_RANGE = (0.05, 0.99)
DEFAULT_THRESHOLD = 0.5
DEFAULT_GAP_S = 0.8          # odstęp między powtórzeniami tego samego gestu (aplikacja macOS: 1,5 s)
GAP_RANGE = (0.3, 3.0)
# głowa z akcelerometru (przechył w bok = lewo/prawo, pochylenie = góra/dół): gest od tylu stopni, gdy kierunek nie
# ma progu z kalibracji (gestures/tilt.py; nagrania: skinienia 37-41°)
DEFAULT_TILT_DEG = 15.0
TILT_RANGE = (5.0, 40.0)
# lewo/prawo także obrotem głowy (żyroskop, wokół pionu): gest od tylu stopni, gdy kierunek nie ma progu z kalibracji.
# Nagrania: obroty 37-80°, przechyły i skinienia dają po drodze do 11° obrotu (gestures/tilt.py).
DEFAULT_TURN_DEG = 20.0
TURN_RANGE = (8.0, 60.0)
# Tryb głowy w grze: "digital" = jeden ruch głowy -> jedno naciśnięcie (Runner: pas po pasie), "analog" = pochylenie
# głowy -> pozycja 0..1 wysyłana do Arcade na bieżąco (Pong: paletka podąża za głową). Oś analogową ("pos") ma
# w Arcade tylko Pong. Pełne wychylenie: analog_range_deg (kalibracja dobiera je osobie; gestures/tilt.py AnalogAxis).
HEAD_MODES = ("digital", "analog")
ANALOG_PROFILES = ("pong",)
DEFAULT_HEAD_MODE = {"menu": "digital", "tetris": "digital", "pong": "analog", "runner": "digital"}
DEFAULT_ANALOG_RANGE_DEG = 20.0      # = gestures.tilt.ANALOG_RANGE_DEG
ANALOG_RANGE = (8.0, 40.0)
# Schemat 2 (15.11.2026): głowa z akcelerometru, EEG głównie do podwójnego mrugnięcia i spojrzeń - szczęka i czoło
# wyłączone w grach, podwójne mrugnięcie = A, spojrzenia = lewo/prawo. Starszy plik jest przestawiany raz (_migrate_v2).
SCHEMA = 2
# gest twarzy/oczu z modelu jest pomijany, gdy w ostatnich MUTE_S sekundach głowa ruszała się szybciej niż MUTE_DPS
DEFAULT_MUTE_S = 1.5
MUTE_S_RANGE = (0.0, 5.0)    # 0 = wyłączone
DEFAULT_MUTE_DPS = 30.0
MUTE_DPS_RANGE = (10.0, 200.0)
FLAGS = ("calibration", "voice", "record", "head_turn")   # kalibracja na starcie sesji, polecenia głosem, zapis sesji
# na dysk, lewo/prawo także obrotem głowy
# Dawne pole "blink_source" (podwójne mrugnięcie z Fp albo z modelu) jest pomijane: długie mrugnięcie liczy zawsze Fp.

# gest -> (przycisk, ms); brak gestu = wyłączony
_EEG = {"long_blink": ("a", TAP_MS), "look_left": ("left", TAP_MS), "look_right": ("right", TAP_MS)}
_DEFAULTS: dict[str, dict[str, tuple[str, int]]] = {
    "menu": {"head_left": ("left", TAP_MS), "head_right": ("right", TAP_MS), "head_up": ("up", TAP_MS),
             "head_down": ("down", TAP_MS), **_EEG},
    "tetris": {"head_left": ("left", TAP_MS), "head_right": ("right", TAP_MS), "head_up": ("up", TAP_MS),
               "head_down": ("down", 400), **_EEG},
    "pong": {"head_up": ("up", 300), "head_down": ("down", 300)},
    "runner": {"head_left": ("left", TAP_MS), "head_right": ("right", TAP_MS), "head_up": ("up", TAP_MS),
               "head_down": ("down", TAP_MS), **_EEG},
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
    return {"schema": SCHEMA, "arcade_url": DEFAULT_ARCADE_URL, "refractory_s": DEFAULT_GAP_S,
            "head_tilt_deg": DEFAULT_TILT_DEG, "head_turn": True, "head_turn_deg": DEFAULT_TURN_DEG,
            "head_mode": dict(DEFAULT_HEAD_MODE), "analog_range_deg": DEFAULT_ANALOG_RANGE_DEG,
            "calibration": True, "voice": True, "record": True,
            "motion_mute_s": DEFAULT_MUTE_S, "motion_mute_dps": DEFAULT_MUTE_DPS,
            "thresholds": thresholds, "profiles": profiles}


def _number(data: dict, key: str, lo: float, hi: float, what: str, unit: str) -> float | None:
    if key not in data:
        return None
    v = data[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
        raise ValueError(f"{what} musi być w zakresie {lo:g}-{hi:g} {unit}")
    return float(v)


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

    # "head_gyro", "head_gyro_dps" (dawna głowa z żyroskopu) są pomijane jak każde nieznane pole
    deg = _number(data, "head_tilt_deg", *TILT_RANGE, "próg ruchu głowy", "°")
    if deg is not None:
        out["head_tilt_deg"] = round(deg, 1)
    turn = _number(data, "head_turn_deg", *TURN_RANGE, "próg obrotu głowy", "°")
    if turn is not None:
        out["head_turn_deg"] = round(turn, 1)
    if "head_mode" in data:
        modes = data["head_mode"]
        if not isinstance(modes, dict):
            raise ValueError("tryb głowy musi być obiektem {gra: digital|analog}")
        for p, m in modes.items():
            if p not in PROFILES:
                raise ValueError(f"nieznany profil {p!r}")
            if m not in HEAD_MODES:
                raise ValueError(f"{p}: tryb głowy musi być digital albo analog")
            if m == "analog" and p not in ANALOG_PROFILES:
                raise ValueError(f"{p}: tryb analogowy działa tylko w grach z osią analogową ({', '.join(ANALOG_PROFILES)})")
            out["head_mode"][p] = m
    rng = _number(data, "analog_range_deg", *ANALOG_RANGE, "pełne wychylenie w trybie analogowym", "°")
    if rng is not None:
        out["analog_range_deg"] = round(rng, 1)
    mute_s = _number(data, "motion_mute_s", *MUTE_S_RANGE, "czas wyciszenia po ruchu głowy", "s")
    if mute_s is not None:
        out["motion_mute_s"] = round(mute_s, 2)
    mute_dps = _number(data, "motion_mute_dps", *MUTE_DPS_RANGE, "prędkość głowy wyciszająca gesty twarzy", "°/s")
    if mute_dps is not None:
        out["motion_mute_dps"] = round(mute_dps, 1)
    for flag in FLAGS:
        if flag in data:
            if not isinstance(data[flag], bool):
                raise ValueError(f"{flag} musi być true albo false")
            out[flag] = data[flag]

    thr = data.get("thresholds", {})
    if not isinstance(thr, dict):
        raise ValueError("thresholds musi być obiektem")
    thr = {g: v for g, v in thr.items() if g not in LEGACY}
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
        mapping = dict(mapping)
        for old, new in LEGACY.items():
            if old in mapping:
                mapping.setdefault(new, mapping[old])
                del mapping[old]
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
    if not isinstance(data.get("schema"), int) or isinstance(data.get("schema"), bool) or data["schema"] < SCHEMA:
        _migrate_v2(out["profiles"])
    out["schema"] = SCHEMA
    return out


def _migrate_v2(profiles: dict) -> None:
    """Plik sprzed schematu 2: szczęka i czoło wyłączone, wolne długie mrugnięcie i spojrzenia jak w domyślnych."""
    for p, mapping in profiles.items():
        for g in ("jaw", "frown"):
            mapping[g]["button"] = None
        for g, (button, ms) in _DEFAULTS[p].items():
            if g in _EEG and mapping[g]["button"] is None:
                mapping[g] = {"button": button, "ms": ms}


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
