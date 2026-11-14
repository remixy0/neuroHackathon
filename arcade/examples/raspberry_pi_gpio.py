#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ARCADE – przyciski na Raspberry Pi (GPIO) -> wspólne API sterowania.

Podłączenie: przycisk między pinem GPIO a GND (wewnętrzny pull-up).
    gracz 1: GPIO17 UP  GPIO27 DOWN  GPIO22 LEFT  GPIO23 RIGHT  GPIO24 A  GPIO25 B
    gracz 2: GPIO5  UP  GPIO6  DOWN  GPIO13 LEFT  GPIO19 RIGHT  GPIO26 A  GPIO16 B
    GPIO20 START   GPIO21 SELECT

Uruchom:
    python3 raspberry_pi_gpio.py --server http://192.168.1.100:8787
(gdy gra działa na tym samym Raspberry Pi: --server http://localhost:8787)

Wymaga: gpiozero (jest domyślnie w Raspberry Pi OS).
"""
import argparse
import queue
import signal
import threading
import time
import urllib.parse
import urllib.request

from gpiozero import Button

PINS = {
    17: (1, "up"), 27: (1, "down"), 22: (1, "left"), 23: (1, "right"), 24: (1, "a"), 25: (1, "b"),
    5: (2, "up"), 6: (2, "down"), 13: (2, "left"), 19: (2, "right"), 26: (2, "a"), 16: (2, "b"),
    20: (1, "start"), 21: (1, "select"),
}

ap = argparse.ArgumentParser()
ap.add_argument("--server", default="http://localhost:8787", help="game server address")
args = ap.parse_args()
SERVER = args.server.rstrip("/")

outbox = queue.Queue()


def sender():
    """Wysyła w osobnym wątku – obsługa GPIO nigdy nie czeka na sieć."""
    while True:
        player, button, state = outbox.get()
        url = SERVER + "/api/input?" + urllib.parse.urlencode({"player": player, "button": button, "state": state})
        try:
            urllib.request.urlopen(urllib.request.Request(url, method="POST"), timeout=1).read()
        except Exception as e:  # noqa
            print("Send error:", e)


threading.Thread(target=sender, daemon=True).start()

buttons = []
for pin, (player, name) in PINS.items():
    b = Button(pin, pull_up=True, bounce_time=0.01)
    b.when_pressed = lambda p=player, n=name: outbox.put((p, n, "down"))
    b.when_released = lambda p=player, n=name: outbox.put((p, n, "up"))
    buttons.append((b, player, name))


def keepalive():
    """Gra puszcza przycisk po 5 s bez sygnału – trzymane przyciski odświeżamy co 1 s."""
    while True:
        time.sleep(1.0)
        for b, player, name in buttons:
            if b.is_pressed:
                outbox.put((player, name, "down"))


threading.Thread(target=keepalive, daemon=True).start()
print("Controller running – server:", SERVER, "(Ctrl+C to stop)")
signal.pause()
