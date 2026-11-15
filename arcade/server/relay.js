// ARCADE – serwer sterowania. Zbiera wejście ze wszystkich źródeł i przekazuje je grze.
//
//   WebSocket  ws://<host>:8787            gra (?role=game), pady, skrypty, mikrokontrolery
//   HTTP       http://<host>:8787/api/...   /api/input, /api/cmd, /api/state (+ zgodność z API Ponga)
//   UDP        <host>:8788                  linie tekstu, np. "P1 UP PRESS"
//   Pad        http://<host>:8787/?player=1 pad na telefon
//   Upstream   ARCADE_UPSTREAM=ws://localhost:8765   serwer też łączy się jako klient (np. backend HALO)
import http from 'node:http';
import dgram from 'node:dgram';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { WebSocketServer, WebSocket } from 'ws';
import { parse, createDeduper, BUTTONS } from '../src/input/protocol.js';

export const PORT = Number(process.env.ARCADE_PORT || process.env.WS_PORT) || 8787;
export const UDP_PORT = process.env.ARCADE_UDP === '0' ? 0 : Number(process.env.ARCADE_UDP) || PORT + 1;
const VERBOSE = process.env.ARCADE_VERBOSE === '1';

function padPage() {
  const candidates = [
    path.join(path.dirname(fileURLToPath(import.meta.url)), 'pad.html'),
    path.resolve(process.cwd(), 'server/pad.html'),
  ];
  for (const p of candidates) if (fs.existsSync(p)) return fs.readFileSync(p);
  return 'server/pad.html not found';
}

function lanIps() {
  const out = [];
  for (const list of Object.values(os.networkInterfaces())) {
    for (const a of list || []) if (a.family === 'IPv4' && !a.internal) out.push(a.address);
  }
  return out;
}

