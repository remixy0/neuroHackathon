// RUNNER – grafika 3D w stylu pozostałych gier: czarne tło, płaskie bryły w kolorach klocków
// z Tetrisa i niska rozdzielczość (224×168) powiększana bez wygładzania, jak na starej konsoli.
import * as THREE from 'three';
import { LANE_WIDTH, jumpHeight, rng } from './engine.js';

const VIEW_W = 224;
const VIEW_H = 168;

export const C = {
  cyan: 0x1fc8e8, yellow: 0xf2cf1d, purple: 0xa64fd6, green: 0x4cc24a, red: 0xe5403a,
  blue: 0x3a64e0, orange: 0xef8a26, grey: 0x6b6b6b, white: 0xececec,
};
const PIECE_COLORS = [C.cyan, C.yellow, C.purple, C.green, C.red, C.blue, C.orange];

const solid = new Map();
const glow = new Map();
const mat = (color) => {
  if (!solid.has(color)) solid.set(color, new THREE.MeshLambertMaterial({ color, flatShading: true }));
  return solid.get(color);
};
const lit = (color) => {
  if (!glow.has(color)) glow.set(color, new THREE.MeshBasicMaterial({ color }));
  return glow.get(color);
};
const cube = new THREE.BoxGeometry(1, 1, 1);
const coinGeometry = new THREE.OctahedronGeometry(0.36, 0);

function box(parent, material, x, y, z, w, h, d) {
  const m = new THREE.Mesh(cube, material);
  m.position.set(x, y, z);
  m.scale.set(w, h, d);
  parent.add(m);
  return m;
}

