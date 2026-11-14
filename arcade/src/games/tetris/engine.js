// Silnik gry – czysty JS, bez Reacta. React tylko czyta stan i rysuje.
import {
  COLS, ROWS, HID, DAS, ARR, LOCK_DELAY, MAX_RESETS, SOFT_FACTOR,
  PIECES, SHAPES, KICKS, KICKS_I, COMBO_ATTACK,
} from './constants.js';
import { sfx } from '../../lib/sound.js';
import { saveRecord } from '../../lib/records.js';

function mulberry32(a) {
  return function rnd() {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function rotateMatrix(m, dir) {
  const n = m.length;
  const r = [];
  for (let y = 0; y < n; y++) {
    r.push([]);
    for (let x = 0; x < n; x++) r[y][x] = dir === 1 ? m[n - 1 - x][y] : m[x][n - 1 - y];
  }
  return r;
}

const gravityMs = (level) => Math.pow(0.8 - (level - 1) * 0.007, level - 1) * 1000;

export function formatTime(ms, centis = false) {
  const t = Math.max(0, ms);
  const m = Math.floor(t / 60000);
  const s = Math.floor(t / 1000) % 60;
  let out = `${m}:${String(s).padStart(2, '0')}`;
  if (centis) out += '.' + String(Math.floor(t / 10) % 100).padStart(2, '0');
  return out;
}

export class Player {
  constructor(id, seed, level, match) {
    this.id = id;
    this.match = match;
    this.rng = mulberry32(seed); // obaj gracze dostają tę samą kolejność klocków
    this.garbageRng = mulberry32(seed ^ (0x9e3779b9 * (id + 1)));
    this.board = Array.from({ length: ROWS }, () => Array(COLS).fill(0));
    this.queue = [];
    this.fillQueue();
    this.hold = null;
    this.holdUsed = false;
    this.score = 0;
    this.lines = 0;
    this.startLevel = level;
    this.level = level;
    this.combo = -1;
    this.maxCombo = 0;
    this.b2b = false;
    this.pieces = 0;
    this.tetrises = 0;
    this.tspins = 0;
    this.sent = 0;
    this.garbage = [];
    this.alive = true;
    this.opponent = null;
    this.time = 0;
    this.held = { left: false, right: false, soft: false };
    this.dir = 0;
    this.dasT = 0;
    this.arrT = 0;
    this.gravAcc = 0;
    this.popups = [];
    this.flash = 0;
    this.spawn();
  }

  fillQueue() {
    while (this.queue.length < 7) {
      const bag = [...PIECES];
      for (let i = bag.length - 1; i > 0; i--) {
        const j = Math.floor(this.rng() * (i + 1));
        [bag[i], bag[j]] = [bag[j], bag[i]];
      }
      this.queue.push(...bag);
    }
  }

  collide(m, x, y) {
    for (let r = 0; r < m.length; r++) {
      for (let c = 0; c < m[r].length; c++) {
        if (!m[r][c]) continue;
        const bx = x + c;
        const by = y + r;
        if (bx < 0 || bx >= COLS || by >= ROWS) return true;
        if (by >= 0 && this.board[by][bx]) return true;
      }
    }
    return false;
  }

  filled(x, y) {
    if (x < 0 || x >= COLS || y >= ROWS) return true;
    if (y < 0) return false;
    return !!this.board[y][x];
  }

  spawn(type) {
    if (!type) {
      type = this.queue.shift();
      this.fillQueue();
    }
    const m = SHAPES[type].map((r) => r.slice());
    // klocek pojawia się w całości w pierwszym widocznym rzędzie
    this.cur = { type, m, x: type === 'O' ? 4 : 3, y: type === 'I' ? HID - 1 : HID, rot: 0 };
    this.lockT = 0;
    this.resets = 0;
    this.lastRot = false;
    this.lastKick = 0;
    this.gravAcc = 0;
    this.lowest = this.cur.y;
    if (this.collide(m, this.cur.x, this.cur.y)) this.topOut();
  }

  afterMove() {
    const c = this.cur;
    if (this.collide(c.m, c.x, c.y + 1) && this.resets < MAX_RESETS) {
      this.lockT = 0;
      this.resets++;
    }
  }

  move(dx) {
    const c = this.cur;
    if (this.collide(c.m, c.x + dx, c.y)) return false;
    c.x += dx;
    this.lastRot = false;
    this.afterMove();
    return true;
  }

  rotate(dir) {
    const c = this.cur;
    if (c.type === 'O') return false;
    const nr = (c.rot + dir + 4) % 4;
    const nm = rotateMatrix(c.m, dir);
    const tests = (c.type === 'I' ? KICKS_I : KICKS)[`${c.rot}>${nr}`];
    for (let i = 0; i < tests.length; i++) {
      const [kx, ky] = tests[i];
      if (!this.collide(nm, c.x + kx, c.y - ky)) {
        c.m = nm;
        c.x += kx;
        c.y -= ky;
        c.rot = nr;
        this.lastRot = true;
        this.lastKick = i;
        if (c.y > this.lowest) { this.lowest = c.y; this.resets = 0; }
        this.afterMove();
        sfx('rotate');
        return true;
      }
    }
    return false;
  }

  stepDown(soft) {
    const c = this.cur;
    if (this.collide(c.m, c.x, c.y + 1)) return false;
    c.y++;
    this.lastRot = false;
    if (soft) this.score += 1;
    if (c.y > this.lowest) { this.lowest = c.y; this.resets = 0; this.lockT = 0; }
    return true;
  }

  hardDrop() {
    const c = this.cur;
    let d = 0;
    while (!this.collide(c.m, c.x, c.y + 1)) { c.y++; d++; }
    if (d > 0) this.lastRot = false;
    this.score += 2 * d;
    sfx('hard');
    this.lock();
  }

  doHold() {
    if (this.holdUsed) return;
    const t = this.cur.type;
    if (this.hold) {
      const h = this.hold;
      this.hold = t;
      this.spawn(h);
    } else {
      this.hold = t;
      this.spawn();
    }
    this.holdUsed = true;
    sfx('hold');
  }

  ghostY() {
    const c = this.cur;
    let y = c.y;
    while (!this.collide(c.m, c.x, y + 1)) y++;
    return y;
  }

  popup(text) {
    this.popups.push({ text, t: 0, id: Math.random() });
  }

  lock() {
    const c = this.cur;

    // T-spin: zasada trzech rogów
    let tspin = null;
    if (c.type === 'T' && this.lastRot) {
      const corners = [[0, 0], [2, 0], [0, 2], [2, 2]].map(([px, py]) => this.filled(c.x + px, c.y + py));
      if (corners.filter(Boolean).length >= 3) {
        const front = [[0, 1], [1, 3], [2, 3], [0, 2]][c.rot];
        tspin = (corners[front[0]] && corners[front[1]]) || this.lastKick === 4 ? 'full' : 'mini';
      }
    }

    let allHidden = true;
    for (let r = 0; r < c.m.length; r++) {
      for (let x = 0; x < c.m[r].length; x++) {
        if (!c.m[r][x]) continue;
        const by = c.y + r;
        if (by >= HID) allHidden = false;
        if (by >= 0) this.board[by][c.x + x] = c.type;
      }
    }
    this.pieces++;
    if (allHidden) { this.topOut(); return; }

    const full = [];
    for (let y = 0; y < ROWS; y++) if (this.board[y].every(Boolean)) full.push(y);
    const n = full.length;
    for (const y of full) {
      this.board.splice(y, 1);
      this.board.unshift(Array(COLS).fill(0));
    }

    const L = this.level;
    let pts;
    let atk;
    let label;
    if (tspin === 'full') {
      pts = [400, 800, 1200, 1600][n];
      atk = [0, 2, 4, 6][n];
      label = 'T-SPIN' + ['', ' SINGLE', ' DOUBLE', ' TRIPLE'][n];
      this.tspins++;
    } else if (tspin === 'mini') {
      const k = Math.min(n, 2);
      pts = [100, 200, 400][k];
      atk = [0, 0, 1][k];
      label = 'T-SPIN MINI' + ['', ' SINGLE', ' DOUBLE'][k];
    } else {
      pts = [0, 100, 300, 500, 800][n];
      atk = [0, 0, 1, 2, 4][n];
      label = ['', '', 'DOUBLE', 'TRIPLE', 'TETRIS'][n];
    }
    if (n === 4) this.tetrises++;

    if (n > 0) {
      const difficult = n === 4 || !!tspin;
      if (difficult) {
        if (this.b2b) { pts *= 1.5; atk += 1; label = 'B2B ' + label; }
        this.b2b = true;
      } else {
        this.b2b = false;
      }
      this.combo++;
      this.maxCombo = Math.max(this.maxCombo, this.combo);
      if (this.combo > 0) {
        pts += 50 * this.combo;
        atk += COMBO_ATTACK[Math.min(this.combo, COMBO_ATTACK.length - 1)];
      }
      this.score += Math.floor(pts * L);
      if (this.board.every((row) => row.every((v) => !v))) {
        this.score += [0, 800, 1200, 1800, 2000][n] * L;
        atk += 10;
        this.popup('PERFECT CLEAR');
      }
      if (label) this.popup(label);
      if (this.combo > 0) this.popup('COMBO ×' + this.combo);
      this.lines += n;
      this.level = Math.min(20, this.startLevel + Math.floor(this.lines / 10));
      this.flash = 120;
      this.match.emit(`P${this.id + 1} LINES ${n}`);
      sfx(tspin ? 'tspin' : n === 4 ? 'tetris' : 'clear');
    } else {
      this.combo = -1;
      if (tspin) { this.score += pts * L; this.popup(label); sfx('tspin'); } else sfx('lock');
    }

    // śmieci: najpierw kasują nadchodzące, reszta leci do przeciwnika
    if (this.match.garbageOn && atk > 0) {
      while (atk > 0 && this.garbage.length) {
        const k = Math.min(atk, this.garbage[0]);
        this.garbage[0] -= k;
        atk -= k;
        if (!this.garbage[0]) this.garbage.shift();
      }
      if (atk > 0 && this.opponent?.alive) {
        this.opponent.garbage.push(atk);
        this.sent += atk;
      }
    }
    if (n === 0 && this.garbage.length) {
      this.applyGarbage();
      if (!this.alive) return;
    }

    this.holdUsed = false;
    this.spawn();
  }

  applyGarbage() {
    for (const amount of this.garbage) {
      const hole = Math.floor(this.garbageRng() * COLS);
      for (let i = 0; i < amount; i++) {
        const top = this.board.shift();
        if (top.some(Boolean)) this.topOut();
        const row = Array(COLS).fill('G');
        row[hole] = 0;
        this.board.push(row);
      }
    }
    this.garbage = [];
    sfx('garbage');
  }

  topOut() {
    if (!this.alive) return;
    this.alive = false;
    this.time = this.match.elapsed;
    this.match.emit(`P${this.id + 1} OUT`);
    sfx('over');
    this.match.onDeath(this);
  }

  press(action) {
    if (!this.alive) return;
    switch (action) {
      case 'left':
        this.held.left = true; this.dir = -1; this.dasT = 0; this.arrT = 0; this.move(-1); break;
      case 'right':
        this.held.right = true; this.dir = 1; this.dasT = 0; this.arrT = 0; this.move(1); break;
      case 'soft':
        this.held.soft = true; this.stepDown(true); this.gravAcc = 0; break;
      case 'cw': this.rotate(1); break;
      case 'ccw': this.rotate(-1); break;
      case 'hard': this.hardDrop(); break;
      case 'hold': this.doHold(); break;
      default:
    }
  }

  release(action) {
    if (action === 'left') {
      this.held.left = false;
      if (this.dir === -1) { this.dir = this.held.right ? 1 : 0; this.dasT = 0; this.arrT = 0; }
    } else if (action === 'right') {
      this.held.right = false;
      if (this.dir === 1) { this.dir = this.held.left ? -1 : 0; this.dasT = 0; this.arrT = 0; }
    } else if (action === 'soft') {
      this.held.soft = false;
    }
  }

  releaseAll() {
    this.held = { left: false, right: false, soft: false };
    this.dir = 0;
  }

  tick(dt) {
    for (const p of this.popups) p.t += dt;
    this.popups = this.popups.filter((p) => p.t < 1600);
    if (this.flash > 0) this.flash -= dt;
  }

  update(dt) {
    this.tick(dt);
    if (!this.alive) return;

    if (this.dir !== 0) {
      this.dasT += dt;
      if (this.dasT >= DAS) {
        this.arrT += dt;
        while (this.arrT >= ARR) {
          this.arrT -= ARR;
          if (!this.move(this.dir)) { this.arrT = 0; break; }
        }
      }
    }

    const g = gravityMs(this.level);
    const interval = this.held.soft ? Math.max(g / SOFT_FACTOR, 1) : g;
    this.gravAcc += dt;
    while (this.gravAcc >= interval) {
      this.gravAcc -= interval;
      if (!this.stepDown(this.held.soft)) { this.gravAcc = 0; break; }
    }

    const c = this.cur;
    if (this.collide(c.m, c.x, c.y + 1)) {
      this.lockT += dt;
      if (this.lockT >= LOCK_DELAY) this.lock();
    } else {
      this.lockT = 0;
    }
  }
}

const PRESS_MAP = { up: 'cw', down: 'soft', left: 'left', right: 'right', a: 'hard', b: 'ccw', x: 'hold' };

export class Match {
  constructor({ players, mode, time, garbage, level }) {
    this.mode = mode;
    this.elapsed = 0;
    this.state = 'countdown'; // countdown | playing | paused | over
    this.countdown = 3000;
    this.lastCount = 4;
    this.overFor = 0;
    this.timeLimit = mode === 'ultra' || mode === 'timed' ? time * 1000 : 0;
    this.garbageOn = players === 2 && garbage;
    this.result = null;
    const seed = (Math.random() * 4294967296) >>> 0;
    this.players = Array.from({ length: players }, (_, i) => new Player(i, seed, level, this));
    if (players === 2) {
      this.players[0].opponent = this.players[1];
      this.players[1].opponent = this.players[0];
    }
  }

  get solo() { return this.players.length === 1; }

  update(dt) {
    if (this.state === 'countdown') {
      this.countdown -= dt;
      const n = Math.ceil(this.countdown / 1000);
      if (n !== this.lastCount) {
        this.lastCount = n;
        if (n > 0) sfx('count');
      }
      if (this.countdown <= 0) { this.state = 'playing'; sfx('go'); }
      return;
    }
    if (this.state === 'over') {
      this.overFor += dt;
      this.players.forEach((p) => p.tick(dt));
      return;
    }
    if (this.state !== 'playing') return;
    this.elapsed += dt;
    for (const p of this.players) {
      if (this.state !== 'playing') break;
      p.update(dt);
    }
    if (this.state === 'playing') this.checkEnd();
  }

  // Wspólny pad – tak jak na klawiaturze: up = obrót w prawo, down = szybciej, a = upuść od razu, b = obrót w lewo, x = hold
  press(i, button) {
    const action = PRESS_MAP[button];
    if (action && this.state === 'playing') this.players[i]?.press(action);
  }

  release(i, button) {
    const action = PRESS_MAP[button];
    if (action) this.players[i]?.release(action);
  }

  snapshot() {
    return this.players.map((p) => ({ score: p.score, alive: p.alive, info: `lines ${p.lines}  level ${p.level}` }));
  }

  emit(line) {
    this.onEvent?.(line);
  }

  releaseAll(i) {
    this.players[i]?.releaseAll();
  }

  togglePause() {
    if (this.state === 'playing') this.state = 'paused';
    else if (this.state === 'paused') this.state = 'playing';
  }

  onDeath() {
    if (this.state === 'over') return;
    if (this.solo || this.mode === 'survival') this.finish();
    else if (this.players.every((p) => !p.alive)) this.finish();
  }

  checkEnd() {
    if (this.mode === 'sprint' && this.players[0].lines >= 40) {
      this.finish();
    } else if (this.timeLimit && this.elapsed >= this.timeLimit) {
      this.elapsed = this.timeLimit;
      this.finish();
    }
  }

  finish() {
    this.state = 'over';
    this.overFor = 0;
    for (const p of this.players) if (p.alive) p.time = this.elapsed;
    this.result = buildResult(this);
  }
}

function buildResult(match) {
  const ps = match.players;
  let title;
  let sub;
  let record = null;
  let winner = -1;

  if (ps.length === 1) {
    const p = ps[0];
    if (match.mode === 'sprint') {
      if (p.lines >= 40) {
        title = 'FINISH!';
        sub = formatTime(p.time, true);
        record = saveRecord('tetris_sprint', p.time, true, (v) => formatTime(v, true));
      } else {
        title = 'GAME OVER';
        sub = `${p.lines}/40 LINES`;
      }
    } else {
      title = match.mode === 'ultra' && p.alive ? 'TIME UP' : 'GAME OVER';
      sub = `${p.score} PTS`;
      record = saveRecord('tetris_' + match.mode, p.score, false, (v) => String(v));
    }
  } else {
    const [a, b] = ps;
    if (match.mode === 'survival') {
      winner = a.alive ? 0 : b.alive ? 1 : -1;
      sub = winner < 0 ? 'BOTH TOPPED OUT' : `PLAYER ${2 - winner} TOPPED OUT`;
    } else {
      if (a.lines !== b.lines) winner = a.lines > b.lines ? 0 : 1;
      else if (a.score !== b.score) winner = a.score > b.score ? 0 : 1;
      sub = `LINES ${a.lines}:${b.lines}`;
    }
    title = winner < 0 ? 'DRAW' : `PLAYER ${winner + 1} WINS`;
  }

  const rows = [
    ['SCORE', (p) => p.score],
    ['LINES', (p) => p.lines],
    ['LEVEL', (p) => p.level],
    ['TETRISES', (p) => p.tetrises],
    ['T-SPINS', (p) => p.tspins],
    ['COMBO', (p) => Math.max(0, p.maxCombo)],
    ['PIECES/S', (p) => (p.pieces / Math.max(1, p.time / 1000)).toFixed(2)],
    ...(match.garbageOn ? [['GARBAGE', (p) => p.sent]] : []),
    ['TIME', (p) => formatTime(p.time)],
  ].map(([label, f]) => [label, ...ps.map((p) => String(f(p)))]);

  return { title, sub, note: record, winner, rows, head: ps.length === 2 ? ['', 'P1', 'P2'] : null };
}
