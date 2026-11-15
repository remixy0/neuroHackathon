// Real Swift URLSessionWebSocketTask client against the project's Node receiver.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { once } from 'node:events';
import { createReceiver } from '../../test-server/server.js';
const { WebSocketServer } = createRequire(new URL('../../test-server/package.json', import.meta.url))('ws');
const binary = process.argv[2];
if (!binary) throw new Error('Usage: node scripts/smoke.mjs /absolute/path/to/HaloSmoke');

async function client(port, mode) {
  const child = spawn(binary, [`ws://127.0.0.1:${port}/ws/controller`, mode], { timeout: 20000 });
  let output = '';
  child.stdout.on('data', chunk => { output += chunk; });
  child.stderr.on('data', chunk => { output += chunk; });
  const [code, signal] = await once(child, 'exit');
  assert.equal(code, 0, `${mode}: ${signal ?? ''}\n${output}`);
  assert.ok(output.includes(`PASS ${mode}`), output);
  console.log(output.trim());
}

const logs = [];
const receiver = createReceiver({ log: line => logs.push(line) });
receiver.server.listen(0, '127.0.0.1');
await once(receiver.server, 'listening');
try {
  await client(receiver.server.address().port, 'normal');
  const packets = logs.filter(line => line.startsWith('[RX] ')).map(line => JSON.parse(line.slice(5)));
  const hellos = packets.filter(packet => packet.type === 'hello');
  assert.deepEqual(hellos.map(packet => packet.player), [1, 2]);
  assert.notEqual(hellos[0].session_id, hellos[1].session_id);
  const buttons = packets.filter(packet => packet.type === 'manual');
  assert.deepEqual(buttons.slice(0, 9).map(packet => packet.button), ['up', 'down', 'left', 'right', 'a', 'b', 'x', 'select', 'start']);
  assert.deepEqual(buttons.slice(0, 9).map(packet => packet.seq), [0, 1, 2, 3, 4, 5, 6, 7, 8]);
  assert.equal(buttons[9].seq, 0);
  assert.equal(buttons[9].player, 2);
  assert.ok(!logs.some(line => line.startsWith('[ERROR]') || line.startsWith('[TIMEOUT]')), logs.join('\n'));
  const health = await fetch(`http://127.0.0.1:${receiver.server.address().port}/health`).then(response => response.json());
  assert.deepEqual(health.players, [], 'Closing the app must release both player leases');
} finally { await receiver.close(); }

for (const mode of ['no-ack', 'wrong-ready', 'rejected', 'wrong-session', 'no-ready']) {
  const server = new WebSocketServer({ host: '127.0.0.1', port: 0 });
  await once(server, 'listening');
  server.on('connection', socket => {
    socket.on('message', raw => {
      const message = JSON.parse(raw);
      const send = payload => socket.send(JSON.stringify({ version: 1, session_id: message.session_id, ...payload }));
      if (message.type === 'hello' && mode !== 'no-ready') {
        if (mode === 'rejected') send({ type: 'error', message: 'Player occupied' });
        else send({ type: 'ready', mode: mode === 'wrong-ready' ? 'eeg' : 'manual', player: message.player });
      }
      if (message.type === 'manual' && mode === 'wrong-session') send({ type: 'ack', session_id: 'wrong-session', seq: message.seq });
    });
  });
  try { await client(server.address().port, mode); }
  finally {
    for (const socket of server.clients) socket.terminate();
    await new Promise(resolve => server.close(resolve));
  }
}
console.log('All six native Swift integration scenarios passed.');
