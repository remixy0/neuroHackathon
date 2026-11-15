"""Polecenia głosem: `say` z macOS, głos Zosia; bez `say` albo bez głosu kalibracja idzie dalej."""
from backend.voice import Voice


class FakeProc:
    def __init__(self, cmd):
        self.cmd, self.running, self.terminated = cmd, True, False

    def poll(self):
        return None if self.running else 0

    def terminate(self):
        self.terminated, self.running = True, False


class Runner:
    def __init__(self):
        self.procs: list[FakeProc] = []

    def __call__(self, cmd, **kw):
        self.procs.append(FakeProc(cmd))
        return self.procs[-1]


VOICES = "Alice               it_IT    # Ciao!\nZosia               pl_PL    # Witaj, nazywam się Zosia.\n"


def test_voice_uses_zosia():
    run = Runner()
    v = Voice(which=lambda name: "/usr/bin/say", popen=run, voices=lambda exe: VOICES)
    assert v.available is True
    v.say("Głowa w lewo.")
    assert run.procs[0].cmd == ["/usr/bin/say", "-v", "Zosia", "Głowa w lewo."]


def test_voice_falls_back_to_default_voice():
    run = Runner()
    v = Voice(which=lambda name: "/usr/bin/say", popen=run, voices=lambda exe: "Alice   it_IT  # Ciao!\n")
    v.say("Mrugnij.")
    assert run.procs[0].cmd == ["/usr/bin/say", "Mrugnij."]


def test_voice_without_say_is_silent():
    run = Runner()
    v = Voice(which=lambda name: None, popen=run, voices=lambda exe: VOICES)
    assert v.available is False
    v.say("Mrugnij.")
    v.stop()
    assert run.procs == []


def test_voice_interrupts_previous():
    run = Runner()
    v = Voice(which=lambda name: "/usr/bin/say", popen=run, voices=lambda exe: VOICES)
    v.say("Kalibracja. Usiądź spokojnie i patrz przed siebie.")
    v.say("Głowa w lewo.")
    assert run.procs[0].terminated is True and run.procs[1].terminated is False
    run.procs[1].running = False            # skończyła mówić sama
    v.say("Głowa w prawo.")
    assert run.procs[1].terminated is False
    v.stop()
    assert run.procs[2].terminated is True


def test_voice_survives_spawn_error():
    def boom(cmd, **kw):
        raise OSError("no audio")
    v = Voice(which=lambda name: "/usr/bin/say", popen=boom, voices=lambda exe: VOICES)
    v.say("Mrugnij.")                        # bez wyjątku
    assert v.available is False


def test_voice_list_error_means_default_voice():
    def voices(exe):
        raise OSError("timeout")
    run = Runner()
    v = Voice(which=lambda name: "/usr/bin/say", popen=run, voices=voices)
    v.say("Mrugnij.")
    assert run.procs[0].cmd == ["/usr/bin/say", "Mrugnij."]
