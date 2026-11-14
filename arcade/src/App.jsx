import { useCallback, useEffect, useRef, useState } from 'react';
import { input } from './input/hub.js';
import { sfx, setMuted } from './lib/sound.js';
import { MenuScreen, Dialog } from './ui/Menus.jsx';
import tetris from './games/tetris/index.jsx';
import pong from './games/pong/index.jsx';
import runner from './games/runner/index.jsx';

const GAMES = [tetris, pong, runner];

const RESULTS_AFTER = 900; // ms po końcu gry, zanim pokaże się podsumowanie
const RESULTS_INPUT_AFTER = 1400; // chroni przed przypadkowym "Play again"
const PAUSE_ITEMS = [{ key: 'resume', label: 'RESUME' }, { key: 'restart', label: 'RESTART' }, { key: 'menu', label: 'MENU' }];
const RESULT_ITEMS = [{ key: 'restart', label: 'PLAY AGAIN' }, { key: 'menu', label: 'MENU' }];
const MENU_SIZE = { w: 212, h: 188 };
const DIALOG_H = 250;

const snap = (v) => Math.max(1.5, Math.min(6, Math.floor(v * 4) / 4));

// Rozmiar jednego "piksela" ekranu (--u) dobierany do okna i do tego, co jest na ekranie
function useUnit(w, h) {
  const calc = useCallback(() => {
    const u = snap(Math.min((window.innerWidth - 32) / w, (window.innerHeight - 32) / h));
    return { u, du: Math.min(u, snap((window.innerHeight - 24) / DIALOG_H)) };
  }, [w, h]);
  const [v, setV] = useState(calc);
  useEffect(() => {
    const f = () => setV(calc());
    f();
    window.addEventListener('resize', f);
    return () => window.removeEventListener('resize', f);
  }, [calc]);
  return v;
}

function loadSettings() {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem('arcade_settings') || '{}'); } catch { /* ignore */ }
  return Object.fromEntries(GAMES.map((g) => [g.id, g.sanitize(saved[g.id] || {})]));
}

