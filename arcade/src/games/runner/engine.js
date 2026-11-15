// RUNNER – logika biegu (bez DOM i bez Three.js).
// Trzy pasy, przeszkody: block (zmień pas), barrier (skok), gate (ślizg), monety.
// Wynik = dystans × 10 + monety × 25. Po trafieniu 1,8 s nietykalności.
import { sfx } from '../../lib/sound.js';
import { saveRecord } from '../../lib/records.js';

export const LANE_WIDTH = 2.4;
const ACTION_TIME = 0.95;

export function rng(seed) {
  return () => {
    seed |= 0; seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Tor w stylu Subway Surfers – rzędy przeszkód z wzorców:
//   single  – jedna przeszkoda, można ominąć
//   trains  – długie pociągi na dwóch pasach: trzeba być na trzecim
//   jump    – płotki na wszystkich pasach: trzeba skoczyć
//   slide   – belki na wszystkich pasach: trzeba się wślizgnąć
//   mixed   – pociąg + płotek + belka: zmień pas albo skocz / wślizgnij się
//   zigzag  – kilka krótkich rzędów pociągów, wolny pas skacze na boki
// Im dalej, tym gęściej i trudniej. Odstępy dobrane tak, żeby zawsze dało się przejść:
// po rzędzie wymagającym skoku/ślizgu jest czas na kolejną akcję.
const LANES = [-1, 0, 1];
const BASE_WEIGHTS = (level) => ({
  single: 3 - 2.4 * level,
  trains: 1.6 + 0.6 * level,
  jump: 1 + 1.4 * level,
  slide: 1 + 1.4 * level,
  mixed: 0.4 + 1.8 * level,
  zigzag: level > 0.15 ? 0.4 + 1.6 * level : 0,
});
const FORCED = new Set(['jump', 'slide', 'mixed']);

function pickWeighted(random, weights) {
  const entries = Object.entries(weights).filter(([, w]) => w > 0);
  let r = random() * entries.reduce((a, [, w]) => a + w, 0);
  for (const [k, w] of entries) { r -= w; if (r <= 0) return k; }
  return entries[entries.length - 1][0];
}

export function createTrack(seed, length = 3200) {
  const random = rng(seed);
  const items = [];
  const lane = () => LANES[Math.floor(random() * 3)];
  const others = (l) => LANES.filter((x) => x !== l);
  const shuffle = (a) => { for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };
  const coins = (l, z0, n) => { for (let j = 0; j < n; j++) items.push({ z: z0 + j * 2, lane: l, type: 'coin' }); };
  const train = (l, z, len) => items.push({ z, lane: l, type: 'block', len });

  let z = 35;           // początek następnego rzędu
  let lastForced = false;
  let free = 0;         // wolny pas poprzedniego rzędu
  while (z < length) {
    const level = Math.min(1, z / 1500);
    const actionGap = 17 + z / 300; // czas na wylądowanie i kolejną akcję nawet przy pełnej prędkości
    const laneGap = 11 + z / 400;
    const kind = pickWeighted(random, BASE_WEIGHTS(level));
    const forced = FORCED.has(kind);
    if (forced && !lastForced) z += actionGap - laneGap; // przed wymuszonym skokiem/ślizgiem trochę więcej miejsca
    let end = z;

    if (kind === 'single') {
      const l = lane();
      const type = ['block', 'barrier', 'gate'][Math.floor(random() * 3)];
      if (type === 'block') { train(l, z, 4); end = z + 4; } else items.push({ z, lane: l, type });
      free = others(l)[Math.floor(random() * 2)];
      coins(free, z, 4);
    } else if (kind === 'trains') {
      free = lane();
      const len = Math.round(6 + random() * 14 * (0.4 + level));
      for (const l of others(free)) train(l, z, len + Math.round(random() * 4));
      coins(free, z, Math.min(8, Math.floor(len / 2)));
      end = z + len + 4;
    } else if (kind === 'jump' || kind === 'slide') {
      for (const l of LANES) items.push({ z, lane: l, type: kind === 'jump' ? 'barrier' : 'gate' });
      free = lane();
      coins(free, z + 4, 3);
    } else if (kind === 'mixed') {
      const types = shuffle(['block', 'barrier', 'gate']);
      LANES.forEach((l, i) => (types[i] === 'block' ? train(l, z, 4) : items.push({ z, lane: l, type: types[i] })));
      free = LANES[types.indexOf('barrier')];
      coins(free, z + 3, 3);
      end = z + 4;
    } else {
      // zigzag: wolny pas za każdym razem inny
      const rows = 3 + Math.floor(random() * 2 * level);
      let zz = z;
      for (let r = 0; r < rows; r++) {
        free = others(free)[Math.floor(random() * 2)];
        for (const l of others(free)) train(l, zz, 4);
        coins(free, zz, 2);
        zz += 4 + laneGap * 0.8;
      }
      end = zz - laneGap * 0.8;
    }

    lastForced = forced;
    z = end + (forced ? actionGap : laneGap) + random() * 4;
  }
  return items.sort((a, b) => a.z - b.z);
}

export function createPlayer() {
  return { lane: 0, x: 0, distance: 0, lives: 3, coins: 0, score: 0, jump: 0, slide: 0, invulnerable: 0, alive: true, seen: new Set() };
}

export function command(p, direction) {
  if (!p.alive) return;
  if (direction === 'left') p.lane = Math.max(-1, p.lane - 1);
  if (direction === 'right') p.lane = Math.min(1, p.lane + 1);
  if (direction === 'up' && p.jump <= 0 && p.slide <= 0) p.jump = ACTION_TIME;
  if (direction === 'down' && p.jump <= 0 && p.slide <= 0) p.slide = ACTION_TIME;
}

export const jumpHeight = (p) => (p.jump > 0 ? Math.sin((1 - p.jump / ACTION_TIME) * Math.PI) * 2.5 : 0);

export function advance(p, dt, speed, track) {
  if (!p.alive) return [];
  p.distance += speed * dt;
  p.x += (p.lane * LANE_WIDTH - p.x) * Math.min(1, dt * 14);
  p.jump = Math.max(0, p.jump - dt);
  p.slide = Math.max(0, p.slide - dt);
  p.invulnerable = Math.max(0, p.invulnerable - dt);
  const events = [];
  const hit = () => {
    p.lives--;
    p.invulnerable = 1.8;
    events.push('hit');
    if (p.lives <= 0) { p.alive = false; events.push('out'); }
  };
  for (let i = 0; i < track.length; i++) {
    const item = track[i];
    if (item.z > p.distance + 0.6) break; // tor jest posortowany – dalej same przyszłe przeszkody
    if (p.seen.has(i)) continue;
    const inLane = Math.abs(p.x - item.lane * LANE_WIDTH) <= 1;
    if (item.len) {
      // pociąg: groźny przez całą długość, także gdy wjedziesz na jego pas w połowie
      if (p.distance > item.z + item.len) { p.seen.add(i); continue; }
      if (inLane && p.invulnerable <= 0) { p.seen.add(i); hit(); }
      continue;
    }
    p.seen.add(i);
    if (!inLane) continue;
    if (item.type === 'coin') { p.coins++; events.push('coin'); continue; }
    const safe = (item.type === 'barrier' && jumpHeight(p) > 1.05) || (item.type === 'gate' && p.slide > 0);
    if (!safe && p.invulnerable <= 0) hit();
  }
  p.score = Math.floor(p.distance * 10) + p.coins * 25;
  return events;
}

const fmt = (sec) => {
  const s = Math.max(0, Math.floor(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
};

// Wspólny pad: lewo/prawo = pas, góra/A = skok, dół/B = ślizg
const DIRS = { left: 'left', right: 'right', up: 'up', down: 'down', a: 'up', b: 'down' };

export class RunnerMatch {
  constructor({ players, time }) {
    this.solo = players === 1;
    this.duration = time || 90;
    this.players = Array.from({ length: players }, () => createPlayer());
    this.track = createTrack((Math.random() * 4294967296) >>> 0);
    this.state = 'countdown';
    this.countdown = 3000;
    this.lastCount = 4;
    this.elapsed = 0;
    this.anim = 0;
    this.overFor = 0;
    this.result = null;
    this.popups = this.players.map(() => []);
    this.outAt = this.players.map(() => 0);
    this.go = 0;
  }

  emit(line) { this.onEvent?.(line); }

  popup(i, text) {
    this.popups[i] = [{ text, t: 0, id: Math.random() }];
  }

  press(i, button) {
    const dir = DIRS[button];
    const p = this.players[i];
    if (!dir || !p || this.state !== 'playing' || !p.alive) return;
    if (dir === 'up' && p.jump <= 0 && p.slide <= 0) sfx('jump');
    command(p, dir);
  }
  release() {}
  releaseAll() {}

  togglePause() {
    if (this.state === 'playing') this.state = 'paused';
    else if (this.state === 'paused') this.state = 'playing';
  }

  snapshot() {
    return this.players.map((p) => ({ score: p.score, alive: p.alive, info: `coins ${p.coins}  lives ${p.lives}` }));
  }

  update(dtMs) {
    const dt = Math.min(dtMs / 1000, 0.05);
    for (const list of this.popups) for (const pp of list) pp.t += dtMs;
    this.popups = this.popups.map((l) => l.filter((pp) => pp.t < 700));
    if (this.state === 'countdown') {
      this.countdown -= dtMs;
      const n = Math.ceil(this.countdown / 1000);
      if (n !== this.lastCount) { this.lastCount = n; if (n > 0) sfx('count'); }
      if (this.countdown <= 0) {
        this.state = 'playing';
        sfx('go');
        this.players.forEach((_, i) => this.popup(i, 'GO!'));
      }
      return;
    }
    if (this.state === 'over') { this.overFor += dtMs; this.anim += dt; return; }
    if (this.state !== 'playing') return;

    this.elapsed = Math.min(this.duration, this.elapsed + dt);
    this.anim += dt;
    const speed = 11 + Math.min(this.elapsed * 0.08, 8);
    this.players.forEach((p, i) => {
      for (const ev of advance(p, dt, speed, this.track)) {
        if (ev === 'coin') sfx('coin');
        if (ev === 'hit') { this.popup(i, '-1 LIFE'); sfx('crash'); this.emit(`P${i + 1} HIT ${p.lives}`); }
        if (ev === 'out') { this.outAt[i] = this.elapsed; sfx('over'); this.emit(`P${i + 1} OUT`); }
      }
    });
    if (this.elapsed >= this.duration || this.players.every((p) => !p.alive)) this.finish();
  }

  finish() {
    this.state = 'over';
    this.overFor = 0;
    const ps = this.players;
    const timeOf = (i) => (ps[i].alive ? this.elapsed : this.outAt[i]);
    let title;
    let sub;
    let note = null;
    let winner = -1;
    if (this.solo) {
      const p = ps[0];
      title = p.alive ? 'TIME UP' : 'GAME OVER';
      sub = `${p.score} PTS`;
      note = saveRecord('runner', p.score, false, (v) => String(v));
    } else {
      const [a, b] = ps;
      if (a.score !== b.score) winner = a.score > b.score ? 0 : 1;
      title = winner < 0 ? 'DRAW' : `PLAYER ${winner + 1} WINS`;
      sub = `${a.score} : ${b.score}`;
    }
    this.emit(winner >= 0 ? `WIN ${winner + 1}` : 'END');
    this.result = {
      title,
      sub,
      note,
      winner,
      head: this.solo ? null : ['', 'P1', 'P2'],
      rows: [
        ['SCORE', ...ps.map((p) => String(p.score))],
        ['DISTANCE', ...ps.map((p) => `${Math.floor(p.distance)} M`)],
        ['COINS', ...ps.map((p) => String(p.coins))],
        ['LIVES', ...ps.map((p) => String(p.lives))],
        ['TIME', ...ps.map((_, i) => fmt(timeOf(i)))],
      ],
    };
  }
}
