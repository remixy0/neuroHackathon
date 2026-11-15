import { RunnerMatch } from './engine.js';
import { RunnerView } from './RunnerView.jsx';

const TIMES = [60, 90, 120];
const cycle = (list, v, d) => list[(list.indexOf(v) + d + list.length) % list.length];

export default {
  id: 'runner',
  name: 'RUNNER',
  players: '1-2P',
  defaults: { players: 2, time: 90 },

  sanitize(s) {
    const out = { ...this.defaults, ...s };
    if (out.players !== 1 && out.players !== 2) out.players = 2;
    if (!TIMES.includes(out.time)) out.time = 90;
    return out;
  },

  rows: (s) => [
    { key: 'players', label: 'PLAYERS', value: String(s.players) },
    { key: 'time', label: 'TIME', value: `${s.time} SEC` },
  ],

  change(s, key, dir) {
    if (key === 'players') return { ...s, players: s.players === 1 ? 2 : 1 };
    if (key === 'time') return { ...s, time: cycle(TIMES, s.time, dir) };
    return s;
  },

  create: (s) => new RunnerMatch(s),
  View: RunnerView,
  // ekran 224×168 + ramka
  size: (match) => ({ w: match.solo ? 244 : 494, h: 194 }),
};
