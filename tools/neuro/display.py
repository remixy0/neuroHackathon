"""Wypisywanie rozpoznan jako odcinkow czasu z pewnoscia (wspolne dla pliku i strumienia na zywo)."""
from __future__ import annotations

import sys

from .model import FAMILY_PL
from .pipeline import WIN_S
from .position import describe


class SegmentPrinter:
    def __init__(self, min_family: float = 0.45, min_conf: float = 0.25, show_rest: bool = False,
                 status_line: bool = False, on_segment=None):
        self.on_segment = on_segment  # zamiast wypisywania: funkcja(dict) dla kazdego zakonczonego odcinka
        self.min_family, self.min_conf, self.show_rest = min_family, min_conf, show_rest
        self.status_line = status_line and sys.stdout.isatty()
        self.seg = None  # [poczatek, koniec, klucz, opis, pewnosci, pewnosci rodziny]

    def _describe(self, res: dict) -> tuple[str, str]:
        if res["family_confidence"] < self.min_family:
            return "rest", "(niepewne)"
        if res["family"] == "rest":
            return "rest", "spoczynek"
        if res["confidence"] < self.min_conf:
            return "?" + res["family"], f"{FAMILY_PL[res['family']]} (rodzaj niepewny)"
        return res["label"], res["label_pl"]

    def feed(self, res: dict) -> None:
        t = res["t"] - WIN_S / 2  # srodek okna analizy
        key, desc = self._describe(res)
        if self.seg and self.seg[2] == key:
            self.seg[1] = t
            self.seg[4].append(res["confidence"])
            self.seg[5].append(res["family_confidence"])
        else:
            self.flush()
            self.seg = [t, t, key, desc, [res["confidence"]], [res["family_confidence"]]]
        if self.status_line:
            print(f"\r\033[K  teraz ({t:6.1f}s): {desc}  {res['confidence'] * 100:.0f}%"
                  f"  [rodzina {res['family_pl']} {res['family_confidence'] * 100:.0f}%]"
                  + (f"  |  {describe(res['position'])}" if res.get("position") else ""), end="", flush=True)

    def flush(self) -> None:
        s = self.seg
        self.seg = None
        if s and (self.show_rest or s[2] != "rest") and len(s[4]) >= 2 and self.on_segment:
            self.on_segment({"start": round(s[0], 2), "end": round(s[1], 2), "key": s[2], "label_pl": s[3],
                             "confidence": max(s[4]), "family_confidence": max(s[5])})
        elif s and (self.show_rest or s[2] != "rest") and len(s[4]) >= 2:
            if self.status_line:
                print("\r\033[K", end="")
            print(f"{s[0]:7.2f}s - {s[1]:7.2f}s  {s[3]:28s} pewnosc {max(s[4]) * 100:3.0f}%   "
                  f"(rodzina: {max(s[5]) * 100:3.0f}%)", flush=True)