export function startRelay({ port = PORT, udpPort = UDP_PORT } = {}) {
  if (globalThis.__arcadeRelay) return globalThis.__arcadeRelay;

  const games = new Set();
  const pads = new Set();
  const dedupe = createDeduper();
  let lastState = null;
  const ips = lanIps();
  const urls = {
    pad: ips.map((ip) => `http://${ip}:${port}/?player=1`),
    ws: ['ws://localhost:' + port, ...ips.map((ip) => `ws://${ip}:${port}`)],
    http: ['http://localhost:' + port + '/api', ...ips.map((ip) => `http://${ip}:${port}/api`)],
    udp: udpPort ? ips.map((ip) => `${ip}:${udpPort}`) : [],
  };

  const relayInfo = () => {
    const count = { 1: 0, 2: 0 };
    for (const p of pads) if (p.player === 1 || p.player === 2) count[p.player]++;
    // "type" jako pierwsze pole – gra rozpoznaje po nim komunikat serwisowy
    return JSON.stringify({ type: 'relay', pads: count, total: pads.size, urls });
  };
  const toGames = (text) => { for (const g of games) if (g.readyState === 1) g.send(text); };
  const toPads = (text) => { for (const p of pads) if (p.readyState === 1) p.send(text); };
  const announce = () => toGames(relayInfo());

  /** Wejście z dowolnego źródła → gra. Zwraca listę przyjętych zdarzeń. */
  function input(raw, source, owner) {
    const events = parse(raw).filter(dedupe);
    for (const ev of events) {
      if (owner) {
        owner.pressed = owner.pressed || new Set();
        owner.pressed.add(ev.player);
        if (!owner.player) owner.player = ev.player;
      }
      if (VERBOSE) console.log(`[arcade] ${source}:`, JSON.stringify(ev));
      toGames(JSON.stringify({ type: 'input', ...ev, source }));
    }
    return events;
  }

  // ---------------- HTTP ----------------
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, 'http://localhost');
    const p = url.pathname.replace(/\/+$/, '') || '/';
    const cors = {
      'access-control-allow-origin': '*',
      'access-control-allow-methods': 'GET, POST, OPTIONS',
      'access-control-allow-headers': 'content-type',
      'cache-control': 'no-store',
    };
    const json = (data, code = 200) => {
      res.writeHead(code, { ...cors, 'content-type': 'application/json; charset=utf-8' });
      res.end(JSON.stringify(data));
    };
    if (req.method === 'OPTIONS') { res.writeHead(204, cors); res.end(); return; }

    if (p === '/' || p === '/pad' || p === '/pad.html') {
      res.writeHead(200, { ...cors, 'content-type': 'text/html; charset=utf-8' });
      res.end(padPage());
      return;
    }

    let body = '';
    req.on('data', (c) => { body += c; if (body.length > 64e3) req.destroy(); });
    req.on('end', () => {
      const params = Object.fromEntries(url.searchParams);
      if (p === '/api') {
        return json({
          name: 'ARCADE input API',
          buttons: BUTTONS,
          states: ['down', 'up', 'tap'],
          game_clients: games.size,
          pads: pads.size,
          urls,
          endpoints: {
            '/api/input': 'GET/POST ?player=1&button=left&state=down | JSON body | text body',
            '/api/cmd': 'GET ?c=P1 LEFT PRESS | POST text body (one command per line)',
            '/api/state': 'GET – last state reported by the game',
            '/api/button': 'Pong compatible: ?player=1&button=up&action=press|release|tap',
            '/api/paddle': 'Pong compatible: ?player=2&pos=0.5 | ?player=2&raw=512&max=1023',
          },
        });
      }
      if (p === '/api/state') {
        if (req.method === 'POST' && body) { try { lastState = JSON.parse(body); toPads(body); } catch { /* ignore */ } }
        return json({ ok: true, state: lastState, game_clients: games.size });
      }
      if (p === '/api/input' || p === '/api/button' || p === '/api/paddle' || p === '/api/cmd') {
        let raw;
        if (p === '/api/cmd') raw = params.c ?? params.cmd ?? body;
        else if (body.trim()) {
          const t = body.trim();
          const form = t[0] !== '{' && t[0] !== '[' && t.includes('=') && !/\s/.test(t);
          raw = form ? Object.fromEntries(new URLSearchParams(t)) : t;
        } else raw = params;
        const events = input(raw, 'http');
        if (!events.length) return json({ ok: false, error: 'Unrecognised input. See GET /api' }, 400);
        const out = { ok: true, events, game_clients: games.size };
        if (!games.size) out.warning = 'No game is open in a browser.';
        return json(out);
      }
      json({ ok: false, error: 'Not found. Pad: /?player=1, API: /api' }, 404);
    });
  });

  // ---------------- WebSocket ----------------
  const wss = new WebSocketServer({ server });
  wss.on('connection', (ws, req) => {
    const q = new URL(req.url, 'http://localhost').searchParams;
    const isGame = q.get('role') === 'game';
    ws.player = Number(q.get('player')) || null;
    if (isGame) {
      games.add(ws);
      ws.send(relayInfo());
    } else {
      pads.add(ws);
      announce();
      if (lastState) ws.send(JSON.stringify(lastState));
    }

    ws.on('message', (data, isBinary) => {
      if (isBinary) return;
      const text = data.toString();
      if (isGame) {
        try { const m = JSON.parse(text); if (m.type === 'state') lastState = m; } catch { /* ignore */ }
        toPads(text);
        return;
      }
      const before = ws.player;
      input(text, 'ws', ws);
      if (ws.player !== before) announce();
    });

    ws.on('close', () => {
      if (isGame) { games.delete(ws); return; }
      pads.delete(ws);
      // pad zniknął w trakcie trzymania przycisku – puszczamy wszystko
      for (const pl of ws.pressed || []) toGames(JSON.stringify({ type: 'input', player: pl, button: 'all', state: 'up' }));
      announce();
    });
  });

  // ---------------- UDP ----------------
  let udp = null;
  if (udpPort) {
    udp = dgram.createSocket('udp4');
    udp.on('message', (msg, rinfo) => {
      const events = input(msg.toString('utf8'), 'udp');
      const reply = Buffer.from(events.length ? `OK ${events.length}\n` : 'ERR unrecognised\n');
      udp.send(reply, rinfo.port, rinfo.address);
    });
    udp.on('error', (e) => console.warn(`[arcade] UDP ${udpPort}: ${e.message}`));
    udp.bind(udpPort, '0.0.0.0');
  }

  // ---------------- Upstream (serwer jako klient, np. backend HALO) ----------------
  const upstreams = (process.env.ARCADE_UPSTREAM || '').split(',').map((s) => s.trim()).filter(Boolean);
  for (const target of upstreams) {
    let delay = 1000;
    const connect = () => {
      const ws = new WebSocket(target);
      ws.on('open', () => { delay = 1000; console.log(`[arcade] upstream connected: ${target}`); });
      ws.on('message', (data) => input(data.toString(), 'upstream'));
      ws.on('close', () => { setTimeout(connect, delay); delay = Math.min(delay * 2, 10000); });
      ws.on('error', () => {});
    };
    connect();
  }

  server.on('error', (e) => {
    if (e.code === 'EADDRINUSE') console.warn(`[arcade] port ${port} is busy – the input server is probably already running.`);
    else console.error('[arcade]', e);
  });
  server.listen(port, '0.0.0.0', () => {
    console.log(`\n  [arcade] input API   http://localhost:${port}/api   ws://localhost:${port}`);
    if (udpPort) console.log(`  [arcade] UDP         port ${udpPort}`);
    for (const u of urls.pad) console.log(`  [arcade] phone pad   ${u}  (or ?player=2)`);
    console.log('');
  });

  globalThis.__arcadeRelay = server;
  return server;
}
