import { COLS, ROWS, HID, SHAPES } from './constants.js';

const VISIBLE = ROWS - HID;

// Mały podgląd klocka (hold / następne)
export function MiniPiece({ type, scale = 1, dim = false }) {
  if (!type) return null;
  const m = SHAPES[type];
  const rows = m.filter((r) => r.some(Boolean));
  const cols = m[0].map((_, c) => c).filter((c) => m.some((r) => r[c]));
  return (
    <div
      className={dim ? 'mini dim' : 'mini'}
      style={{ '--s': scale, gridTemplateColumns: `repeat(${cols.length}, calc(var(--cell) * ${scale}))` }}
    >
      {rows.flatMap((r, y) => cols.map((c) => (
        <div key={`${y}-${c}`} className={r[c] ? `cell t-${type}` : 'cell'} />
      )))}
    </div>
  );
}

export function Playfield({ player, hidden, overlay }) {
  const cells = new Array(COLS * VISIBLE).fill('');

  if (!hidden) {
    for (let y = HID; y < ROWS; y++) {
      for (let x = 0; x < COLS; x++) {
        const v = player.board[y][x];
        if (v) cells[(y - HID) * COLS + x] = player.alive ? `t-${v}` : 'dead';
      }
    }
    const c = player.cur;
    if (player.alive && c) {
      const gy = player.ghostY();
      c.m.forEach((row, r) => row.forEach((on, x) => {
        const yy = gy + r - HID;
        const i = yy * COLS + c.x + x;
        if (on && yy >= 0 && !cells[i]) cells[i] = `ghost t-${c.type}`;
      }));
      c.m.forEach((row, r) => row.forEach((on, x) => {
        const yy = c.y + r - HID;
        if (on && yy >= 0) cells[yy * COLS + c.x + x] = `t-${c.type}`;
      }));
    }
  }

  return (
    <div className="field">
      {cells.map((cls, i) => <div key={i} className={cls ? `cell ${cls}` : 'cell'} />)}
      {player.flash > 0 && !hidden && <div className="flash" />}
      {overlay && <div className="field-overlay">{overlay}</div>}
    </div>
  );
}
