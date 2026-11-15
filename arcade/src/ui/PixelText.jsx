import { memo } from 'react';
import { textPath, GLYPH_H } from './font.js';

// Tekst rysowany pikselową czcionką. Rozmiar liczony w jednostkach --u (1 piksel ekranu LCD).
export const PixelText = memo(function PixelText({ text, scale = 1, className = '' }) {
  const { d, w } = textPath(text);
  return (
    <svg
      className={`px ${className}`}
      viewBox={`0 0 ${w} ${GLYPH_H}`}
      style={{ width: `calc(var(--u) * ${w * scale})`, height: `calc(var(--u) * ${GLYPH_H * scale})` }}
      shapeRendering="crispEdges"
      role="img"
      aria-label={String(text)}
    >
      <path d={d} fill="currentColor" />
    </svg>
  );
});
