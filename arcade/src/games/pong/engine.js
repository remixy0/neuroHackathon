// PONG – logika gry (bez DOM). Mechanika jak w automacie z 1972 r.:
//  - paletka podzielona na 8 segmentów → kąt odbicia zależy od miejsca trafienia
//  - piłka przyspiesza po 4. i 12. odbiciu w wymianie
//  - serw ze środka w stronę gracza, który stracił punkt
import { sfx } from '../../lib/sound.js';

export const W = 800;
export const H = 600;
export const CFG = {
  paddleW: 12,
  paddleH: 64,
  inset: 44,
  ball: 12,
  speeds: [430, 520, 620],
  speedHits: [4, 12],
  angle: [-1, -0.68, -0.4, -0.14, 0.14, 0.4, 0.68, 1],
  angleScale: 0.85,
  paddleSpeed: 640,
  serveDelay: 1.1,
};
const AI_LEVELS = {
  easy: { speed: 330, react: 0.28, err: 34, predict: false },
  normal: { speed: 420, react: 0.18, err: 26, predict: true },
  hard: { speed: 540, react: 0.1, err: 16, predict: true },
};
export const DIFFS = ['easy', 'normal', 'hard'];
const STEP = 1 / 240;

const rand = (a, b) => a + Math.random() * (b - a);
const pick = (arr) => arr[(Math.random() * arr.length) | 0];
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