export class View {
  constructor(canvas, accent, seed) {
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: false, powerPreference: 'high-performance' });
    this.renderer.setPixelRatio(1);
    this.renderer.setSize(VIEW_W, VIEW_H, false);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;

    const scene = new THREE.Scene();
    this.scene = scene;
    scene.background = new THREE.Color(0x000000);
    scene.fog = new THREE.Fog(0x000000, 28, 100);
    this.camera = new THREE.PerspectiveCamera(53, VIEW_W / VIEW_H, 0.1, 220);
    this.camera.position.set(0, 6.3, 9.5);
    this.camera.lookAt(0, 1, -16);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x303030, 1.9));
    const sun = new THREE.DirectionalLight(0xffffff, 1.5);
    sun.position.set(-8, 14, 10);
    scene.add(sun);

    // podłoże i tor
    box(scene, mat(0x0a0a0a), 0, -0.55, -55, 100, 0.5, 170);
    box(scene, mat(0x171717), 0, -0.25, -55, 7.4, 0.5, 170);

    // gwiazdy – pojedyncze piksele
    const random = rng(seed);
    const starPos = [];
    for (let i = 0; i < 70; i++) starPos.push((random() - 0.5) * 220, 12 + random() * 40, -70 - random() * 90);
    this.starGeometry = new THREE.BufferGeometry();
    this.starGeometry.setAttribute('position', new THREE.Float32BufferAttribute(starPos, 3));
    const stars = new THREE.Points(this.starGeometry, new THREE.PointsMaterial({ color: C.white, size: 1, sizeAttenuation: false, fog: false }));
    scene.add(stars);

    // przerywane linie między pasami i "cegiełki" wzdłuż toru, jak ściany studni w Tetrisie
    this.markers = new THREE.Group();
    scene.add(this.markers);
    for (let i = 0; i < 45; i++) {
      for (const x of [-LANE_WIDTH / 2, LANE_WIDTH / 2]) box(this.markers, lit(0x8c8c8c), x, 0.02, -i * 4, 0.08, 0.02, 1.4);
    }
    this.walls = new THREE.Group();
    scene.add(this.walls);
    for (let i = 0; i < 90; i++) {
      for (const x of [-3.85, 3.85]) box(this.walls, mat(i % 2 ? C.grey : C.white), x, 0.12, -i * 2, 0.3, 0.45, 1.75);
    }

    // miasto: ciemne bloki z zapalonymi oknami
    this.city = new THREE.Group();
    scene.add(this.city);
    for (let i = 0; i < 34; i++) {
      const side = i % 2 ? 1 : -1;
      const g = new THREE.Group();
      const h = 3 + random() * 4.5;
      const w = 3 + random() * 1.5;
      g.position.x = side * (8 + random() * 2);
      this.city.add(g);
      box(g, mat([0x1c1c1c, 0x242424, 0x2c2c2c][i % 3]), 0, h / 2, 0, w, h, 4.8);
      box(g, mat(0x3a3a3a), 0, h + 0.1, 0, w + 0.2, 0.2, 5);
      const face = -side * (w / 2 + 0.02);
      for (let y = 1.2; y < h - 0.4; y += 1.3) {
        for (const z of [-1.5, 0, 1.5]) {
          if (random() < 0.45) continue;
          const color = random() < 0.25 ? PIECE_COLORS[Math.floor(random() * 7)] : 0xe8dfb8;
          box(g, lit(color), face, y, z, 0.04, 0.6, 0.7);
        }
      }
    }

    // bramownice z kolorowymi lampkami
    this.arches = new THREE.Group();
    scene.add(this.arches);
    for (let i = 0; i < 5; i++) {
      const g = new THREE.Group();
      this.arches.add(g);
      for (const x of [-4.5, 4.5]) box(g, mat(C.grey), x, 2.8, 0, 0.25, 5.6, 0.25);
      box(g, mat(C.grey), 0, 5.6, 0, 9.25, 0.3, 0.3);
      for (let j = 0; j < 7; j++) box(g, lit(PIECE_COLORS[j]), (j - 3) * 1.2, 5.25, 0.1, 0.35, 0.35, 0.1);
    }

    // biegacz z klocków
    this.runner = new THREE.Group();
    scene.add(this.runner);
    this.body = new THREE.Group();
    this.runner.add(this.body);
    const dark = mat(0x2a2a2a);
    box(this.body, mat(accent), 0, 1.07, 0, 0.8, 0.85, 0.55);
    box(this.body, dark, 0, 0.62, 0, 0.7, 0.22, 0.5);
    box(this.body, mat(C.white), 0, 1.82, 0, 0.52, 0.5, 0.46);
    box(this.body, mat(accent), 0, 2.1, 0, 0.56, 0.12, 0.5);
    box(this.body, mat(C.white), 0, 1.12, 0.36, 0.5, 0.55, 0.18);
    this.legs = [];
    this.arms = [];
    for (const side of [-1, 1]) {
      const leg = new THREE.Group();
      leg.position.set(side * 0.2, 0.62, 0);
      this.body.add(leg);
      box(leg, dark, 0, -0.22, 0, 0.28, 0.48, 0.3);
      box(leg, mat(C.white), 0, -0.5, -0.06, 0.32, 0.16, 0.44);
      this.legs.push(leg);
      const arm = new THREE.Group();
      arm.position.set(side * 0.52, 1.38, 0);
      this.body.add(arm);
      box(arm, mat(accent), 0, -0.2, 0, 0.22, 0.48, 0.24);
      box(arm, mat(C.white), 0, -0.48, 0, 0.2, 0.16, 0.2);
      this.arms.push(arm);
    }

    this.objects = new Map();
    this.track = [];
  }

  reset(track) {
    for (const o of this.objects.values()) this.scene.remove(o);
    this.objects.clear();
    this.track = track;
  }

  make(item) {
    const g = new THREE.Group();
    g.position.x = item.lane * LANE_WIDTH;
    if (item.type === 'coin') {
      const coin = new THREE.Mesh(coinGeometry, lit(C.yellow));
      coin.position.y = 1;
      g.add(coin);
    }
    if (item.type === 'block') {
      // pociąg: zmień pas. Przód w z = 0, ciągnie się w głąb toru na długość len
      const len = item.len || 4;
      const mid = -len / 2;
      box(g, mat(C.blue), 0, 1.4, mid, 1.95, 2.8, len);
      box(g, mat(0x2a4aa8), 0, 2.88, mid, 2, 0.16, len + 0.05);
      box(g, lit(C.white), 0, 2.05, 0.01, 1.5, 0.45, 0.05);
      box(g, lit(C.yellow), 0, 0.7, 0.01, 1.4, 0.12, 0.05);
      for (let z = -1; z > -len + 0.5; z -= 1.6) {
        for (const x of [-0.99, 0.99]) box(g, lit(0xbfd4ff), x, 2.0, z, 0.03, 0.5, 0.9);
      }
      for (const x of [-0.95, 0.95]) for (let z = -0.8; z > -len; z -= 2.4) box(g, mat(0x111111), x, 0.25, z, 0.15, 0.4, 0.5);
    }
    if (item.type === 'barrier') {
      // niski płotek: przeskocz
      box(g, mat(C.red), 0, 0.6, 0, 1.95, 0.75, 0.3);
      for (const x of [-0.6, 0, 0.6]) box(g, mat(C.white), x, 0.6, 0.02, 0.24, 0.75, 0.3);
      for (const x of [-0.8, 0.8]) box(g, mat(C.grey), x, 0.12, 0, 0.18, 0.25, 0.6);
    }
    if (item.type === 'gate') {
      // wysoka belka: wślizgnij się pod spód
      for (const x of [-0.9, 0.9]) box(g, mat(C.purple), x, 1.5, 0, 0.2, 3, 0.3);
      box(g, mat(C.purple), 0, 2.25, 0, 1.95, 1, 0.4);
      box(g, lit(C.white), 0, 2.4, 0.21, 0.12, 0.45, 0.02);
      for (const s of [-1, 1]) box(g, lit(C.white), s * 0.12, 2.12, 0.21, 0.12, 0.12, 0.02);
      box(g, lit(C.white), 0, 2.0, 0.21, 0.12, 0.12, 0.02);
    }
    this.scene.add(g);
    return g;
  }

  render(p, time) {
    this.markers.position.z = p.distance % 4;
    this.walls.position.z = p.distance % 4;
    this.city.children.forEach((b, i) => { b.position.z = 12 - ((Math.floor(i / 2) * 9 - (p.distance % 153) + 153) % 153); });
    this.arches.children.forEach((b, i) => { b.position.z = 10 - ((i * 30 - (p.distance % 150) + 150) % 150); });
    this.track.forEach((item, i) => {
      const z = p.distance - item.z;
      if (z < -105 || z - (item.len || 0) > 9 || (p.seen.has(i) && item.type === 'coin')) {
        if (this.objects.has(i)) { this.scene.remove(this.objects.get(i)); this.objects.delete(i); }
        return;
      }
      let obj = this.objects.get(i);
      if (!obj) { obj = this.make(item); this.objects.set(i, obj); }
      obj.position.z = z;
      if (item.type === 'coin') obj.children[0].rotation.y = time * 3;
    });
    this.runner.position.set(p.x, jumpHeight(p), 0);
    this.runner.visible = p.alive && !(p.invulnerable > 0 && Math.floor(time * 12) % 2);
    this.body.scale.set(p.slide > 0 ? 1.12 : 1, p.slide > 0 ? 0.42 : 1, p.slide > 0 ? 1.3 : 1);
    this.body.rotation.z = (p.lane * LANE_WIDTH - p.x) * -0.13;
    const stride = p.alive && p.jump <= 0 && p.slide <= 0 ? Math.sin(time * 17) * 0.65 : 0;
    this.legs.forEach((l, i) => { l.rotation.x = stride * (i ? 1 : -1); });
    this.arms.forEach((l, i) => { l.rotation.x = stride * (i ? -1 : 1); });
    this.renderer.render(this.scene, this.camera);
  }

  dispose() {
    this.starGeometry.dispose();
    this.renderer.dispose();
  }
}
