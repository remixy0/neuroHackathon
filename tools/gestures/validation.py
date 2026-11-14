"""Pomiar dokladnosci modelu gestow: walidacja krzyzowa na oknach i symulacja pracy na zywo.

Trzy podzialy (folds), od najtrudniejszego:
  person  - model nie widzial tej OSOBY (nowy uzytkownik bez wlasnych danych);
  session - model nie widzial tej SESJI (znana osoba, nowe zalozenie czepka; dopoki osoba ma jedna sesje
            danego gestu, model nie zna tez jej wykonania tego gestu);
  block   - model nie widzial tych PROB (5 kolejnych blokow prob w kazdej sesji: ta sama osoba, to samo
            zalozenie czepka - gorna granica tego, co da dogranie wlasnych danych).
Okna jednej proby nigdy nie trafiaja jednoczesnie do treningu i testu.
"""
from __future__ import annotations

import numpy as np

from . import model as gm
from .data import CLASSES
from .dataset import Windows

N_BLOCKS = 5
SCORED_KINDS = ("event", "hold", "rest", "quiet")   # "moving" (ruch glowy przed sygnalem) nie ma pewnej etykiety
HOWS = ("person", "session", "block")


def folds(W: Windows, how: str) -> np.ndarray:
    """Numer czesci walidacji dla kazdego okna."""
    if how == "person":
        return np.unique(W.person, return_inverse=True)[1]
    if how == "session":
        return np.unique(W.session, return_inverse=True)[1]
    if how != "block":
        raise ValueError(f"nieznany podzial: {how}")
    out = np.zeros(len(W), dtype=int)
    for sid in np.unique(W.session):
        m = W.session == sid
        # baseline (rest) dzielimy osobno: inaczej cala cisza z poczatku sesji trafilaby do pierwszego bloku
        for part in (m & (W.kind == "rest"), m & (W.kind != "rest")):
            trials = np.unique(W.trial[part])
            if not len(trials):
                continue
            first = np.array([W.end_s[part & (W.trial == t)].min() for t in trials])
            rank = np.argsort(np.argsort(first))
            block = dict(zip(trials, rank * N_BLOCKS // len(trials)))
            out[part] = [block[t] for t in W.trial[part]]
    return out


def cv_proba(W: Windows, fold: np.ndarray) -> np.ndarray:
    """Prawdopodobienstwa (okna x CLASSES) z modeli, ktore nie widzialy czesci, do ktorej nalezy okno.
    Tlo do normalizacji liczymy raz, z okien spoczynku calej sesji (bez etykiet gestow - tak jak na zywo)."""
    Z = gm.normalize_windows(W)
    P = np.zeros((len(W), len(CLASSES)))
    for f in np.unique(fold):
        te = fold == f
        if te.all():
            continue
        clf, keep = gm.fit(W[~te], Z=Z[~te])
        P[te] = gm.predict_proba(clf, keep, W[te], Z=Z[te])
    return P


def _ratio(a: int, b: int) -> float | None:
    return round(a / b, 4) if b else None


def trial_predictions(W: Windows, P: np.ndarray) -> list[tuple[str, str, bool, str]]:
    """[(etykieta, rozpoznanie, weak, osoba)] dla kazdej proby z gestem: klasa o najwyzszym srednim
    prawdopodobienstwie w oknach zdarzenia tej proby (na zywo prawdopodobienstwa tez sa usredniane)."""
    out = []
    ev = W.kind == "event"
    for t in np.unique(W.trial[ev]):
        m = ev & (W.trial == t)
        i = int(np.argmax(m))
        out.append((str(W.y[i]), CLASSES[int(P[m].mean(axis=0).argmax())],
                    bool(W.weak[i]) if W.weak is not None else False, str(W.person[i])))
    return out


def window_metrics(W: Windows, P: np.ndarray) -> dict:
    """Trafnosc na oknach i na probach. Klasa bez danych -> None."""
    m = np.isin(W.kind, SCORED_KINDS)
    y = W.y[m]
    pred = np.array(CLASSES, dtype=object)[P[m].argmax(axis=1)] if m.any() else np.array([], dtype=object)
    trials = trial_predictions(W, P)
    per, recalls = {}, []
    for c in CLASSES:
        n = int((y == c).sum())
        tr = [(lab == p, weak) for lab, p, weak, _ in trials if lab == c]
        per[c] = {
            "n_windows": n,
            "recall": _ratio(int(((y == c) & (pred == c)).sum()), n),
            "precision": _ratio(int(((y == c) & (pred == c)).sum()), int((pred == c).sum())),
            "n_trials": len(tr),
            "trial_recall": _ratio(sum(ok for ok, _ in tr), len(tr)),
            "n_trials_visible": sum(not weak for _, weak in tr),
            "trial_recall_visible": _ratio(sum(ok for ok, weak in tr if not weak), sum(not weak for _, weak in tr)),
        }
        if n:
            recalls.append(per[c]["recall"])
    bg = np.isin(W.kind[m], ["rest", "quiet"])
    return {
        "n_windows": int(m.sum()),
        "accuracy": _ratio(int((pred == y).sum()), int(m.sum())),
        "balanced_accuracy": round(float(np.mean(recalls)), 4) if recalls else None,
        "trial_accuracy": _ratio(sum(lab == p for lab, p, _, _ in trials), len(trials)),
        "false_alarm_rate": _ratio(int((pred[bg] != "rest").sum()), int(bg.sum())),
        "per_class": per,
        "confusion": {c: {d: int(((y == c) & (pred == d)).sum()) for d in CLASSES} for c in CLASSES},
    }


# --- symulacja pracy na zywo -------------------------------------------------------------------------------
# Cala sesja przechodzi przez GestureRecognizer (te same filtry, tlo z biegnacej mediany, wygladzanie, progi
# klas, blokada powtorzen i ruchow powrotnych) modelem, ktory nie widzial tej osoby. Liczymy zgloszenia.
BLINK_SPAN_S = 2.0        # mrugniecie: zgloszenie liczy sie do tylu sekund po sygnale
HIT_AFTER_END_S = 0.5     # gesty trzymane: zgloszenie liczy sie do tylu sekund po sygnale powrotu
RETURN_SPAN_S = 2.0       # potem tyle sekund powrotu (glowa/oczy do srodka, rozluznienie): ani trafienie, ani alarm
KEY_HIT_AFTER_S = 1.0     # tryb klawiatury: zgloszenie liczy sie do tylu sekund po koncu odcinka key_press
STREAM_WARMUP_S = 3.0


def stream_events(s, bundle: dict) -> list[tuple[float, str, float]]:
    """[(sekunda, zgloszony gest, pewnosc)] dla calej sesji."""
    from .recognizer import GestureRecognizer
    r = GestureRecognizer(s.channels, s.fs, model=bundle)
    return [(o["t"], o["event"], o["confidence"]) for o in r.run(s.x) if o["event"]]


def session_spans(s) -> tuple[list[tuple[float, float, str]], list[tuple[float, float]]]:
    """(proby [(od, do, etykieta)], odcinki wylaczone z liczenia alarmow [(od, do)]) w sekundach."""
    trials, excluded = [], []
    for iv in s.intervals:
        a, b = iv["start_sample"] / s.fs, iv["end_sample"] / s.fs
        if iv["kind"] == "expected_response":
            trials.append((a, a + BLINK_SPAN_S, iv["label"]))
        elif iv["kind"] == "instructed_hold" or (iv["kind"] == "dot_jump" and iv["label"] in CLASSES):
            trials.append((a, b + HIT_AFTER_END_S, iv["label"]))
            excluded.append((b + HIT_AFTER_END_S, b + HIT_AFTER_END_S + RETURN_SPAN_S))
        elif iv["kind"] == "key_press":                    # ruch od 0,8 s przed do 0,5 s po klawiszu
            trials.append((a, b + KEY_HIT_AFTER_S, iv["label"]))
            if iv["label"] in ("look_left", "look_right"):     # oczy wracaja na srodek
                excluded.append((b + KEY_HIT_AFTER_S, b + KEY_HIT_AFTER_S + RETURN_SPAN_S))
        elif iv["kind"] in ("dot_jump", "dot_sweep"):       # powrot kropki do srodka, wodzenie wzrokiem
            excluded.append((a, b + 1.0))
    return trials, excluded


def stream_metrics(sessions: list, bundles_by_person: dict[str, dict]) -> dict:
    """Symulacja na zywo: bundles_by_person[osoba] = model uczony bez tej osoby.
    per_class: hit_rate = proby, w ktorych zgloszono wlasciwy gest; wrong = zgloszono tylko inny gest.
    false_per_min: zgloszenia poza probami (miedzy probami osoba odpoczywa, ale moze mrugnac lub sie poprawic)."""
    per = {c: {"n": 0, "hit": 0, "wrong": 0} for c in CLASSES if c != "rest"}
    false_by: dict[str, int] = {}
    wrong_by: dict[str, dict[str, int]] = {}
    outside_s = 0.0
    for s in sessions:
        if s.person not in bundles_by_person:
            continue
        events = stream_events(s, bundles_by_person[s.person])
        trials, excluded = session_spans(s)
        for a, b, label in trials:
            got = [e for t, e, _ in events if a <= t < b]
            per[label]["n"] += 1
            if label in got:
                per[label]["hit"] += 1
            elif got:
                per[label]["wrong"] += 1
                w = wrong_by.setdefault(label, {})
                w[got[0]] = w.get(got[0], 0) + 1
        spans = sorted([(a, b) for a, b, _ in trials] + excluded)
        t, dur = STREAM_WARMUP_S, s.n / s.fs
        for a, b in spans:                       # czas poza probami i powrotami
            outside_s += max(0.0, min(a, dur) - t)
            t = max(t, b)
        outside_s += max(0.0, dur - t)
        for t, e, _ in events:
            if t >= STREAM_WARMUP_S and not any(a <= t < b for a, b in spans):
                false_by[e] = false_by.get(e, 0) + 1
    minutes = outside_s / 60.0
    n_false = sum(false_by.values())
    return {
        "per_class": {c: {"n": v["n"], "hit_rate": _ratio(v["hit"], v["n"]), "wrong_rate": _ratio(v["wrong"], v["n"])}
                      for c, v in per.items()},
        "hit_rate": _ratio(sum(v["hit"] for v in per.values()), sum(v["n"] for v in per.values())),
        "wrong_gesture": wrong_by,
        "false_per_min": round(n_false / minutes, 2) if minutes > 0 else None,
        "false_by_label": dict(sorted(false_by.items())),
        "minutes_outside_trials": round(minutes, 1),
    }


def loso_bundles(W: Windows) -> dict[str, dict]:
    """{osoba: model uczony bez niej, z progami dobranymi tez bez niej}."""
    return {str(p): gm.train(W[W.person != p]) for p in np.unique(W.person)}
