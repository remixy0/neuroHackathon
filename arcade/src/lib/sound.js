// Proste dźwięki generowane w przeglądarce (fala prostokątna jak w starych konsolach)
let ctx = null;
let muted = false;

export const setMuted = (v) => { muted = v; };

function tone(freq, dur, type = 'square', vol = 0.05, slide) {
  if (muted) return;
  try {
    ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    const t = ctx.currentTime;
    o.type = type;
    o.frequency.setValueAtTime(freq, t);
    if (slide) o.frequency.exponentialRampToValueAtTime(slide, t + dur);
    g.gain.setValueAtTime(vol, t);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(g);
    g.connect(ctx.destination);
    o.start(t);
    o.stop(t + dur + 0.02);
  } catch {
    /* brak audio – trudno */
  }
}

const SFX = {
  rotate: () => tone(440, 0.04, 'square', 0.02),
  lock: () => tone(140, 0.06, 'square', 0.04),
  hard: () => tone(220, 0.08, 'square', 0.05, 90),
  hold: () => tone(660, 0.05, 'square', 0.03),
  clear: () => tone(523, 0.16, 'square', 0.05, 1046),
  tetris: () => {
    tone(523, 0.1, 'square', 0.05);
    setTimeout(() => tone(659, 0.1, 'square', 0.05), 90);
    setTimeout(() => tone(784, 0.1, 'square', 0.05), 180);
    setTimeout(() => tone(1046, 0.22, 'square', 0.05), 270);
  },
  tspin: () => tone(330, 0.22, 'square', 0.04, 990),
  garbage: () => tone(90, 0.14, 'square', 0.05, 60),
  over: () => tone(392, 0.9, 'square', 0.05, 49),
  count: () => tone(587, 0.1, 'square', 0.05),
  go: () => tone(1175, 0.22, 'square', 0.05),
  menu: () => tone(880, 0.03, 'square', 0.02),
  // Pong – "bipy" jak w oryginalnym automacie
  pongHit: () => tone(459, 0.05, 'square', 0.06),
  pongWall: () => tone(226, 0.045, 'square', 0.06),
  pongScore: () => tone(490, 0.27, 'square', 0.06),
  // RUNNER
  coin: () => { tone(988, 0.05, 'square', 0.03); setTimeout(() => tone(1319, 0.09, 'square', 0.03), 50); },
  crash: () => tone(180, 0.25, 'sawtooth', 0.06, 60),
  jump: () => tone(392, 0.08, 'square', 0.025, 784),
};

export function sfx(name) {
  SFX[name]?.();
}
