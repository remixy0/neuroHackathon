"""Polecenia głosem z komputera, na którym działa serwer (kalibracja): `say` z macOS, głos Zosia.

Bez głosu Zosia mówi głos domyślny; bez `say` (Windows, Linux) nic nie słychać - kroki widać na stronie.
say() nie czeka na koniec wypowiedzi; nowe polecenie przerywa poprzednie (kroki kalibracji mają stały czas).
"""
from __future__ import annotations

import logging
import shutil
import subprocess

log = logging.getLogger("halo.voice")

VOICE = "Zosia"


def _list_voices(exe: str) -> str:
    return subprocess.run([exe, "-v", "?"], capture_output=True, text=True, timeout=5).stdout


class Voice:
    def __init__(self, which=shutil.which, popen=subprocess.Popen, voices=_list_voices):
        self.exe = which("say")
        self.available = bool(self.exe)
        self._popen = popen
        self._proc = None
        self.voice: str | None = None
        if self.available:
            try:
                names = {line.split()[0] for line in voices(self.exe).splitlines() if line.strip()}
                self.voice = VOICE if VOICE in names else None
            except (OSError, subprocess.SubprocessError):
                self.voice = None

    def say(self, text: str) -> None:
        if not self.available:
            return
        self.stop()
        cmd = [self.exe, "-v", self.voice, text] if self.voice else [self.exe, text]
        try:
            self._proc = self._popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
        except OSError as e:
            log.warning("Głos wyłączony: %s", e)
            self.available = False

    def stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass
