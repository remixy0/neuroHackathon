import { PongMatch, DIFFS } from './engine.js';
import { PongView } from './PongView.jsx';

const POINTS = [3, 5, 7, 11, 15];
const cycle = (list, v, d) => list[(list.indexOf(v) + d + list.length) % list.length];

export default {
  id: 'pong',
  name: 'PONG',
  players: '1-2P',
  defaults: { players: 1, level: 'normal', points: 11 },

  sanitize(s) {
    const out = { ...this.defaults, ...s };
    if (out.players !== 1 && out.players !== 2) out.players = 1;
    if (!DIFFS.includes(out.level)) out.level = 'normal';
    if (!POINTS.includes(out.points)) out.points = 11;
    return out;
  },

  rows: (s) => [
    { key: 'players', label: 'PLAYERS', value: String(s.players) },
    ...(s.players === 1 ? [{ key: 'level', label: 'CPU', value: s.level.toUpperCase() }] : []),
    { key: 'points', label: 'POINTS', value: String(s.points) },
  ],

  change(s, key, dir) {
    if (key === 'players') return { ...s, players: s.players === 1 ? 2 : 1 };
    if (key === 'level') return { ...s, level: cycle(DIFFS, s.level, dir) };
    if (key === 'points') return { ...s, points: cycle(POINTS, s.points, dir) };
    return s;
  },

  create: (s) => new PongMatch(s),
  View: PongView,
  size: () => ({ w: 276, h: 218 }),
};
