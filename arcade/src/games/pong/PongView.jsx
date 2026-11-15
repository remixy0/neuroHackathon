import { useEffect, useRef } from 'react';
import { Screen } from '../../ui/Screen.jsx';
import { drawText } from '../../ui/canvasText.js';
import { W, H, CFG } from './engine.js';

const INK = '#ececec';

// Cyfry wyniku 3×5 – blokowe, jak w automacie z 1972 r.
const DIGITS = {
  0: ['###', '#.#', '#.#', '#.#', '###'],
  1: ['..#', '..#', '..#', '..#', '..#'],
  2: ['###', '..#', '###', '#..', '###'],
  3: ['###', '..#', '###', '..#', '###'],
  4: ['#.#', '#.#', '###', '..#', '..#'],
  5: ['###', '#..', '###', '..#', '###'],
  6: ['#..', '#..', '###', '#.#', '###'],
  7: ['###', '..#', '..#', '..#', '..#'],
  8: ['###', '#.#', '###', '#.#', '###'],
  9: ['###', '#.#', '###', '..#', '..#'],
};

function drawScore(ctx, n, cx, y, s) {
  const str = String(n);
  const w = (str.length * 3 + (str.length - 1)) * s;
  let x = cx - w / 2;
  for (const ch of str) {
    DIGITS[ch].forEach((row, py) => {
      for (let px = 0; px < 3; px++) if (row[px] === '#') ctx.rect(x + px * s, y + py * s, s, s);
    });
    x += 4 * s;
  }
}

function render(ctx, m) {
  const blink = (hz) => Math.floor(m.clock * hz * 2) % 2 === 0;
  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, W, H);
  ctx.fillStyle = INK;
  ctx.globalAlpha = m.state === 'paused' ? 0.35 : 1;

  ctx.beginPath();
  for (let y = 4; y < H; y += 24) ctx.rect(W / 2 - 2, y, 4, 12); // siatka
  for (const p of m.paddles) ctx.rect(p.x, p.y, CFG.paddleW, CFG.paddleH);
  const b = m.ball;
  if (b.live || (m.phase === 'serve' && m.timer < 0.6 && blink(4))) ctx.rect(b.x, b.y, CFG.ball, CFG.ball);
  drawScore(ctx, m.score[0], W / 2 - 130, 30, 13);
  drawScore(ctx, m.score[1], W / 2 + 130, 30, 13);
  ctx.fill();

  if (m.state === 'playing' && m.phase === 'serve' && m.score[0] + m.score[1] === 0) {
    const label = m.solo ? `YOU VS CPU (${m.diff.toUpperCase()})` : 'PLAYER 1 VS PLAYER 2';
    ctx.globalAlpha = 0.7;
    drawText(ctx, label, W / 2, H - 70, 3, 'center');
  }
  ctx.globalAlpha = 1;
}

export function PongView({ match, pads }) {
  const canvas = useRef(null);
  const ref = useRef(match);
  ref.current = match;

  useEffect(() => {
    const cv = canvas.current;
    const ctx = cv.getContext('2d', { alpha: false });
    let raf;
    const loop = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = Math.max(1, Math.round(cv.clientWidth * dpr));
      const h = Math.max(1, Math.round(cv.clientHeight * dpr));
      if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
      ctx.setTransform(w / W, 0, 0, h / H, 0, 0);
      render(ctx, ref.current);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, []);

  const label = match.solo ? 'Player 1 vs CPU' : 'Player 1 vs Player 2';
  return (
    <div className="stage">
      <Screen label={label} led={!!(pads[1] || pads[2])} ledLabel="pad">
        <canvas ref={canvas} className="pong-canvas" aria-label="Pong" />
      </Screen>
    </div>
  );
}
