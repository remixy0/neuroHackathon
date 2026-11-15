import http from 'node:http';
import { networkInterfaces } from 'node:os';
import { pathToFileURL } from 'node:url';
import { WebSocketServer, WebSocket } from 'ws';

// Receiver only: no model, database, authentication or game commands.
export function createReceiver({ log = console.log, idleTimeoutMs = 10_000 } = {}) {
  const players = new Map();
  const server = http.createServer((req, res) => {
    if (req.url !== '/health') {
      res.writeHead(404).end('Use WebSocket /ws/controller or GET /health\n');
      return;
    }
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ status: 'ok', service: 'halo-test-receiver', modes: ['eeg', 'manual'], players: [...players.keys()] }));
  });
  const wss = new WebSocketServer({ server, path: '/ws/controller', maxPayload: 1024 * 1024 });
  // The HTTP server owns listen errors; ws forwards those too.
  wss.on('error', error => log(`[SERVER ERROR] ${error.message}`));

  wss.on('connection', (ws, req) => {
    let session = null;
    let nextSeq = 0;
    let samples = 0;
    let mode = 'eeg';
    let lastSeen = Date.now();
    log(`[CONNECT] ${req.socket.remoteAddress}`);

    const send = (type, extra = {}) => ws.send(JSON.stringify({
      type, version: 1, session_id: session?.session_id ?? '', ...extra,
    }));
    const release = () => {
      if (session && players.get(session.player) === ws) players.delete(session.player);
    };
    const reject = (message, code = 'invalid_packet', sessionId = session?.session_id ?? '') => {
      log(`[ERROR] ${message}`);
      ws.send(JSON.stringify({ type: 'error', version: 1, session_id: sessionId, code, message }));
      ws.close(1008, code);
      release();
    };
    // Also release player slots if a phone vanishes without sending stop/close.
    const timer = setInterval(() => {
      if (Date.now() - lastSeen > idleTimeoutMs) {
        log('[TIMEOUT] Brak danych lub heartbeat kontrolera');
        release();
        ws.terminate();
      }
    }, Math.min(1000, idleTimeoutMs));
    timer.unref();
    // Manual controllers may stay idle indefinitely. OkHttp pings every 5 seconds.
    // EEG still requires actual samples, even if its WebSocket transport is alive.
    ws.on('ping', () => { if (session && mode === 'manual') lastSeen = Date.now(); });

    ws.on('message', (raw, binary) => {
      if (ws.readyState !== WebSocket.OPEN) return;
      lastSeen = Date.now();
      if (binary) return reject('Oczekiwano tekstowego JSON');
      let message;
      try { message = JSON.parse(raw.toString()); }
      catch { return reject('Nieprawidłowy JSON'); }
      if (!message || Array.isArray(message) || typeof message !== 'object') return reject('Oczekiwano obiektu JSON');
      // Print complete arrays, without console.log's array truncation.
      log(`[RX] ${JSON.stringify(message)}`);
      if (message.version !== 1 || typeof message.session_id !== 'string' || !message.session_id) {
        return reject('Wymagane version=1 i session_id', 'invalid_packet', message.session_id ?? '');
      }

      if (message.type === 'hello') {
        if (session) return reject('Sesja jest już zarejestrowana');
        const requestedMode = message.mode ?? 'eeg';
        if (message.role !== 'controller' || ![1, 2].includes(message.player) || !['eeg', 'manual'].includes(requestedMode)) {
          return reject('Nieprawidłowy gracz lub tryb kontrolera', 'invalid_packet', message.session_id);
        }
        const stream = message.stream;
        if (requestedMode === 'eeg' && (
            !Array.isArray(stream?.channels) || stream.channels.length === 0 ||
            !stream.channels.every(c => typeof c === 'string' && c.length > 0) ||
            new Set(stream.channels).size !== stream.channels.length ||
            !Number.isInteger(stream.sample_rate_hz) || stream.sample_rate_hz <= 0 ||
            stream.layout !== 'sample_major' || typeof stream.has_accel !== 'boolean' || typeof stream.has_gyro !== 'boolean')) {
          return reject('Nieprawidłowe hello / metadane strumienia', 'invalid_packet', message.session_id);
        }
        if (players.has(message.player)) return reject('Gracz jest już połączony', 'player_busy', message.session_id);
        session = message;
        mode = requestedMode;
        players.set(session.player, ws);
        send('ready', { player: session.player, ...(mode === 'manual' ? { mode } : {}) });
        log(mode === 'manual' ? `[READY] gracz=${session.player}, tryb=manual` :
          `[READY] gracz=${session.player}, HALO=${session.device?.name ?? '?'}, ${stream.sample_rate_hz} Hz, kanały=${stream.channels.join(',')}`);
        return;
      }
      if (!session || message.session_id !== session.session_id) return reject('Najpierw hello; session_id musi być zgodne');
      if (message.type === 'stop') {
        log(`[STOP] gracz=${session.player}, pakiety=${nextSeq}, próbki=${samples}`);
        release();
        ws.close(1000, 'Stopped');
        return;
      }
      if (message.type === 'manual') {
        const buttons = ['up', 'down', 'left', 'right', 'a', 'b', 'x', 'select', 'start'];
        if (mode !== 'manual' || message.player !== session.player || message.action !== 'press' ||
            !buttons.includes(message.button) || !Number.isSafeInteger(message.seq) || message.seq !== nextSeq ||
            message.id !== `${session.session_id}:${message.seq}`) {
          return reject('Nieprawidłowy tryb, gracz, przycisk lub numer zdarzenia manual');
        }
        nextSeq++;
        log(`[MANUAL] gracz=${session.player}, przycisk=${message.button}, id=${message.id}`);
        send('ack', { seq: message.seq });
        return;
      }
      if (message.type !== 'samples') return reject('Nieznany typ wiadomości');
      if (mode !== 'eeg') return reject('Sesja manual nie przyjmuje próbek EEG');
      const n = message.sample_count;
      const numericArray = (value, length) => Array.isArray(value) && value.length === length && value.every(Number.isFinite);
      const boolArray = (value, length) => Array.isArray(value) && value.length === length && value.every(v => typeof v === 'boolean');
      const channels = session.stream.channels.length;
      if (!Number.isSafeInteger(message.seq) || message.seq !== nextSeq || !Number.isInteger(n) || n <= 0 ||
          !numericArray(message.eeg, n * channels) || !boolArray(message.is_dummy, n) || !boolArray(message.contact, channels) ||
          !(session.stream.has_accel ? numericArray(message.accel, n * 3) : message.accel === null) ||
          !(session.stream.has_gyro ? numericArray(message.gyro, n * 3) : message.gyro === null)) {
        return reject('Nieprawidłowe seq lub rozmiary / wartości próbek');
      }
      nextSeq++;
      samples += n;
      send('ack', { seq: message.seq }); // Every packet, comfortably within the Android 2 s deadline.
      log(`[ACK] gracz=${session.player}, seq=${message.seq}, próbki=${n}, razem=${samples}`);
    });
    ws.on('error', error => log(`[SOCKET ERROR] ${error.message}`));
    ws.on('close', (code, reason) => {
      clearInterval(timer);
      release();
      log(`[DISCONNECT] gracz=${session?.player ?? '?'}, kod=${code}, powód=${reason.toString()}, próbki=${samples}`);
    });
  });

  return {
    server,
    close() {
      for (const ws of wss.clients) ws.terminate();
      return new Promise(resolve => wss.close(() => server.close(resolve)));
    },
  };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const port = Number(process.env.PORT ?? 8766);
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('PORT musi być liczbą 1–65535');
  const receiver = createReceiver();
  receiver.server.on('error', error => { console.error(`Nie można uruchomić serwera: ${error.message}`); process.exit(1); });
  receiver.server.listen(port, '0.0.0.0', () => {
    console.log(`HALO test receiver · port ${port} · token pozostaw pusty`);
    for (const addresses of Object.values(networkInterfaces())) {
      for (const address of addresses ?? []) {
        if (address.family === 'IPv4' && !address.internal) {
          console.log(`Telefon: ws://${address.address}:${port}/ws/controller`);
          console.log(`Test w przeglądarce telefonu: http://${address.address}:${port}/health`);
        }
      }
    }
    console.log('Pełne wiadomości JSON pojawią się poniżej. Ctrl+C zatrzymuje serwer.');
  });
  for (const signal of ['SIGINT', 'SIGTERM']) process.once(signal, () => receiver.close());
}
