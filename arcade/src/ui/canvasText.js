// Pikselowa czcionka na canvasie – te same znaki co w PixelText (ui/font.js)
import { textPath } from './font.js';

const cache = new Map();

/** Rysuje napis; y = górna krawędź litery (bez akcentów). */
export function drawText(ctx, text, x, y, s, align = 'left') {
  const { d, w } = textPath(text);
  let p = cache.get(d);
  if (!p) { p = new Path2D(d); cache.set(d, p); }
  const left = align === 'center' ? x - (w * s) / 2 : align === 'right' ? x - w * s : x;
  ctx.save();
  ctx.translate(left, y - 3 * s);
  ctx.scale(s, s);
  ctx.fill(p);
  ctx.restore();
}
