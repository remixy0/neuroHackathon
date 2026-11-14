"""Silnik aplikacji macOS: laczy sie z czepkiem BrainAccess przez Bluetooth (albo odtwarza nagranie)
i wypisuje rozpoznania jako linie JSON. Sterowanie: linie JSON na stdin.

Polecenia:  {"cmd":"scan"}  {"cmd":"connect","name":"BA HALO 208"}  {"cmd":"demo","path":"plik.db"}
            {"cmd":"disconnect"}  {"cmd":"quit"}  {"cmd":"person","name":"Ania"}
            sesja treningowa (ekran Trening, zapis do training/sessions/, patrz session_recorder.py):
            {"cmd":"session_start","mode":"blink","person":"Ania","unix_time":...,"protocol":{...},"instructions":"..."}
            {"cmd":"session_event","unix_time":...,"event":"cue","label":"blink","trial":3,"details":{...}}
            {"cmd":"session_stop","unix_time":...,"status":"complete"}
Zdarzenia:  ready, model, status, devices, battery, prediction, signal, gesture, position, session, sessions_state
"""
from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
from pathlib import Path

import joblib
import numpy as np

import session_recorder
from gestures import model as gm
from gestures.live import LiveRecognizer
from neuro import appdata
from neuro.model import FAMILY_PL, LABELS_PL, family
from neuro.position import person_eye_calibration
from neuro import emotion
from neuro.recording import load_recording
from session_recorder import PRE_ROLL_S, SessionRecorder

HERE = Path(__file__).resolve().parent
# kolejnosc elektrod HALO (indeksy 0-3) - taka jak w nagraniach z BrainAccess Board
ELECTRODES = os.environ.get("BA_ELECTRODES", "O1,O2,Fp2,Fp1").split(",")
PLOT_DECIM = 5
ALLOW_DEMO_TRAIN = os.environ.get("BRAINGESTURES_ALLOW_DEMO_TRAIN") == "1"
# model gestow z gestures/ (train_gestures.py); dawny model neuro/ (models/model.joblib) nie jest juz uzywany
MODEL_PATH = Path(os.environ.get("BRAINGESTURES_MODEL", gm.DEFAULT_PATH))
RAW_KEEP_S = 16.0      # ile sekund surowego sygnalu trzymamy w pamieci
POSITION_EVERY_S = 0.1  # co ile wysylamy analogowa pozycje glowy i oczu
EMO_MAX_S = 15 * 60     # najdluzsza proba emocji (zabezpieczenie pamieci)
# sesje treningowe (ekran Trening): ciagly zapis surowego sygnalu i bodzcow do training/sessions/
# (session_recorder.py). Dane z czasow pojedynczych prob (samples.jsonl) sa w archiwum.
SESSION_ROOT = appdata.DIR
SESSION_MAX_S = 30 * 60   # zabezpieczenie: najdluzsza sesja


# ---------------------------------------------------------------- model

def model_state() -> dict:
    """Czy jest model gestow do rozpoznawania. 14.11.2026 dane i model poszly do archiwum (start od zera):
    do czasu wytrenowania nowego modelu z sesji treningowych rozpoznawanie jest wylaczone."""
    try:
        b = joblib.load(MODEL_PATH)
    except FileNotFoundError:
        return {"state": "none", "message": "Brak modelu - rozpoznawanie wylaczone. Zbieraj dane w trybach treningu."}
    except Exception as e:  # noqa: BLE001
        return {"state": "error", "message": f"Nie mozna wczytac modelu: {e}"}
    if not gm.is_current(b):
        return {"state": "none", "message": "Model z innej wersji - rozpoznawanie wylaczone."}
    return {"state": "ready", "samples": int(b.get("n_windows", 0))}


events: "queue.Queue[tuple]" = queue.Queue()
_out_lock = threading.Lock()
LOG_DIR = Path.home() / "Library" / "Logs" / "BrainGestures"
LOG_DIR.mkdir(parents=True, exist_ok=True)
_log = open(LOG_DIR / "engine.log", "a", buffering=1)
SLOT = os.environ.get("BRAINGESTURES_SLOT", "1")  # numer gniazda czepka w aplikacji (1, 2, ...)


