import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createTrack, createPlayer, command, advance } from '../src/games/runner/engine.js';

const LANES = [-1, 0, 1];
const trainAt = (track, lane, z) => track.some((t) => t.len && t.lane === lane && t.z <= z && z <= t.z + t.len);

test('same seed gives identical course', () => assert.deepEqual(createTrack(42), createTrack(42)));

test('every row can be passed: a free lane or a jump/slide option, never only trains', () => {
  for (const seed of [1, 2, 3, 99, 12345]) {
    const t = createTrack(seed);
    const rows = [...new Set(t.filter((x) => x.type !== 'coin').map((x) => x.z))];
    for (const z of rows) {
      const ok = LANES.some((l) => !trainAt(t, l, z) && !t.some((o) => o.z === z && o.lane === l && o.type === 'block'));
      assert.ok(ok, `seed ${seed}, row at ${z} is blocked in every lane`);
    }
  }
});

test('rows that force a jump or slide leave time to land before the next obstacle', () => {
  for (const seed of [1, 2, 3, 99, 12345]) {
    const t = createTrack(seed);
    const obstacles = t.filter((x) => x.type !== 'coin');
    const forcedRows = [...new Set(obstacles.map((o) => o.z))].filter((z) => LANES.every((l) => trainAt(t, l, z) || obstacles.some((o) => o.z === z && o.lane === l)));
    for (const z of forcedRows) {
      const next = obstacles.find((o) => o.z > z);
      if (next) assert.ok(next.z - z >= 16, `seed ${seed}: only ${next.z - z} units after forced row at ${z}`);
    }
  }
});

test('the course has all kinds of forced moves', () => {
  const t = createTrack(7);
  const rowTypes = (type) => [...new Set(t.filter((x) => x.type === type).map((x) => x.z))].filter((z) => t.filter((x) => x.z === z && x.type === type).length === 3);
  assert.ok(rowTypes('barrier').length > 3, 'full-width barriers (must jump)');
  assert.ok(rowTypes('gate').length > 3, 'full-width gates (must slide)');
  assert.ok(t.some((x) => x.len > 8), 'long trains');
});

test('lane bounds and independent players', () => {
  const a = createPlayer();
  const b = createPlayer();
  for (let i = 0; i < 4; i++) command(a, 'left');
  assert.equal(a.lane, -1);
  assert.equal(b.lane, 0);
});

test('jump clears barrier, slide clears gate, neither clears a train', () => {
  for (const [action, type] of [['up', 'barrier'], ['down', 'gate']]) {
    const p = createPlayer();
    command(p, action);
    advance(p, 0.35, 10, [{ z: 3.5, lane: 0, type }]);
    assert.equal(p.lives, 3);
  }
  const p = createPlayer();
  command(p, 'up');
  advance(p, 0.35, 10, [{ z: 3.5, lane: 0, type: 'block', len: 4 }]);
  assert.equal(p.lives, 2);
});

test('moving into the lane of a long train hits, one hit per train', () => {
  const track = [{ z: 0, lane: -1, type: 'block', len: 30 }];
  const p = createPlayer();
  advance(p, 0.5, 10, track); // jedziemy obok pociągu
  assert.equal(p.lives, 3);
  command(p, 'left');
  for (let i = 0; i < 10; i++) advance(p, 0.05, 10, track);
  assert.equal(p.lives, 2);
  for (let i = 0; i < 10; i++) advance(p, 0.05, 10, track);
  assert.equal(p.lives, 2);
});

test('coins count once, eliminated player freezes', () => {
  const p = createPlayer();
  const t = [{ z: 1, lane: 0, type: 'coin' }];
  advance(p, 0.1, 10, t);
  advance(p, 0.1, 10, t);
  assert.equal(p.coins, 1);
  p.alive = false;
  const d = p.distance;
  advance(p, 1, 10, t);
  assert.equal(p.distance, d);
});
