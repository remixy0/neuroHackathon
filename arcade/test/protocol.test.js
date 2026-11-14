import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parse, createDeduper } from '../src/input/protocol.js';

test('canonical JSON', () => {
  assert.deepEqual(parse('{"player":2,"button":"left","state":"down"}'), [{ player: 2, button: 'left', state: 'down' }]);
  assert.deepEqual(parse('{"player":1,"button":"a"}'), [{ player: 1, button: 'a', state: 'tap' }]);
  assert.deepEqual(parse('{"player":2,"pos":0.25}'), [{ player: 2, pos: 0.25 }]);
});

test('text lines', () => {
  assert.deepEqual(parse('1 left down'), [{ player: 1, button: 'left', state: 'down' }]);
  assert.deepEqual(parse('P2 UP RELEASE'), [{ player: 2, button: 'up', state: 'up' }]);
  assert.deepEqual(parse('P1 DOWN TAP 300'), [{ player: 1, button: 'down', state: 'tap', ms: 300 }]);
  assert.deepEqual(parse('P2 RAW 512 1024'), [{ player: 2, pos: 0.5 }]);
  assert.deepEqual(parse('START'), [{ player: 1, button: 'start', state: 'tap' }]);
  assert.equal(parse('P1 UP PRESS\nP2 DOWN PRESS').length, 2);
});

test('old Tetris, Pong and HALO RUSH formats', () => {
  assert.deepEqual(parse('{"player":1,"action":"hard"}'), [{ player: 1, button: 'a', state: 'tap' }]);
  assert.deepEqual(parse('{"player":2,"action":"cw","state":"down"}'), [{ player: 2, button: 'up', state: 'down' }]);
  assert.deepEqual(parse('{"player":1,"button":"down","action":"press"}'), [{ player: 1, button: 'down', state: 'down' }]);
  assert.deepEqual(parse('{"type":"input","player":2,"direction":"góra","id":7}'), [{ player: 2, button: 'up', state: 'tap', id: 7 }]);
  assert.deepEqual(parse({ player: '1', button: 'start2' }), [{ player: 1, button: 'start', state: 'tap' }]);
});

test('rejects garbage and service messages', () => {
  for (const bad of ['', 'hello', '{"player":3,"button":"up"}', '{"type":"state","players":[]}', '{"player":1,"button":"jumpy"}', '{bad json']) {
    assert.deepEqual(parse(bad), []);
  }
});

test('dedupe by (player, id)', () => {
  const ok = createDeduper();
  const [a] = parse('{"type":"input","player":1,"direction":"left","id":1}');
  const [b] = parse('{"type":"input","player":2,"direction":"left","id":1}');
  assert.equal(ok(a), true);
  assert.equal(ok(a), false);
  assert.equal(ok(b), true);
});
