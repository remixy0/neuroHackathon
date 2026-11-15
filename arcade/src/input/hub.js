// Wejście w przeglądarce. Wszystkie źródła (klawiatura, gamepad, serwer WebSocket)
// sprowadzamy do jednego wirtualnego pada na gracza: up, down, left, right, a, b, x, start, select.
// Gry dostają tylko zbocza: { player, button, down: true|false } oraz pozycję analogową { player, pos }.
import { parse, BUTTONS, TAP_MS, HOLD_TIMEOUT } from './protocol.js';

const KEYMAP = {
  // gracz 1
  KeyW: [1, 'up'], KeyS: [1, 'down'], KeyA: [1, 'left'], KeyD: [1, 'right'],
  Space: [1, 'a'], KeyE: [1, 'a'], KeyQ: [1, 'b'], ShiftLeft: [1, 'x'], KeyR: [1, 'x'],
  // gracz 2
  ArrowUp: [2, 'up'], ArrowDown: [2, 'down'], ArrowLeft: [2, 'left'], ArrowRight: [2, 'right'],
  Enter: [2, 'a'], NumpadEnter: [2, 'a'], Numpad0: [2, 'a'],
  Slash: [2, 'b'], ControlRight: [2, 'b'], ShiftRight: [2, 'x'], Period: [2, 'x'],
  // systemowe
  KeyP: [1, 'start'], Escape: [1, 'select'], Backspace: [1, 'select'],
};
const MODIFIER_KEYS = new Set(['ControlRight', 'ShiftLeft', 'ShiftRight']);

const RELAY_PORT = 8787;