def log(msg: str):
    _log.write(time.strftime("%H:%M:%S ") + f"[czepek {SLOT}] " + msg + "\n")


def emit(kind: str, **data):
    with _out_lock:
        sys.stdout.write(json.dumps({"type": kind, **data}, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def status(state: str, message: str = "", **extra):
    log(f"status {state} {message}")
    emit("status", state=state, message=message, **extra)


# ---------------------------------------------------------------- zrodla danych

class DemoSource:
    """Odtwarza nagranie .db w tempie rzeczywistym."""

    def __init__(self, sid: int, path: str, wal: str | None):
        self.sid, self.path, self.wal = sid, path, wal
        self.stop_flag = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def _run(self):
        try:
            rec = load_recording(self.path, self.wal)
        except Exception as e:  # noqa: BLE001
            events.put(("failed", self.sid, f"Nie mozna wczytac nagrania: {e}"))
            return
        events.put(("started", self.sid, rec.channels, rec.fs, f"Demo: {Path(self.path).name}"))
        chunk, t0 = 25, time.time()
        for n, i in enumerate(range(0, rec.data.shape[1], chunk)):
            if self.stop_flag.is_set():
                return
            events.put(("chunk", self.sid, rec.data[:, i:i + chunk], time.time()))
            delay = t0 + (n + 1) * chunk / rec.fs - time.time()
            if delay > 0:
                time.sleep(delay)
        events.put(("ended", self.sid, "Koniec nagrania."))

    def stop(self):
        self.stop_flag.set()

    def battery(self):
        return None


class DeviceSource:
    """Czepek BrainAccess przez Bluetooth (SDK brainaccess)."""

    def __init__(self, sid: int, name: str):
        self.sid, self.name = sid, name
        self.mgr = None
        self.rows: list[int | None] = []
        self.closing = False
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def _run(self):
        try:
            from brainaccess import core
            from brainaccess.core import eeg_channel as ch
            from brainaccess.core.eeg_manager import EEGManager
            from brainaccess.core.gain_mode import GainMode

            ba_init()
            mgr = EEGManager()
            self.mgr = mgr
            last = None
            for _ in range(4):
                try:
                    mgr.connect(self.name)
                    last = None
                    break
                except Exception as e:  # noqa: BLE001  przejsciowe bledy BLE - ponow
                    last = e
                    time.sleep(0.7)
            if last is not None:
                raise last
            feat = mgr.get_device_features()
            n_el = feat.electrode_count()
            if n_el < len(ELECTRODES):
                raise RuntimeError(f"Urzadzenie ma {n_el} elektrod, potrzeba {len(ELECTRODES)}.")
            wanted: list[tuple[str, int | None]] = []
            for e in range(n_el):
                mgr.set_channel_enabled(ch.ELECTRODE_MEASUREMENT + e, e < len(ELECTRODES))
            for e, nm in enumerate(ELECTRODES):
                mgr.set_channel_gain(ch.ELECTRODE_MEASUREMENT + e, GainMode.X8)
                wanted.append((nm, ch.ELECTRODE_MEASUREMENT + e))
            for e, nm in enumerate(ELECTRODES):
                mgr.set_channel_enabled(ch.ELECTRODE_CONTACT + e, True)
                wanted.append(("contact_" + nm, ch.ELECTRODE_CONTACT + e))
            for base, ok, names in ((ch.ACCELEROMETER, feat.has_accel(), ("Accel_x", "Accel_y", "Accel_z")),
                                    (ch.GYROSCOPE, feat.has_gyro(), ("Gyro_x", "Gyro_y", "Gyro_z"))):
                for axis, nm in enumerate(names):
                    if ok:
                        mgr.set_channel_enabled(base + axis, True)
                    wanted.append((nm, base + axis if ok else None))
            try:
                # licznik probek z czepka: w zapisie sesji widac zgubione probki
                mgr.set_channel_enabled(ch.SAMPLE_NUMBER, True)
                wanted.append(("Sample", ch.SAMPLE_NUMBER))
            except Exception:  # noqa: BLE001
                pass
            mgr.set_channel_enabled(ch.STREAMING, True)
            wanted.append(("Streaming", ch.STREAMING))
            mgr.set_sample_rate(250)
            mgr.set_callback_chunk(self._on_chunk)
            mgr.set_callback_disconnect(self._on_disconnect)
            mgr.load_config()
            mgr.start_stream()
            def index(cid):
                try:
                    return mgr.get_channel_index(cid) if cid is not None else None
                except Exception:  # noqa: BLE001
                    return None
            self.rows = [index(cid) for _, cid in wanted]
            fs = float(mgr.get_sample_frequency())
            note = "" if feat.has_gyro() else " (brak zyroskopu - ruchy glowy nie beda rozpoznawane)"
            events.put(("started", self.sid, [nm for nm, _ in wanted], fs, f"Polaczono: {self.name}{note}"))
        except Exception as e:  # noqa: BLE001
            self._teardown()
            events.put(("failed", self.sid, f"Nie udalo sie polaczyc z {self.name}: {e}"))

    def _on_chunk(self, data, n):
        if not self.rows:
            return  # strumien ruszyl, zanim znamy uklad kanalow
        t_arr = time.time()   # chwila przyjscia paczki (do zegara sesji treningowych)
        arr = np.zeros((len(self.rows), n))
        for i, r in enumerate(self.rows):
            if r is not None:
                arr[i] = data[r]
        events.put(("chunk", self.sid, arr, t_arr))

    def _on_disconnect(self, *_):
        if not self.closing:
            events.put(("ended", self.sid, "Utracono polaczenie z czepkiem."))

    def _teardown(self):
        self.closing = True
        mgr, self.mgr = self.mgr, None
        if mgr is None:
            return
        for step in (mgr.stop_stream, mgr.disconnect, mgr.destroy):
            try:
                step()
            except Exception:  # noqa: BLE001
                pass

    def stop(self):
        threading.Thread(target=self._teardown, daemon=True).start()

    def battery(self):
        try:
            return int(self.mgr.get_battery_info().level) if self.mgr else None
        except Exception:  # noqa: BLE001
            return None


_ba_ready = False
_ba_lock = threading.Lock()


def ba_init():
    global _ba_ready
    with _ba_lock:
        if not _ba_ready:
            from brainaccess import core
            logs = LOG_DIR / f"czepek{SLOT}"
            logs.mkdir(parents=True, exist_ok=True)
            os.chdir(logs)  # SDK zapisuje bacore.log w biezacym katalogu
            core.init()
            _ba_ready = True


def scan_devices():
    try:
        from brainaccess import core
        ba_init()
        found = core.scan()
        events.put(("devices", [{"name": d.name, "address": d.mac_address} for d in found], ""))
    except Exception as e:  # noqa: BLE001
        events.put(("devices", [], f"Skanowanie nie powiodlo sie: {e}"))


# ---------------------------------------------------------------- petla glowna

def read_commands():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        log("cmd " + line[:200])
        try:
            events.put(("cmd", json.loads(line)))
        except json.JSONDecodeError:
            emit("status", state="error", message=f"Niezrozumiale polecenie: {line[:80]}")
    log("stdin closed")
    events.put(("cmd", {"cmd": "quit"}))


def main():
    ms = model_state()
    demo_dir = HERE.parent / "resources"
    demos = sorted(str(p) for p in demo_dir.glob("*.db")) if demo_dir.is_dir() else []
    emit("ready", demo_files=demos, electrodes=ELECTRODES, labels=LABELS_PL, families=FAMILY_PL)
    emit("model", **ms)
    status("idle", "Gotowy.")
    threading.Thread(target=read_commands, daemon=True).start()

    sid = 0
    source = None
    source_name = ""
    rec: LiveRecognizer | None = None
    names: list[str] = []
    last_batt = 0.0
    scanning = False
    raw_ring: list[tuple[int, np.ndarray, float]] = []   # (indeks pierwszej probki, kawalek, czas przyjscia unix)
    fs_now = 250.0
    cal_person = ""        # osoba w tym czepku (kalibracja odczytu oczu)
    last_position = 0
    emo: dict | None = None  # trwajaca proba emocji: surowe kawalki od startu do konca wywolania
    session: SessionRecorder | None = None   # trwajaca sesja treningowa (zapis na dysk na biezaco)

    def sessions_state():
        try:
            emit("sessions_state", by_person=session_recorder.summary(SESSION_ROOT))
        except Exception as ex:  # noqa: BLE001
            log(f"podsumowanie sesji: {ex}")

    def emo_state():
        emit("emo_state", by_person=emotion.summary(appdata.DIR))

    def save_emotion(meta: dict, data: np.ndarray, chans: list[str], fs: float):
        try:
            e = emotion.save_trial(appdata.DIR, meta, data, chans, fs)
            clean = sum(w.get("clean", False) for w in e["windows"])
            emit("emo_saved", ok=True, id=e["id"], emotion=meta.get("emotion"), duration=e["duration_s"],
                 windows=len(e["windows"]), clean=clean)
            emo_state()
        except Exception as ex:  # noqa: BLE001
            log(f"zapis emocji: {ex}")
            emit("emo_saved", ok=False, message=f"Nie udalo sie zapisac: {ex}")

    def calibrate_eyes(person: str):
        """W tle: kalibracja oczu z prob spojrzen tej osoby (kierunek i skala)."""
        def run():
            try:
                events.put(("eye_cal", person, person_eye_calibration(person, appdata.DIR)))
            except Exception as e:  # noqa: BLE001
                log(f"kalibracja oczu {person}: {e}")
        threading.Thread(target=run, daemon=True).start()

    def finish_session(how: str):
        nonlocal session
        s, session = session, None
        if s is None:
            return
        try:
            info = s.finish(how)
            log(f"sesja zapisana {info['id']} ({how}, {info['duration_s']} s)")
            emit("session", state="saved", **info)
        except Exception as ex:  # noqa: BLE001
            log(f"zapis sesji: {ex}")
            emit("session", state="error", message=f"Nie udalo sie zapisac sesji: {ex}")
        sessions_state()

    def stop_source(msg: str = "Rozlaczono."):
        nonlocal source, rec, sid, emo
        if session is not None:
            finish_session("interrupted")   # dane do chwili rozlaczenia zostaja (status w session.json)
        if emo is not None:
            emo = None
            emit("emo_saved", ok=False, message="Przerwano - utracono polaczenie.")
        if source is not None:
            source.stop()
        source, rec = None, None
        sid += 1
        status("idle", msg)

    sessions_state()
    emo_state()
    while True:
        try:
            ev = events.get(timeout=1.0)
        except queue.Empty:
            ev = None
        if source is not None and rec is not None and time.time() - last_batt > 20:
            last_batt = time.time()
            level = source.battery()
            if level is not None:
                emit("battery", level=level)
        if ev is None:
            continue
        kind = ev[0]

        if kind == "cmd":
            c = ev[1]
            cmd = c.get("cmd")
            if cmd == "quit":
                if session is not None:
                    finish_session("interrupted")
                if source is not None:
                    source._teardown() if isinstance(source, DeviceSource) else source.stop()
                return
            if cmd == "scan":
                if not scanning:
                    scanning = True
                    emit("status", state="scanning", message="Szukam czepkow BrainAccess (ok. 5 s)...")
                    threading.Thread(target=scan_devices, daemon=True).start()
            elif cmd in ("connect", "demo"):
                if source is not None:
                    stop_source()
                sid += 1
                if cmd == "connect":
                    status("connecting", f"Lacze z {c['name']}...")
                    source = DeviceSource(sid, c["name"])
                    source_name = c["name"]
                else:
                    wal = c.get("wal")
                    if not wal and "urbanek-1" in Path(c["path"]).name:
                        cand = Path(c["path"]).parent / "urbanek zlapany.db-wal"
                        wal = str(cand) if cand.exists() else None
                    status("connecting", "Wczytuje nagranie...")
                    source = DemoSource(sid, c["path"], wal)
                    source_name = "demo: " + Path(c["path"]).name
                source.start()
            elif cmd == "disconnect":
                stop_source()
            elif cmd == "person":
                cal_person = (c.get("name") or "").strip()
                calibrate_eyes(cal_person)
            elif cmd == "sessions_state":
                sessions_state()
            elif cmd == "session_start":
                if rec is None:
                    emit("session", state="error", message="Najpierw polacz czepek.")
                elif isinstance(source, DemoSource) and not ALLOW_DEMO_TRAIN:
                    emit("session", state="error", message="Trening dziala tylko z czepkiem, nie w trybie demo.")
                elif session is not None:
                    emit("session", state="error", message="Trwa inna sesja.")
                else:
                    # rozbieg: ostatnie PRE_ROLL_S sygnalu sprzed startu (filtry, tlo)
                    need, pre = int(PRE_ROLL_S * fs_now), []
                    for _, a, t_arr in reversed(raw_ring):
                        if need <= 0:
                            break
                        pre.insert(0, (a, t_arr))
                        need -= a.shape[1]
                    person = (c.get("person") or cal_person or "osoba").strip()
                    meta = {"mode": c.get("mode"), "person": person, "slot": SLOT, "device": source_name,
                            "demo": isinstance(source, DemoSource), "protocol": c.get("protocol") or {},
                            "instructions": c.get("instructions", ""), "electrode_order_setting": ELECTRODES}
                    try:
                        session = SessionRecorder(SESSION_ROOT, meta, names, fs_now, pre)
                        session.add_event({"unix_time": c.get("unix_time"), "event": "session_start",
                                           "label": c.get("mode"), "details": {"person": person}})
                        log(f"sesja start {session.id}")
                        emit("session", state="recording", id=session.id, path=str(session.dir))
                    except Exception as ex:  # noqa: BLE001
                        session = None
                        log(f"start sesji: {ex}")
                        emit("session", state="error", message=f"Nie udalo sie zaczac zapisu: {ex}")
            elif cmd == "session_event":
                if session is not None:
                    session.add_event(c)
            elif cmd == "session_stop":
                if session is not None:
                    session.add_event({"unix_time": c.get("unix_time"), "event": "session_end",
                                       "details": {"reason": c.get("status") or "complete"}})
                    finish_session(c.get("status") or "complete")
            elif cmd == "emo_state":
                emo_state()
            elif cmd == "emo_start":
                if rec is None:
                    emit("emo_saved", ok=False, message="Najpierw polacz czepek.")
                elif isinstance(source, DemoSource) and not ALLOW_DEMO_TRAIN:
                    emit("emo_saved", ok=False, message="Zbieranie emocji dziala tylko z czepkiem, nie w trybie demo.")
                else:
                    emo = {"meta": {k: c.get(k) for k in ("person", "emotion", "source", "note", "round")},
                           "chunks": [], "n": 0, "phases": [["baseline", 0.0]], "recording": True,
                           "fs": fs_now, "channels": list(names)}
                    emit("emo", state="recording")
            elif cmd == "emo_phase":
                if emo is not None and emo["recording"]:
                    t = round(emo["n"] / emo["fs"], 3)
                    if c.get("phase") == "end":
                        emo["recording"] = False  # ocena osoby nie jest juz czescia nagrania
                        emo["end_s"] = t
                    else:
                        emo["phases"].append([c.get("phase") or "?", t])
            elif cmd == "emo_stop":
                if emo is not None:
                    e, emo = emo, None
                    if c.get("save") and e["chunks"]:
                        data = np.concatenate(e["chunks"], axis=1)
                        meta = {**e["meta"], "ratings": c.get("ratings") or {}, "phases": e["phases"],
                                "end_s": e.get("end_s")}
                        threading.Thread(target=save_emotion, args=(meta, data, e["channels"], e["fs"]),
                                         daemon=True).start()
                    else:
                        emit("emo_saved", ok=False, message="Odrzucono probe.")

        elif kind == "devices":
            scanning = False
            emit("devices", devices=ev[1], error=ev[2])
            if source is None:
                status("idle", ev[2] or (f"Znaleziono: {len(ev[1])}." if ev[1] else
                                         "Nie znaleziono czepka. Wlacz go i sprobuj ponownie."))

        elif kind == "eye_cal":
            if ev[1] == cal_person and rec is not None:
                rec.position.calibrate(ev[2])
            if ev[1] == cal_person:
                emit("eye_calibration", person=ev[1], calibrated=ev[2]["x"] is not None)

        elif kind == "started" and ev[1] == sid:
            _, _, names, fs, msg = ev
            fs_now, raw_ring = fs, []
            try:
                rec = LiveRecognizer(names, fs, MODEL_PATH if model_state()["state"] == "ready" else None)
            except Exception as e:  # noqa: BLE001
                stop_source(f"Blad modelu: {e}")
                continue
            last_position = 0
            if cal_person:
                calibrate_eyes(cal_person)
            last_batt = 0.0
            status("streaming", msg, fs=fs, demo=isinstance(source, DemoSource))

        elif kind == "failed" and ev[1] == sid:
            source = None
            status("error", ev[2])

        elif kind == "ended" and ev[1] == sid:
            stop_source(ev[2])

        elif kind == "chunk" and ev[1] == sid and rec is not None:
            arr, t_arr = ev[2], ev[3]
            raw_ring.append((rec.stream.n_seen, arr, t_arr))
            if session is not None:
                try:
                    session.add_chunk(arr, t_arr)
                    if session.n > SESSION_MAX_S * fs_now:
                        finish_session("too_long")
                except Exception as ex:  # noqa: BLE001
                    log(f"zapis sesji: {ex}")
                    finish_session("error")
            if emo is not None and emo["recording"]:
                emo["chunks"].append(arr)
                emo["n"] += arr.shape[1]
                if emo["n"] > EMO_MAX_S * fs_now:
                    emo["recording"] = False
                    emo["end_s"] = round(emo["n"] / emo["fs"], 3)
            keep_from = rec.stream.n_seen - int(RAW_KEEP_S * fs_now)
            while raw_ring and raw_ring[0][0] + raw_ring[0][1].shape[1] < keep_from:
                raw_ring.pop(0)
            results = rec.push(arr)
            if rec.stream.n_seen - last_position >= int(POSITION_EVERY_S * fs_now):
                last_position = rec.stream.n_seen
                emit("position", t=round(rec.stream.n_seen / fs_now, 2), **rec.position.state)
            for res in results:
                top = sorted(res["probs"].items(), key=lambda kv: -kv[1])[:5]
                emit("prediction", t=res["t"], label=res["label"], label_pl=res["label_pl"],
                     confidence=round(res["confidence"], 3), family=res["family"], family_pl=res["family_pl"],
                     family_confidence=round(res["family_confidence"], 3), families=res["families"],
                     top=[{"label": k, "label_pl": LABELS_PL.get(k, k), "p": v} for k, v in top],
                     warmup=res["t"] < 10)
                if res["event"]:
                    # gest zgloszony przez model (prog klasy, bez powtorzen i ruchow powrotnych glowy)
                    ev_l = res["event"]
                    emit("gesture", start=round(res["t"] - 0.75, 2), end=round(res["t"], 2), key=ev_l,
                         label_pl=LABELS_PL.get(ev_l, ev_l), confidence=round(res["event_confidence"], 3),
                         family_confidence=round(res["families"].get(family(ev_l), 0.0), 3))
            if rec.plot_ready:
                st = rec.stream
                hop = st.hop
                contact = [int(arr[names.index("contact_" + e), -1]) if "contact_" + e in names else 1
                           for e in ELECTRODES]
                lost = float(1 - arr[names.index("Streaming")].mean()) if "Streaming" in names else 0.0
                emit("signal", t=round(st.n_seen / st.fs, 2), dt=PLOT_DECIM / st.fs,
                     eeg={nm: np.round(st.buf["eeg"][i, -hop::PLOT_DECIM], 1).tolist()
                          for i, nm in enumerate(("O1", "O2", "Fp2", "Fp1"))},
                     gyro={a: np.round(st.buf["gyro"][i, -hop::PLOT_DECIM], 1).tolist()
                           for i, a in enumerate("xyz")},
                     contact=dict(zip(ELECTRODES, contact)), lost=round(lost, 3))


if __name__ == "__main__":
    main()