export default function App() {
  const [settings, setSettings] = useState(loadSettings);
  const [screen, setScreen] = useState('hub'); // hub | setup | game
  const [gameId, setGameId] = useState(GAMES[0].id);
  const [hubIdx, setHubIdx] = useState(0);
  const [setupIdx, setSetupIdx] = useState(0);
  const [dlgIdx, setDlgIdx] = useState(0);
  const [status, setStatus] = useState(input.status);
  const [matchId, setMatchId] = useState(0);
  const [, setFrame] = useState(0);
  const matchRef = useRef(null);
  const heldRef = useRef({});
  const mutedRef = useRef(false);

  const game = GAMES.find((g) => g.id === gameId);
  const gs = settings[gameId];
  const match = matchRef.current;

  const hubRows = GAMES.map((g) => ({ key: g.id, label: g.name }));
  const setupRows = [...game.rows(gs), { key: 'start', label: 'START' }, { key: 'back', label: 'BACK' }];

  const size = screen === 'game' && match ? game.size(match) : MENU_SIZE;
  const { u, du } = useUnit(size.w, size.h);

  useEffect(() => {
    try { localStorage.setItem('arcade_settings', JSON.stringify(settings)); } catch { /* ignore */ }
  }, [settings]);
  useEffect(() => {
    if (setupIdx >= setupRows.length) setSetupIdx(setupRows.length - 1);
  }, [setupRows.length, setupIdx]);

  // Pętla gry: silnik liczy, React przerysowuje.
  // Własny układ klawiszy gry (Tetris) działa tylko w trakcie rozgrywki – menu, pauza i wyniki mają układ domyślny.
  const gameRef = useRef(game);
  gameRef.current = game;
  useEffect(() => {
    if (screen !== 'game') return undefined;
    let raf;
    let last = performance.now();
    const loop = (t) => {
      const dt = Math.min(50, t - last);
      last = t;
      const m = matchRef.current;
      m?.update(dt);
      const g = gameRef.current;
      const active = m && (m.state === 'playing' || m.state === 'countdown');
      input.setKeymap(active && g.keymap ? g.keymap(m) : null);
      setFrame((f) => (f + 1) % 1e9);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => { cancelAnimationFrame(raf); input.setKeymap(null); };
  }, [screen]);

  // ---------- akcje ----------
  const releaseHeld = () => {
    const m = matchRef.current;
    heldRef.current = {};
    m?.players.forEach((_, i) => m.releaseAll(i));
  };
  const startMatch = () => {
    const m = game.create(gs);
    m.onEvent = (line) => input.event(line);
    matchRef.current = m;
    heldRef.current = {};
    setDlgIdx(0);
    setMatchId((n) => n + 1);
    setScreen('game');
  };
  const toSetup = () => { matchRef.current = null; setScreen('setup'); };
  const toHub = () => { matchRef.current = null; setScreen('hub'); };

  const hubConfirm = (i) => {
    const row = hubRows[i];
    if (!row) return;
    sfx('menu');
    setGameId(row.key);
    setSetupIdx(0);
    setScreen('setup');
  };
  const setupChange = (i, d) => {
    const row = setupRows[i];
    if (!row || row.value === undefined) return;
    setSetupIdx(i);
    setSettings((s) => ({ ...s, [gameId]: game.change(s[gameId], row.key, d) }));
    sfx('menu');
  };
  const setupConfirm = (i) => {
    const row = setupRows[i];
    if (!row) return;
    if (row.key === 'start') startMatch();
    else if (row.key === 'back') { sfx('menu'); toHub(); } else setupChange(i, 1);
  };
  const dialogItems = match?.state === 'paused' ? PAUSE_ITEMS : RESULT_ITEMS;
  const dialogConfirm = (i) => {
    const key = dialogItems[i]?.key;
    if (key === 'resume') matchRef.current?.togglePause();
    if (key === 'restart') startMatch();
    if (key === 'menu') toSetup();
  };

  // Nawigacja w menu – ta sama dla każdego źródła wejścia.
  // Tylko dwa przyciski (góra/dół)? Oba naraz = OK.
  const nav = (ev, { count, index, setIndex, change, confirm, back, start }) => {
    const { player, button } = ev;
    const move = (d) => { setIndex((index + d + count) % count); sfx('menu'); };
    if (button === 'up' || button === 'down') {
      const other = button === 'up' ? 'down' : 'up';
      if (input.isDown(player, other)) { confirm(index); return; }
      move(button === 'up' ? -1 : 1);
    } else if ((button === 'left' || button === 'right') && change) change(index, button === 'left' ? -1 : 1);
    else if (button === 'start' && start) start();
    else if (button === 'a' || button === 'start') confirm(index);
    else if (button === 'b' || button === 'select') back?.();
  };

  // ---------- wejście (klawiatura, gamepad, sieć) ----------
  const handlers = useRef({});
  handlers.current = (ev) => {
    const m = matchRef.current;
    if (ev.pos !== undefined) {
      if (screen === 'game' && m) m.setPos?.(m.solo ? 0 : ev.player - 1, ev.pos);
      return;
    }
    if (screen === 'hub') {
      if (ev.down) nav(ev, { count: hubRows.length, index: hubIdx, setIndex: setHubIdx, confirm: hubConfirm });
      return;
    }
    if (screen === 'setup') {
      // START na ekranie ustawień od razu uruchamia grę (jak na konsoli)
      if (ev.down) nav(ev, { count: setupRows.length, index: setupIdx, setIndex: setSetupIdx, change: setupChange, confirm: setupConfirm, back: toHub, start: startMatch });
      return;
    }
    if (!m) return;
    if (m.state === 'paused') {
      if (ev.down) nav(ev, { count: PAUSE_ITEMS.length, index: dlgIdx, setIndex: setDlgIdx, confirm: dialogConfirm, back: () => m.togglePause() });
      return;
    }
    if (m.state === 'over') {
      if (ev.down && m.overFor >= RESULTS_INPUT_AFTER) {
        nav(ev, { count: RESULT_ITEMS.length, index: dlgIdx, setIndex: setDlgIdx, confirm: dialogConfirm, back: toSetup });
      }
      return;
    }
    if (ev.button === 'start' || ev.button === 'select') {
      if (ev.down && m.state === 'playing') { releaseHeld(); m.togglePause(); setDlgIdx(0); }
      return;
    }
    // W grze solo oba zestawy przycisków sterują jednym graczem – liczymy wciśnięcia
    const idx = m.solo ? 0 : ev.player - 1;
    if (idx >= m.players.length) return;
    const key = `${idx}:${ev.button}`;
    const c = heldRef.current[key] || 0;
    if (ev.down) {
      heldRef.current[key] = c + 1;
      if (c === 0) m.press(idx, ev.button);
    } else if (c > 0) {
      heldRef.current[key] = c - 1;
      if (c === 1) m.release(idx, ev.button);
    }
  };

  useEffect(() => {
    input.start();
    const off = input.on((ev) => handlers.current(ev));
    const offStatus = input.onStatus(setStatus);
    const keys = (e) => {
      if (e.repeat || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.code === 'KeyM') { mutedRef.current = !mutedRef.current; setMuted(mutedRef.current); }
      if (e.code === 'KeyF') {
        if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
        else document.documentElement.requestFullscreen().catch(() => {});
      }
    };
    const blur = () => {
      const m = matchRef.current;
      if (m && m.state === 'playing') { m.togglePause(); setDlgIdx(0); }
      heldRef.current = {};
      m?.players.forEach((_, i) => m.releaseAll(i));
    };
    window.addEventListener('keydown', keys);
    window.addEventListener('blur', blur);
    return () => {
      off();
      offStatus();
      window.removeEventListener('keydown', keys);
      window.removeEventListener('blur', blur);
    };
  }, []);

  // Stan dla padów i urządzeń (wynik na telefonie, /api/state)
  useEffect(() => {
    if (!status.connected) return undefined;
    const id = setInterval(() => {
      const m = matchRef.current;
      input.send({
        type: 'state',
        title: screen === 'hub' ? 'ARCADE' : game.name,
        game: screen === 'hub' ? null : gameId,
        screen,
        state: m ? m.state : null,
        players: m ? m.snapshot() : [],
        winner: m?.result ? m.result.winner + 1 : null,
      });
    }, 400);
    return () => clearInterval(id);
  }, [status.connected, screen, gameId, game]);

  // ---------- widok ----------
  let body;
  if (screen === 'hub') {
    body = (
      <MenuScreen
        title="ARCADE"
        label="Arcade"
        led={status.connected}
        rows={hubRows}
        centered
        itemScale={2}
        footer="1-2P"
        index={hubIdx}
        onPick={(i) => { setHubIdx(i); hubConfirm(i); }}
      />
    );
  } else if (screen === 'setup') {
    body = (
      <MenuScreen
        title={game.name}
        label={game.name.charAt(0) + game.name.slice(1).toLowerCase()}
        led={status.connected}
        rows={setupRows}
        index={setupIdx}
        onPick={(i) => { setSetupIdx(i); setupConfirm(i); }}
        onChange={setupChange}
      />
    );
  } else if (match) {
    const View = game.View;
    const r = match.result;
    const showResults = match.state === 'over' && match.overFor >= RESULTS_AFTER && r;
    body = (
      <>
        <View key={matchId} match={match} pads={status.pads || {}} />
        {match.state === 'paused' && (
          <Dialog unit={du} label="Pause" title="PAUSED" items={PAUSE_ITEMS} index={dlgIdx} onPick={(i) => { setDlgIdx(i); dialogConfirm(i); }} />
        )}
        {showResults && (
          <Dialog
            unit={du}
            label="Results"
            title={r.title}
            sub={r.sub}
            note={r.note}
            table={r.head ? [r.head, ...r.rows] : r.rows}
            items={RESULT_ITEMS}
            index={dlgIdx}
            onPick={(i) => { setDlgIdx(i); dialogConfirm(i); }}
          />
        )}
      </>
    );
  }

  return <div className="app" style={{ '--u': `${u}px` }}>{body}</div>;
}
