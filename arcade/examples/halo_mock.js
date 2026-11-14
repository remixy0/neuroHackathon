// Atrapa backendu HALO (rozpoznawanie gestów) – serwer WebSocket na porcie 8765, jak w oryginalnej grze z folderu subway.
// Serwer gry łączy się z nim jako klient, gdy uruchomisz grę ze zmienną ARCADE_UPSTREAM:
//
//   terminal 1:  npm run mock:halo
//   terminal 2:  set ARCADE_UPSTREAM=ws://localhost:8765 && npm run dev      (Windows cmd)
//                $env:ARCADE_UPSTREAM="ws://localhost:8765"; npm run dev     (PowerShell)
//
// Potem wpisuj tutaj np. "1 left", "2 up" i Enter.
import { WebSocketServer } from 'ws';
import readline from 'node:readline';

const wss = new WebSocketServer({ host: '127.0.0.1', port: 8765 });
console.log('HALO mock: ws://localhost:8765\nType e.g. 1 left or 2 up and press Enter. Ctrl+C quits.');
wss.on('connection', () => console.log('Game server connected.'));
let id = 0;
readline.createInterface({ input: process.stdin }).on('line', (line) => {
  const [p, direction] = line.trim().split(/\s+/);
  const player = Number(p);
  if (![1, 2].includes(player) || !['left', 'right', 'up', 'down'].includes(direction)) {
    console.log('Format: 1 left | 2 right | 1 up | 2 down');
    return;
  }
  const message = JSON.stringify({ type: 'input', player, direction, id: `mock:${++id}` });
  for (const client of wss.clients) if (client.readyState === 1) client.send(message);
});
wss.on('error', (error) => { console.error(error.message); process.exitCode = 1; });
