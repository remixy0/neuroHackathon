import { test } from 'node:test';
import assert from 'node:assert/strict';
import { once } from 'node:events';
import { WebSocket } from 'ws';
import { createReceiver } from './server.js';

const hello = (session = 'test', player = 1) => ({
  type: 'hello', version: 1, session_id: session, role: 'controller', player,
  device: { name: 'HALO test' },
  stream: { channels: ['O1', 'O2', 'Fp2', 'Fp1'], sample_rate_hz: 250,
    layout: 'sample_major', has_accel: true, has_gyro: false },
});
const samples = seq => ({
  type: 'samples', version: 1, session_id: 'test', seq, sample_count: 1,
  first_sample_index: String(seq), host_time_ns: '123456789012345', wire_last_sample_index: String(seq),
  eeg: [1, 2, 3, 4], accel: [0, 0, 9.81], gyro: null,
  is_dummy: [false], contact: [true, true, true, true], battery_pct: 80,
  phone_discarded_samples: '0', ble_missed_samples: '0',
});

async function setup(t) {
  const logs = [];
  const receiver = createReceiver({ log: line => logs.push(line) });
  receiver.server.listen(0, '127.0.0.1');
  await once(receiver.server, 'listening');
  t.after(() => receiver.close());
  const base = `127.0.0.1:${receiver.server.address().port}`;
  const connect = async () => {
    const ws = new WebSocket(`ws://${base}/ws/controller`);
    await once(ws, 'open');
    return ws;
  };
  return { logs, connect, health: async () => (await fetch(`http://${base}/health`)).json() };
}

async function exchange(ws, data) {
  const response = once(ws, 'message');
  ws.send(JSON.stringify(data));
  return JSON.parse((await response)[0].toString());
}

test('Android hello, repeated samples, full logs, health and stop', { timeout: 5000 }, async t => {
  const { connect, health, logs } = await setup(t);
  assert.deepEqual((await health()).players, []);
  const ws = await connect();
  assert.deepEqual(await exchange(ws, hello()), { type: 'ready', version: 1, session_id: 'test', player: 1 });
  for (let seq = 0; seq < 20; seq++) {
    assert.deepEqual(await exchange(ws, samples(seq)), { type: 'ack', version: 1, session_id: 'test', seq });
  }
  assert.ok(logs.includes(`[RX] ${JSON.stringify(samples(19))}`));
  assert.deepEqual((await health()).players, [1]);
  const closed = once(ws, 'close');
  ws.send(JSON.stringify({ type: 'stop', version: 1, session_id: 'test', reason: 'user_or_lifecycle' }));
  assert.equal((await closed)[0], 1000);
  assert.deepEqual((await health()).players, []);
});

test('occupied player rejected; disconnect releases the player for a new session', { timeout: 5000 }, async t => {
  const { connect, health } = await setup(t);
  const first = await connect();
  await exchange(first, hello());
  const second = await connect();
  assert.equal((await exchange(second, hello('second'))).code, 'player_busy');
  assert.deepEqual((await health()).players, [1]);
  const closed = once(first, 'close');
  first.close();
  await closed;
  const third = await connect();
  assert.equal((await exchange(third, hello('third'))).type, 'ready');
});

test('malformed samples rejected without crashing the server', { timeout: 5000 }, async t => {
  const { connect, health } = await setup(t);
  const ws = await connect();
  await exchange(ws, hello());
  const response = await exchange(ws, { ...samples(0), eeg: [1] });
  assert.equal(response.type, 'error');
  assert.equal(response.session_id, 'test');
  assert.equal((await health()).status, 'ok');
});

const manualHello = (session = 'test', player = 1) => ({
  type: 'hello', version: 1, session_id: session, role: 'controller', mode: 'manual', player,
});
const manual = (seq, button = 'a', player = 1) => ({
  type: 'manual', version: 1, session_id: 'test', seq, id: `test:${seq}`, player, button, action: 'press',
});

test('manual handshake without HALO, all buttons acknowledged and logged once', { timeout: 5000 }, async t => {
  const { connect, logs } = await setup(t);
  const ws = await connect();
  assert.deepEqual(await exchange(ws, manualHello()), { type: 'ready', version: 1, session_id: 'test', player: 1, mode: 'manual' });
  const buttons = ['up', 'down', 'left', 'right', 'a', 'b', 'x', 'select', 'start'];
  for (const [seq, button] of buttons.entries()) {
    assert.deepEqual(await exchange(ws, manual(seq, button)), { type: 'ack', version: 1, session_id: 'test', seq });
  }
  assert.equal(logs.filter(line => line.startsWith('[MANUAL]')).length, 9);
  assert.equal((await exchange(ws, manual(8, 'start'))).type, 'error');
  assert.equal(logs.filter(line => line.startsWith('[MANUAL]')).length, 9); // duplicate was not applied
});

for (const [name, change] of [
  ['other player', { player: 2 }], ['unknown button', { button: 'fire' }],
  ['unknown action', { action: 'hold' }], ['wrong event id', { id: 'unrelated' }],
]) {
  test(`manual rejects ${name}`, { timeout: 5000 }, async t => {
    const { connect, logs } = await setup(t);
    const ws = await connect();
    await exchange(ws, manualHello());
    assert.equal((await exchange(ws, { ...manual(0), ...change })).type, 'error');
    assert.equal(logs.filter(line => line.startsWith('[MANUAL]')).length, 0);
  });
}

test('EEG and manual can coexist on different players; modes cannot mix in one session', { timeout: 5000 }, async t => {
  const { connect, health } = await setup(t);
  const eeg = await connect();
  await exchange(eeg, hello('eeg', 1));
  const pad = await connect();
  assert.equal((await exchange(pad, manualHello('test', 2))).mode, 'manual');
  assert.deepEqual((await health()).players, [1, 2]);
  const extra = await connect();
  assert.equal((await exchange(extra, manualHello('extra', 1))).code, 'player_busy');
  assert.equal((await exchange(pad, manual(0, 'left', 2))).type, 'ack');
  assert.equal((await exchange(pad, samples(1))).type, 'error');
  assert.equal((await exchange(eeg, { ...manual(0), session_id: 'eeg', id: 'eeg:0' })).type, 'error');
});

test('idle manual pad stays connected through transport ping and expires without it', { timeout: 5000 }, async t => {
  const receiver = createReceiver({ log: () => {}, idleTimeoutMs: 200 });
  receiver.server.listen(0, '127.0.0.1');
  await once(receiver.server, 'listening');
  t.after(() => receiver.close());
  const ws = new WebSocket(`ws://127.0.0.1:${receiver.server.address().port}/ws/controller`);
  await once(ws, 'open');
  await exchange(ws, manualHello());
  const timer = setInterval(() => ws.ping(), 40);
  t.after(() => clearInterval(timer));
  await new Promise(resolve => setTimeout(resolve, 650));
  assert.equal((await exchange(ws, manual(0))).type, 'ack');
  const closed = once(ws, 'close');
  clearInterval(timer);
  await closed;
});
