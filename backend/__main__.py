"""Uruchomienie: backend/.venv/bin/python -m backend [--port 8000] [--settings backend/settings.json]"""
from __future__ import annotations

import argparse
import logging
import os

import uvicorn

from .app import DEFAULT_SETTINGS, HERE, create_app, lan_ips
from .voice import Voice


def main() -> None:
    ap = argparse.ArgumentParser(description="Serwer HALO -> Arcade (gesty EEG)")
    ap.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    ap.add_argument("--settings", default=os.environ.get("HALO_SETTINGS", str(DEFAULT_SETTINGS)))
    ap.add_argument("--recordings", default=os.environ.get("HALO_RECORDINGS", str(HERE / "recordings")),
                    help="katalog na zapis sesji EEG (ustawienie 'record' włącza i wyłącza zapis)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    app = create_app(args.settings, token=os.environ.get("HALO_TOKEN") or None, voice=Voice(),
                     recordings_dir=args.recordings)
    print(f"\n  Ustawienia:  http://localhost:{args.port}/")
    for ip in lan_ips():
        print(f"  Telefon:     ws://{ip}:{args.port}/ws/controller   (strona: http://{ip}:{args.port}/)")
    print()
    # ping co 5 s, limit 10 s: wykrywa martwe połączenia (także w trybie manual bez naciśnięć)
    uvicorn.run(app, host=args.host, port=args.port, ws_ping_interval=5, ws_ping_timeout=10,
                ws_max_size=2 * 2 ** 20, log_level="warning")


if __name__ == "__main__":
    main()
