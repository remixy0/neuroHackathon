// ARCADE INPUT API – wspólny protokół dla wszystkich gier.
// Ten sam plik używa przeglądarka (gra) i serwer (WebSocket, HTTP, UDP).
//
// Każdy gracz (1 lub 2) ma wirtualny pad z przyciskami:
//   up, down, left, right, a, b, x, start, select
// plus opcjonalną oś analogową "pos" (0..1) – np. potencjometr w Pongu.
//
// Komunikat JSON:
//   {"player":1,"button":"left","state":"down"}   wciśnięty
//   {"player":1,"button":"left","state":"up"}     puszczony
//   {"player":1,"button":"a"}                     krótkie naciśnięcie (tap)
//   {"player":2,"pos":0.42}                       pozycja analogowa
// Tekst (jedna komenda w linii):
//   1 left down | P1 LEFT PRESS | 2 a | P2 UP TAP 150 | P1 POS 0.4 | P2 RAW 512 1023 | START
//
// Zgodność wstecz: stare formaty Tetrisa ({"action":"hard"}), Ponga ("P1 UP PRESS",
// {"button":"up","action":"press"}) i Runnera / backendu HALO ({"type":"input","direction":"left","id":7}).

export const BUTTONS = ['up', 'down', 'left', 'right', 'a', 'b', 'x', 'start', 'select'];

const BUTTON_ALIASES = {
  up: 'up', u: 'up', jump: 'up', cw: 'up', rotate: 'up', rot: 'up', rotr: 'up', rotate_cw: 'up', gora: 'up', 'góra': 'up',
  down: 'down', d: 'down', slide: 'down', soft: 'down', softdrop: 'down', soft_drop: 'down', dol: 'down', 'dół': 'down',
  left: 'left', l: 'left', lewo: 'left',
  right: 'right', r: 'right', prawo: 'right',
  a: 'a', hard: 'a', harddrop: 'a', hard_drop: 'a', drop: 'a', fire: 'a', ok: 'a', action: 'a', confirm: 'a',
  b: 'b', ccw: 'b', rotl: 'b', rotate_ccw: 'b', back: 'b', cancel: 'b',
  x: 'x', hold: 'x', y: 'x', c: 'x',
  start: 'start', pause: 'start', pauza: 'start', enter: 'start', start1: 'start', start2: 'start', '1p': 'start', '2p': 'start',
  select: 'select', menu: 'select', esc: 'select', escape: 'select', home: 'select',
  'release-all': 'all', releaseall: 'all', release_all: 'all', all: 'all',
};

const STATES = {
  down: 'down', press: 'down', pressed: 'down', on: 'down', '1': 'down', '+': 'down', true: 'down', hold: 'down',
  up: 'up', release: 'up', released: 'up', off: 'up', '0': 'up', '-': 'up', false: 'up',
  tap: 'tap', click: 'tap', t: 'tap',
};

export const TAP_MS = 120;
export const HOLD_TIMEOUT = 5000;

const clamp01 = (v) => Math.max(0, Math.min(1, v));

export function normButton(v) {
  if (v == null) return null;
  return BUTTON_ALIASES[String(v).trim().toLowerCase()] || null;
}

export function normState(v) {
  if (v == null || v === '') return 'tap';
  return STATES[String(v).trim().toLowerCase()] || null;
}

export function normPlayer(v) {
  if (v == null || v === '') return 1;
  const m = /^(?:p|player|gracz)?\s*([12])$/i.exec(String(v).trim());
  return m ? Number(m[1]) : null;
}

function finish(ev) {
  if (ev.pos !== undefined) return { player: ev.player, pos: ev.pos };
  const out = { player: ev.player, button: ev.button, state: ev.state };
  if (ev.state === 'tap' && Number.isFinite(ev.ms)) out.ms = Math.max(30, Math.min(2000, ev.ms));
  if (ev.id !== undefined) out.id = ev.id;
  return out;
}

/** Obiekt (JSON, parametry HTTP) → zdarzenie albo null. */
export function fromObject(o) {
  if (!o || typeof o !== 'object') return null;
  if (o.type !== undefined && o.type !== 'input') return null; // komunikaty serwisowe (state, relay…)
  const player = normPlayer(o.player ?? o.p);
  if (!player) return null;

  // pozycja analogowa
  const posRaw = o.pos ?? o.position ?? o.value;
  if (posRaw !== undefined && o.button === undefined && o.b === undefined) {
    let v = parseFloat(posRaw);
    if (!Number.isFinite(v)) return null;
    if (o.invert === true || o.invert === '1' || o.invert === 1) v = 1 - v;
    return finish({ player, pos: clamp01(v) });
  }
  if (o.raw !== undefined) {
    let v = parseFloat(o.raw) / (parseFloat(o.max) || 1023);
    if (!Number.isFinite(v)) return null;
    if (o.invert === true || o.invert === '1' || o.invert === 1) v = 1 - v;
    return finish({ player, pos: clamp01(v) });
  }

  // "button"/"direction" = przycisk, wtedy "action" znaczy stan (format Ponga).
  // Bez nich "action" = przycisk (format Tetrisa).
  const named = o.button ?? o.b ?? o.direction ?? o.key;
  const button = normButton(named ?? o.action ?? o.a);
  if (!button) return null;
  const state = normState(o.state ?? o.s ?? (named !== undefined ? o.action ?? o.a : undefined));
  if (!state) return null;
  const ev = { player, button, state, ms: Number(o.ms) };
  if (o.id !== undefined) ev.id = o.id;
  if (button === 'all') ev.state = 'up';
  return finish(ev);
}

/** Linia tekstu → zdarzenie albo null. */
export function fromText(line) {
  const t = String(line).trim().split(/[\s,;:=]+/).filter(Boolean);
  if (!t.length) return null;
  let i = 0;
  let player = 1;
  const pm = /^(?:p|player|gracz)?([12])$/i.exec(t[0]);
  if (pm) { player = Number(pm[1]); i = 1; }
  const word = (t[i] || '').toLowerCase();
  if (!word) return null;
  if (word === 'pos' || word === 'raw') {
    let v = parseFloat(t[i + 1]);
    if (!Number.isFinite(v)) return null;
    if (word === 'raw') v /= parseFloat(t[i + 2]) || 1023;
    return finish({ player, pos: clamp01(v) });
  }
  const button = normButton(word);
  if (!button) return null;
  const state = normState(t[i + 1]);
  if (!state) return null;
  return finish({ player, button: button, state: button === 'all' ? 'up' : state, ms: parseInt(t[i + 2], 10) });
}

/** Dowolna wiadomość (tekst, JSON, tablica JSON, kilka linii) → lista zdarzeń. */
export function parse(raw) {
  if (raw == null) return [];
  if (typeof raw === 'object') {
    if (Array.isArray(raw)) return raw.flatMap((r) => parse(r));
    const ev = fromObject(raw);
    return ev ? [ev] : [];
  }
  const text = String(raw).trim();
  if (!text) return [];
  if (text[0] === '{' || text[0] === '[') {
    try { return parse(JSON.parse(text)); } catch { return []; }
  }
  return text.split(/\r?\n/).map(fromText).filter(Boolean);
}

/** Pamięć ostatnich identyfikatorów – ten sam (player, id) wykonuje się tylko raz. */
export function createDeduper(limit = 1000) {
  const seen = new Set();
  return (ev) => {
    if (ev.id === undefined) return true;
    const key = JSON.stringify([ev.player, ev.id]);
    if (seen.has(key)) return false;
    seen.add(key);
    if (seen.size > limit) seen.delete(seen.values().next().value);
    return true;
  };
}