function relayUrl() {
  const q = new URLSearchParams(window.location.search);
  const v = q.get('ws');
  if (v === 'off') return null;
  const base = v ? (/^wss?:\/\//.test(v) ? v : `ws://${v}`) : `ws://${window.location.hostname || 'localhost'}:${RELAY_PORT}`;
  try {
    const url = new URL(base);
    url.searchParams.set('role', 'game');
    return url.toString();
  } catch {
    return null;
  }
}

class InputHub {
  constructor() {
    this.held = { 1: new Map(), 2: new Map() }; // button → Map(źródło → czas wygaśnięcia)
    this.pos = { 1: null, 2: null };
    this.listeners = new Set();
    this.statusListeners = new Set();
    this.status = { connected: false, pads: {}, gamepads: 0 };
    this.ws = null;
    this.gpPrev = {};
  }

  // ---------- subskrypcje ----------
  on(fn) { this.listeners.add(fn); return () => this.listeners.delete(fn); }
  onStatus(fn) { this.statusListeners.add(fn); return () => this.statusListeners.delete(fn); }
  setStatus(patch) {
    this.status = { ...this.status, ...patch };
    for (const fn of this.statusListeners) fn(this.status);
  }
  emit(ev) { for (const fn of this.listeners) { try { fn(ev); } catch (e) { console.error(e); } } }

  isDown(player, button) { return (this.held[player]?.get(button)?.size || 0) > 0; }

  set(player, button, source, down, expires = Infinity) {
    const map = this.held[player];
    if (!map || !BUTTONS.includes(button)) return;
    const m = map.get(button) || new Map();
    const was = m.size > 0;
    if (down) m.set(source, expires); else m.delete(source);
    map.set(button, m);
    const now = m.size > 0;
    if (down && (button === 'up' || button === 'down')) this.pos[player] = null;
    if (was !== now) this.emit({ player, button, down: now, source });
  }

  clearSources(test, only) {
    for (const pl of only ? [only] : [1, 2]) {
      for (const [button, m] of this.held[pl]) {
        for (const src of [...m.keys()]) if (test(src)) this.set(pl, button, src, false);
      }
    }
  }

  /** Zdarzenie w formacie protokołu (z serwera). */
  feed(ev, source) {
    if (ev.pos !== undefined) {
      this.pos[ev.player] = ev.pos;
      this.emit({ player: ev.player, pos: ev.pos, source });
      return;
    }
    const now = performance.now();
    if (ev.button === 'all') {
      this.clearSources((src) => src.startsWith(source), ev.player);
      return;
    }
    if (ev.state === 'up') {
      this.set(ev.player, ev.button, source, false);
    } else if (ev.state === 'down') {
      // przycisk bez "up" puszcza się sam po 5 s (zgubiony pakiet) – trzymając, ponawiaj "down"
      this.set(ev.player, ev.button, source, true, now + HOLD_TIMEOUT);
    } else {
      this.set(ev.player, ev.button, source + ':tap', true, now + (ev.ms || TAP_MS));
    }
  }

  // ---------- klawiatura ----------
  /** Gra może mieć własny układ klawiszy (np. Tetris). null = układ domyślny. */
  setKeymap(map) {
    if ((map || null) === (this.keymap || null)) return;
    this.clearSources((s) => s.startsWith('kb:'));
    this.keymap = map || null;
  }

  attachKeyboard() {
    window.addEventListener('keydown', (e) => {
      const k = (this.keymap || KEYMAP)[e.code];
      if (!k) return;
      if ((e.ctrlKey || e.metaKey || e.altKey) && !MODIFIER_KEYS.has(e.code)) return;
      e.preventDefault();
      if (!e.repeat) this.set(k[0], k[1], 'kb:' + e.code, true);
    });
    window.addEventListener('keyup', (e) => {
      const k = (this.keymap || KEYMAP)[e.code];
      if (k) this.set(k[0], k[1], 'kb:' + e.code, false);
    });
    window.addEventListener('blur', () => this.clearSources((s) => s.startsWith('kb:') || s.startsWith('gp')));
  }

  // ---------- gamepady: pad 1 → gracz 1, pad 2 → gracz 2 ----------
  pollGamepads() {
    const list = navigator.getGamepads ? navigator.getGamepads() : [];
    let n = 0;
    for (const gp of list) {
      if (!gp || !gp.connected) continue;
      n++;
      if (n > 2) continue;
      const b = (i) => !!gp.buttons[i]?.pressed;
      const ax = gp.axes[0] || 0;
      const ay = gp.axes[1] || 0;
      const cur = {
        up: b(12) || ay < -0.5,
        down: b(13) || ay > 0.5,
        left: b(14) || ax < -0.5,
        right: b(15) || ax > 0.5,
        a: b(0),
        b: b(1),
        x: b(2) || b(3) || b(4) || b(5),
        select: b(8),
        start: b(9),
      };
      const prev = this.gpPrev[gp.index] || {};
      for (const [button, down] of Object.entries(cur)) {
        if (down !== !!prev[button]) this.set(n, button, 'gp' + gp.index, down);
      }
      this.gpPrev[gp.index] = cur;
    }
    if (n !== this.status.gamepads) this.setStatus({ gamepads: n });
  }

  tick() {
    const now = performance.now();
    for (const pl of [1, 2]) {
      for (const [button, m] of this.held[pl]) {
        for (const [src, exp] of m) if (exp <= now) this.set(pl, button, src, false);
      }
    }
    this.pollGamepads();
  }

  // ---------- serwer (WebSocket) ----------
  connect(url) {
    if (!url) return;
    let delay = 1000;
    const open = () => {
      let ws;
      try { ws = new WebSocket(url); } catch { setTimeout(open, delay); return; }
      this.ws = ws;
      ws.onopen = () => { delay = 1000; this.setStatus({ connected: true }); };
      ws.onmessage = (e) => {
        if (typeof e.data !== 'string') return;
        if (e.data.startsWith('{"type":"relay"')) {
          try {
            const info = JSON.parse(e.data);
            this.setStatus({ connected: true, pads: info.pads || {} });
          } catch { /* ignore */ }
          return;
        }
        for (const ev of parse(e.data)) this.feed(ev, 'net');
      };
      ws.onclose = () => {
        if (this.ws === ws) this.ws = null;
        this.clearSources((s) => s.startsWith('net'));
        this.setStatus({ connected: false, pads: {} });
        setTimeout(open, delay);
        delay = Math.min(delay * 2, 10000);
      };
    };
    open();
  }

  /** Gra → serwer → pady (wynik na telefonie, wyświetlacze, LED-y). */
  send(obj) {
    if (this.ws && this.ws.readyState === 1) this.ws.send(JSON.stringify(obj));
  }

  /** Zdarzenie gry → serwer → klienci WebSocket (np. "SCORE 3 5", "P1 LINES 4", "WIN 1"). */
  event(line) {
    this.send({ type: 'event', event: line });
  }

  start() {
    if (this.started) return;
    this.started = true;
    this.attachKeyboard();
    this.connect(relayUrl());
    const loop = () => { this.tick(); requestAnimationFrame(loop); };
    requestAnimationFrame(loop);
  }
}

export const input = new InputHub();