function formatTime(sec) {
  const s = Math.floor(sec);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

export class PongMatch {
  constructor({ players, level, points }) {
    this.solo = players === 1;
    this.diff = DIFFS.includes(level) ? level : 'normal';
    this.winScore = points || 11;
    this.state = 'playing'; // playing | paused | over
    this.overFor = 0;
    this.elapsed = 0;
    this.clock = 0;
    this.acc = 0;
    this.result = null;
    this.score = [0, 0];
    this.hits = [0, 0];
    this.rally = 0;
    this.longestRally = 0;
    this.phase = 'serve';
    this.timer = CFG.serveDelay + 0.5;
    this.serveDir = Math.random() < 0.5 ? -1 : 1;
    this.winner = -1;
    const mk = (side) => ({
      side,
      x: side === 0 ? CFG.inset : W - CFG.inset - CFG.paddleW,
      y: (H - CFG.paddleH) / 2,
      hold: 0,
      ai: null,
    });
    this.paddles = [mk(0), mk(1)];
    if (this.solo) this.paddles[1].ai = { cfg: AI_LEVELS[this.diff], t: 0, coming: false, aim: 0, target: (H - CFG.paddleH) / 2 };
    this.ball = { x: W / 2 - CFG.ball / 2, y: rand(H * 0.25, H * 0.75 - CFG.ball), vx: 0, vy: 0, live: false };
    // stan przycisków ludzi: [gracz] → { up, down, pos }
    this.ctl = [{ up: false, down: false, pos: null }, { up: false, down: false, pos: null }];
    this.chord = [0, 0];
    // "players" – wspólny interfejs dla menu, padów i wyników
    this.players = this.solo ? [{ score: 0, alive: true }] : [{ score: 0, alive: true }, { score: 0, alive: true }];
    this.emit('START');
  }

  emit(line) { this.onEvent?.(line); }

  // ---------- wejście ----------
  press(i, button) {
    const c = this.ctl[i];
    if (!c) return;
    if (button === 'up' || button === 'down') { c[button] = true; c.pos = null; }
  }
  release(i, button) {
    const c = this.ctl[i];
    if (c && (button === 'up' || button === 'down')) c[button] = false;
  }
  releaseAll(i) {
    const c = this.ctl[i];
    if (c) { c.up = false; c.down = false; }
  }
  setPos(i, v) {
    const c = this.ctl[i];
    if (c) c.pos = v;
  }
  togglePause() {
    if (this.state === 'playing') { this.state = 'paused'; sfx('menu'); }
    else if (this.state === 'paused') { this.state = 'playing'; sfx('menu'); }
  }

  snapshot() {
    return this.players.map((_, i) => ({
      score: this.score[i],
      alive: true,
      info: this.solo ? `you ${this.score[0]}  cpu ${this.score[1]}` : `${this.score[0]} : ${this.score[1]}`,
    }));
  }

  // ---------- fizyka ----------
  update(dtMs) {
    const dt = Math.min(0.1, dtMs / 1000);
    this.clock += dt;
    if (this.state === 'over') { this.overFor += dtMs; return; }
    if (this.state !== 'playing') return;
    this.elapsed += dt;
    this.handleChords(dt);
    if (this.state !== 'playing') return;
    this.acc += dt;
    while (this.acc >= STEP && this.state === 'playing') { this.step(STEP); this.acc -= STEP; }
  }

  // Tylko 2 przyciski (góra/dół)? Przytrzymaj oba 1 s → pauza.
  handleChords(dt) {
    this.ctl.forEach((c, i) => {
      if (c.up && c.down) {
        this.chord[i] += dt;
        if (this.chord[i] >= 1) { this.chord[i] = -999; this.togglePause(); }
      } else this.chord[i] = 0;
    });
  }

  step(dt) {
    for (const p of this.paddles) this.movePaddle(p, dt);
    if (this.phase === 'serve') {
      this.timer -= dt;
      if (this.timer <= 0) this.serve();
    } else if (this.phase === 'live') {
      this.stepBall(dt);
    }
  }

  movePaddle(p, dt) {
    const maxY = H - CFG.paddleH;
    if (p.ai) {
      this.aiMove(p, dt);
    } else {
      // w grze solo oba zestawy przycisków sterują lewą paletką (App łączy wejście)
      const c = this.ctl[p.side];
      if (c.pos !== null && c.pos !== undefined && !c.up && !c.down) {
        // potencjometr / pokrętło: paletka podąża za pozycją
        p.y += (c.pos * maxY - p.y) * Math.min(1, dt * 28);
        p.hold = 0;
      } else {
        const dir = (c.down ? 1 : 0) - (c.up ? 1 : 0);
        if (dir) {
          p.hold += dt;
          const sp = CFG.paddleSpeed * Math.min(1, 0.55 + p.hold * 4); // krótkie wciśnięcie = precyzja
          p.y += dir * sp * dt;
        } else p.hold = 0;
      }
    }
    p.y = clamp(p.y, 0, maxY);
  }

  predictY(faceX) {
    const b = this.ball;
    const S = CFG.ball;
    const edge = b.vx > 0 ? b.x + S : b.x;
    const t = (faceX - edge) / b.vx;
    if (t < 0) return b.y + S / 2;
    const range = H - S;
    let y = b.y + b.vy * t;
    y = ((y % (2 * range)) + 2 * range) % (2 * range);
    if (y > range) y = 2 * range - y;
    return y + S / 2;
  }

  aiMove(p, dt) {
    const ai = p.ai;
    const c = ai.cfg;
    const b = this.ball;
    const ph = CFG.paddleH;
    const coming = b.live && this.phase === 'live' && (p.side === 0 ? b.vx < 0 : b.vx > 0);
    if (coming && !ai.coming) {
      ai.t = 0;
      ai.aim = rand(-ph * 0.4, ph * 0.4) + rand(-c.err, c.err);
    }
    ai.coming = coming;
    let speed = c.speed;
    if (coming) {
      ai.t += dt;
      if (ai.t >= c.react) {
        const face = p.side === 0 ? p.x + CFG.paddleW : p.x;
        const by = c.predict ? this.predictY(face) : b.y + CFG.ball / 2;
        ai.target = by - ph / 2 - ai.aim;
      }
    } else {
      ai.target = (H - ph) / 2;
      speed *= 0.45;
    }
    const d = ai.target - p.y;
    if (Math.abs(d) > 1.5) p.y += Math.sign(d) * Math.min(Math.abs(d), speed * dt);
  }

  speedFor(hits) {
    return CFG.speeds[hits >= CFG.speedHits[1] ? 2 : hits >= CFG.speedHits[0] ? 1 : 0];
  }

  serve() {
    const b = this.ball;
    const sp = CFG.speeds[0];
    this.rally = 0;
    b.x = W / 2 - CFG.ball / 2;
    b.vx = this.serveDir * sp;
    b.vy = pick([-0.4, -0.14, 0.14, 0.4]) * sp * CFG.angleScale;
    b.live = true;
    this.phase = 'live';
  }

  bounce(p, newX, dir) {
    const b = this.ball;
    const rel = (b.y + CFG.ball / 2 - p.y) / CFG.paddleH;
    const seg = clamp(Math.floor(rel * 8), 0, 7);
    this.rally++;
    this.hits[p.side]++;
    this.longestRally = Math.max(this.longestRally, this.rally);
    const sp = this.speedFor(this.rally);
    b.x = newX;
    b.vx = dir * sp;
    b.vy = CFG.angle[seg] * sp * CFG.angleScale;
    sfx('pongHit');
    this.emit('HIT');
  }

  point(side) {
    const b = this.ball;
    this.score[side]++;
    b.live = false;
    sfx('pongScore');
    this.emit(`SCORE ${this.score[0]} ${this.score[1]}`);
    if (this.score[side] >= this.winScore) {
      this.winner = side;
      this.phase = 'done';
      this.finish();
      return;
    }
    this.phase = 'serve';
    this.timer = CFG.serveDelay;
    this.serveDir = side === 0 ? 1 : -1;
    b.x = W / 2 - CFG.ball / 2;
    b.y = rand(H * 0.25, H * 0.75 - CFG.ball);
  }

  stepBall(dt) {
    const b = this.ball;
    const S = CFG.ball;
    const PW = CFG.paddleW;
    const PH = CFG.paddleH;
    b.x += b.vx * dt;
    b.y += b.vy * dt;
    if (b.y < 0) { b.y = -b.y; b.vy = Math.abs(b.vy); sfx('pongWall'); this.emit('WALL'); }
    else if (b.y > H - S) { b.y = 2 * (H - S) - b.y; b.vy = -Math.abs(b.vy); sfx('pongWall'); this.emit('WALL'); }

    for (const p of this.paddles) {
      if (b.y + S < p.y || b.y > p.y + PH) continue;
      if (p.side === 0 && b.vx < 0) {
        const face = p.x + PW;
        if (b.x <= face && b.x >= face - 8) this.bounce(p, face, 1);
      } else if (p.side === 1 && b.vx > 0) {
        const face = p.x;
        if (b.x + S >= face && b.x + S <= face + 8) this.bounce(p, face - S, -1);
      }
    }
    if (b.x + S < -30) this.point(1);
    else if (b.x > W + 30) this.point(0);
  }

  finish() {
    this.state = 'over';
    this.overFor = 0;
    this.emit(`WIN ${this.winner + 1}`);
    const [a, b] = this.score;
    const title = this.solo ? (this.winner === 0 ? 'YOU WIN' : 'CPU WINS') : `PLAYER ${this.winner + 1} WINS`;
    this.result = {
      title,
      sub: `${a} : ${b}`,
      note: `LONGEST RALLY ${this.longestRally}`,
      winner: this.solo ? (this.winner === 0 ? 0 : -1) : this.winner,
      head: this.solo ? ['', 'YOU', 'CPU'] : ['', 'P1', 'P2'],
      rows: [
        ['POINTS', String(a), String(b)],
        ['HITS', String(this.hits[0]), String(this.hits[1])],
        ['TIME', formatTime(this.elapsed), formatTime(this.elapsed)],
      ],
    };
  }
}
