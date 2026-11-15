#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ARCADE – test wspólnego API sterowania. Uruchom grę (npm run dev), otwórz ją w przeglądarce, potem:

    python examples/test_api.py
    python examples/test_api.py --server http://192.168.1.100:8787

Skrypt: sprawdza połączenie, przechodzi menu (wybiera Ponga i startuje grę),
rusza paletkami przez HTTP (down/up, tap, pozycja analogowa) i przez UDP, na końcu pokazuje stan gry.
Tylko biblioteka standardowa.
"""
import argparse
import json
import socket
import time
import urllib.parse
import urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("--server", default="http://localhost:8787")
ap.add_argument("--udp", type=int, default=8788)
args = ap.parse_args()
BASE = args.server.rstrip("/")


def press(player, button, state="tap", **extra):
    params = {"player": player, "button": button, "state": state, **extra}
    url = BASE + "/api/input?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(urllib.request.Request(url, method="POST"), timeout=2) as r:
        return json.loads(r.read().decode("utf-8"))


def udp(line):
    host = urllib.parse.urlparse(BASE).hostname
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(1)
    s.sendto(line.encode(), (host, args.udp))
    try:
        return s.recvfrom(100)[0].decode().strip()
    except socket.timeout:
        return "(no reply)"
    finally:
        s.close()


print("1) Connection...")
info = json.loads(urllib.request.urlopen(BASE + "/api", timeout=2).read().decode("utf-8"))
print("   OK, games open in a browser:", info["game_clients"])
if not info["game_clients"]:
    print("   Open the game first – otherwise nothing will happen on screen.")

print("2) Main menu: down (PONG), A (open), start (play)")
press(1, "down"); time.sleep(0.2)
press(1, "a"); time.sleep(0.3)
press(1, "start"); time.sleep(0.4)  # na ekranie ustawień START od razu uruchamia grę

print("3) Player 1: hold UP for 0.4 s, then DOWN for 0.4 s")
press(1, "up", "down"); time.sleep(0.4); press(1, "up", "up")
press(1, "down", "down"); time.sleep(0.4); press(1, "down", "up")

print("4) Player 1: 5 short taps up")
for _ in range(5):
    press(1, "up", "tap", ms=100)
    time.sleep(0.15)

print("5) Player 1: analog position (like a potentiometer) 0 -> 1 -> 0.5")
for i in range(41):
    pos = i / 20 if i <= 20 else 1 - (i - 20) / 40
    urllib.request.urlopen(BASE + f"/api/input?player=1&pos={pos:.3f}", timeout=2).read()
    time.sleep(0.03)

print("6) UDP:", udp("P1 UP TAP 300"))
time.sleep(0.4)
print("   UDP:", udp("P1 DOWN TAP 300"))

time.sleep(0.6)
state = json.loads(urllib.request.urlopen(BASE + "/api/state", timeout=2).read().decode("utf-8"))
print("7) Game state:", json.dumps(state["state"], ensure_ascii=False))
print("Done.")
