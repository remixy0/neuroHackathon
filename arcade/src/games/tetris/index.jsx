import { Match } from './engine.js';
import { MODES, TIMES } from './constants.js';
import { PlayerScreen } from './PlayerScreen.jsx';

// Klawiatura jak w pierwotnym Tetrisie. Klawisze trafiają na wspólny pad, który Tetris rozumie tak:
// up = obrót w prawo, down = szybciej, a = upuść od razu, b = obrót w lewo, x = hold
// (pad w telefonie i gamepad działają więc tak samo: ▲ obraca, A upuszcza).
const SYSTEM_KEYS = { KeyP: [1, 'start'], Escape: [1, 'select'], Backspace: [1, 'select'] };
const KEYS_P1 = {
  KeyA: [1, 'left'], KeyD: [1, 'right'], KeyS: [1, 'down'], KeyW: [1, 'up'], KeyQ: [1, 'b'],
  Space: [1, 'a'], KeyE: [1, 'x'], ShiftLeft: [1, 'x'],
};
const KEYS_P2 = {
  ArrowLeft: [2, 'left'], ArrowRight: [2, 'right'], ArrowDown: [2, 'down'], ArrowUp: [2, 'up'],
  ControlRight: [2, 'b'], Slash: [2, 'b'], Enter: [2, 'a'], NumpadEnter: [2, 'a'], Numpad0: [2, 'a'],
  ShiftRight: [2, 'x'], Period: [2, 'x'],
};
// gra solo: oba zestawy + Z / X / C
const KEYS_SOLO_EXTRA = { KeyZ: [1, 'b'], KeyX: [1, 'up'], KeyC: [1, 'x'] };
const KEYMAP_DUO = { ...SYSTEM_KEYS, ...KEYS_P1, ...KEYS_P2 };
const KEYMAP_SOLO = { ...KEYMAP_DUO, ...KEYS_SOLO_EXTRA };

const cycle = (list, v, d) => list[(list.indexOf(v) + d + list.length) % list.length];
const modeOf = (s) => MODES[s.players].find((m) => m.id === s.mode) || MODES[s.players][0];

function TetrisView({ match, pads }) {
  const two = !match.solo;
  const name = modeOf({ players: match.players.length, mode: match.mode }).name;
  return (
    <div className="stage">
      <PlayerScreen
        match={match}
        player={match.players[0]}
        label={two ? 'Player 1' : name.charAt(0) + name.slice(1).toLowerCase()}
        led={!!pads[1]}
      />
      {two && <PlayerScreen match={match} player={match.players[1]} label="Player 2" led={!!pads[2]} />}
    </div>
  );
}

export default {
  id: 'tetris',
  name: 'TETRIS',
  players: '1-2P',
  defaults: { players: 1, mode: 'marathon', time: 120, garbage: false, level: 1 },

  sanitize(s) {
    const out = { ...this.defaults, ...s };
    if (out.players !== 1 && out.players !== 2) out.players = 1;
    if (!MODES[out.players].some((m) => m.id === out.mode)) out.mode = MODES[out.players][0].id;
    if (!TIMES.includes(out.time)) out.time = 120;
    if (!(out.level >= 1 && out.level <= 15)) out.level = 1;
    return out;
  },

  rows(s) {
    const timed = s.mode === 'ultra' || s.mode === 'timed';
    return [
      { key: 'players', label: 'PLAYERS', value: String(s.players) },
      { key: 'mode', label: 'MODE', value: modeOf(s).name },
      ...(timed ? [{ key: 'time', label: 'TIME', value: `${s.time / 60} MIN` }] : []),
      ...(s.players === 2 ? [{ key: 'garbage', label: 'GARBAGE', value: s.garbage ? 'ON' : 'OFF' }] : []),
      { key: 'level', label: 'LEVEL', value: String(s.level) },
    ];
  },

  change(s, key, dir) {
    switch (key) {
      case 'players': {
        const players = s.players === 1 ? 2 : 1;
        const mode = MODES[players][0].id;
        return { ...s, players, mode, garbage: mode === 'survival' };
      }
      case 'mode': {
        const mode = cycle(MODES[s.players].map((m) => m.id), s.mode, dir);
        return { ...s, mode, garbage: mode === 'survival' };
      }
      case 'time': return { ...s, time: cycle(TIMES, s.time, dir) };
      case 'garbage': return { ...s, garbage: !s.garbage };
      case 'level': return { ...s, level: ((s.level - 1 + dir + 15) % 15) + 1 };
      default: return s;
    }
  },

  create: (s) => new Match(s),
  keymap: (match) => (match.solo ? KEYMAP_SOLO : KEYMAP_DUO),
  View: TetrisView,
  // rozmiar sceny w jednostkach --u (ramka ekranu 212×188)
  size: (match) => ({ w: match.solo ? 212 : 430, h: 188 }),
};
