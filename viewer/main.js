// =============================================================================
// GIS-Based 3D Landslide Hazard Visualization - Three.js viewer (v2).
//
// Features over v1:
//   - 4 rainfall scenarios (Dry / Normal / Wet / Extreme)
//   - Drainage network layer (D8 flow accumulation)
//   - 3D OSM buildings (extruded) + road overlays (textured ribbons)
//   - Camera presets (Oblique / Top / Side) + screenshot export
//   - Exposure stats refresh per active scenario
// =============================================================================
import * as THREE from 'three';
import { OrbitControls } from './lib/OrbitControls.js';

const DATA = './data';
const BUILDING_FOOTPRINT_SCALE = 4.5;     // widen footprint so schools read at overview zoom
const BUILDING_BODY_HEIGHT     = 4.0;     // world units, body box height
const BUILDING_ROOF_HEIGHT     = 1.8;     // pitched-roof ridge height
const BUILDING_BASE_HEIGHT     = 0.25;    // small base trim
const BUILDING_FLAG_HEIGHT     = 5.0;     // tiny flagpole on top - locator at distance
const ROAD_WIDTH_M = 28.0;
const ROAD_Y_OFFSET = 0.6;
const WATERWAY_WIDTH_M = 14.0;
const WATERWAY_Y_OFFSET = 0.3;
const WATERWAY_COLOR = 0x4ec3ff;

// Procedural schoolhouse colours (warm cream + terracotta).
const SCHOOL_COLORS = {
  body: 0xf4ecd6,
  roof: 0xbc4b2b,
  base: 0x3a3328,
  flagPole: 0xeeeeee,
  flag: 0xff5a5a,
};
const NORMAL_ZOOM_SPEED = 0.45;
const PRECISION_ZOOM_SPEED = 0.10;         // when Ctrl is held
const TREE_TARGET_COUNT = 2400;
const TREE_MAX_SLOPE_DEG = 35;
const DETAIL_DISTANCE = 130;               // < this -> show building close-up details
const LABEL_DISTANCE  = 110;               // < this -> show feature name labels

// --- Live runout simulation (particle system) ------------------------------
const SIM_PARTICLE_COUNT = 1200;
const SIM_SOURCE_SLOPE_MIN = 28;           // deg - where new particles spawn
const SIM_DEPOSIT_SLOPE = 8;               // deg - stop & deposit below this
const SIM_VEL_DAMP = 0.92;
const SIM_VEL_GAIN = 0.018;                // accelerator scaling
const SIM_MAX_AGE = 280;                   // frames before forced respawn
const PRESETS = {
  oblique: { pos: [180, 130, 220], target: [0, 25, 0] },
  top:     { pos: [0, 360, 0.1],   target: [0, 0, 0] },
  side:    { pos: [0, 60, 320],    target: [0, 25, 0] },
};

let renderer, scene, camera, controls, dirLight;
let terrainGroup, terrainMesh, skirtMesh, markerGroup;
let featuresGroup, buildingsGroup, roadsGroup, treesGroup;
let waterwaysGroup, environmentGroup;            // streams + POIs/peaks/labels
let boundariesGroup;                             // admin boundary walls
let leafletMap;                                  // 2D minimap (Leaflet)
let meta, elevations, features = null;
let worldScale = 1;
let currentScenario = 'normal';
let activeLayerId = 'hillshade';
const layerTextures = {};                  // shared layer textures
const scenarioTextures = {};               // {scenarioId: {susc: tex, runout: tex}}
const buildingLODs = [];                   // for distance-based detail toggling
const labels = [];                         // {sprite, worldPos} for zoom-aware labels

// Particle simulation state
let simPoints, simPositions, simColors;
const particles = [];
let simRunning = false;
let simFrame = 0;
let simSlopeGrid = null;                   // precomputed slope (deg) per cell

// Trees on/off toggle (button). Plain = trees hidden. Independent of the
// hazard-layer selection - layers always work whether trees are shown or not.
let plainMode = true;
let plainTerrainMat, texturedTerrainMat;

init().catch(err => {
  console.error(err);
  document.getElementById('loader-text').textContent =
    'Failed to load model. Make sure you started a local server in the project '
    + 'root (python -m http.server 8000) and opened http://localhost:8000/viewer/';
});

async function init() {
  renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  document.getElementById('scene').appendChild(renderer.domElement);

  scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0x9ec5e8, 480, 1100);

  camera = new THREE.PerspectiveCamera(
    45, window.innerWidth / window.innerHeight, 0.5, 2500);
  applyPreset('oblique');

  // Sky gradient via a back-faced sphere with a custom shader.
  addSky();

  scene.add(new THREE.HemisphereLight(0xbcd6f5, 0x3a2e1c, 0.85));
  dirLight = new THREE.DirectionalLight(0xffffff, 1.05);
  dirLight.castShadow = true;
  dirLight.shadow.mapSize.set(2048, 2048);
  const sd = 160;
  dirLight.shadow.camera.left = -sd;
  dirLight.shadow.camera.right = sd;
  dirLight.shadow.camera.top = sd;
  dirLight.shadow.camera.bottom = -sd;
  dirLight.shadow.camera.near = 30;
  dirLight.shadow.camera.far = 800;
  dirLight.shadow.bias = -0.0003;
  dirLight.shadow.normalBias = 0.02;
  scene.add(dirLight);
  setSunAzimuth(315);

  controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0, 25, 0);
  controls.enableDamping = true;
  controls.dampingFactor = 0.12;
  controls.zoomSpeed = NORMAL_ZOOM_SPEED;
  controls.zoomToCursor = true;     // zoom toward where the mouse points
  controls.rotateSpeed = 0.7;
  controls.panSpeed = 0.8;
  controls.minDistance = 40;
  controls.maxDistance = 800;
  controls.maxPolarAngle = Math.PI * 0.49;

  // Hold Ctrl for precision (slow) zoom. Also suppresses the browser's
  // built-in Ctrl+wheel page-zoom while the cursor is over the viewer.
  const setZoom = (slow) => {
    if (controls) controls.zoomSpeed = slow ? PRECISION_ZOOM_SPEED : NORMAL_ZOOM_SPEED;
    document.getElementById('precision-indicator')?.classList.toggle('on', slow);
  };
  window.addEventListener('keydown', (e) => { if (e.key === 'Control') setZoom(true); });
  window.addEventListener('keyup',   (e) => { if (e.key === 'Control') setZoom(false); });
  window.addEventListener('blur',    () => setZoom(false));
  renderer.domElement.addEventListener('wheel', (e) => {
    if (e.ctrlKey) e.preventDefault();    // stop the browser's page-zoom
  }, { passive: false });

  meta = await fetch(`${DATA}/terrain.json`).then(r => r.json());
  const binBuf = await fetch(`${DATA}/terrain.bin`).then(r => r.arrayBuffer());
  elevations = new Float32Array(binBuf);

  // Prepend a "Plain" pseudo-layer so users can pick pure-white terrain.
  // Default active layer = plain, so first paint is white as requested.
  meta.layers.unshift({
    id: 'plain',
    name: 'Plain (white)',
    description: 'Pure white terrain - schematic massing without any hazard overlay.',
  });
  activeLayerId = 'plain';

  const loader = new THREE.TextureLoader();
  async function loadTex(name) {
    const t = await loader.loadAsync(`${DATA}/${name}`);
    t.colorSpace = THREE.SRGBColorSpace;
    t.anisotropy = 8;
    return t;
  }

  // Shared layer textures + per-scenario textures. 'plain' has neither.
  for (const L of meta.layers) {
    if (L.texture) {
      layerTextures[L.id] = await loadTex(L.texture);
    } else if (L.scenarioTextures) {
      layerTextures[L.id] = null;           // scenario-driven
    }
  }
  for (const sc of meta.scenarios) {
    const sid = sc.id;
    scenarioTextures[sid] = {
      susc: await loadTex(`tex_susc_${sid}.png`),
      runout: await loadTex(`tex_runout_${sid}.png`),
    };
  }

  if (meta.features_url) {
    try {
      features = await fetch(`${DATA}/${meta.features_url}`).then(r => r.json());
    } catch (e) {
      console.warn('Could not load features.json:', e);
    }
  }

  if (meta.default_scenario) currentScenario = meta.default_scenario;
  buildTerrain();
  buildSkirt();
  buildTrees();
  if (features) {
    buildFeatures();
    buildWaterways();
    buildEnvironmentFeatures();
    buildBoundaries();
  }
  buildMarker();
  buildSimulation();
  buildMinimap();
  if (treesGroup) treesGroup.visible = !plainMode;
  buildUI();
  setLayer(activeLayerId);
  setScenario(currentScenario);
  applyExaggeration(meta.vertical_exaggeration);

  window.addEventListener('resize', onResize);
  document.getElementById('loader').style.display = 'none';
  animate();
}

// ---------------------------------------------------------------------------
// Terrain
// ---------------------------------------------------------------------------
function buildTerrain() {
  const W = meta.generated_grid.width;
  const H = meta.generated_grid.height;
  const cx = meta.cell_x_m, cy = meta.cell_y_m;
  const minE = meta.elev_min;
  worldScale = 200 / Math.max((W - 1) * cx, (H - 1) * cy);

  const positions = new Float32Array(W * H * 3);
  const uvs = new Float32Array(W * H * 2);
  for (let r = 0; r < H; r++) {
    for (let c = 0; c < W; c++) {
      const i = r * W + c;
      positions[i * 3 + 0] = (c - (W - 1) / 2) * cx * worldScale;
      positions[i * 3 + 1] = (elevations[i] - minE) * worldScale;
      positions[i * 3 + 2] = (r - (H - 1) / 2) * cy * worldScale;
      uvs[i * 2 + 0] = c / (W - 1);
      uvs[i * 2 + 1] = 1 - r / (H - 1);
    }
  }
  const indices = new Uint32Array((W - 1) * (H - 1) * 6);
  let k = 0;
  for (let r = 0; r < H - 1; r++) {
    for (let c = 0; c < W - 1; c++) {
      const a = r * W + c, b = a + 1, d = a + W, e2 = d + 1;
      indices[k++] = a; indices[k++] = d; indices[k++] = b;
      indices[k++] = b; indices[k++] = d; indices[k++] = e2;
    }
  }
  const geom = new THREE.BufferGeometry();
  geom.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geom.setAttribute('uv', new THREE.BufferAttribute(uvs, 2));
  geom.setIndex(new THREE.BufferAttribute(indices, 1));
  geom.computeVertexNormals();

  texturedTerrainMat = new THREE.MeshStandardMaterial({
    map: null, roughness: 0.95, metalness: 0.0, side: THREE.DoubleSide,
  });
  plainTerrainMat = new THREE.MeshStandardMaterial({
    color: 0xffffff, roughness: 0.85, metalness: 0.0, side: THREE.DoubleSide,
  });
  terrainMesh = new THREE.Mesh(geom, plainMode ? plainTerrainMat : texturedTerrainMat);
  terrainMesh.receiveShadow = true;
  terrainMesh.castShadow = true;
  terrainGroup = new THREE.Group();
  terrainGroup.add(terrainMesh);
  scene.add(terrainGroup);
}

// ---------------------------------------------------------------------------
// Sky - vertical gradient via a back-faced sphere with a shader material.
// ---------------------------------------------------------------------------
function addSky() {
  const vertex = `
    varying vec3 vWorld;
    void main() {
      vWorld = (modelMatrix * vec4(position, 1.0)).xyz;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }`;
  const fragment = `
    uniform vec3 topColor;
    uniform vec3 bottomColor;
    uniform float offset;
    uniform float exponent;
    varying vec3 vWorld;
    void main() {
      float h = normalize(vWorld + vec3(0.0, offset, 0.0)).y;
      gl_FragColor = vec4(mix(bottomColor, topColor,
                              pow(max(h, 0.0), exponent)), 1.0);
    }`;
  const uniforms = {
    topColor:    { value: new THREE.Color(0x3a7fc0) },
    bottomColor: { value: new THREE.Color(0xe8edf2) },
    offset:      { value: 28 },
    exponent:    { value: 0.68 },
  };
  const sky = new THREE.Mesh(
    new THREE.SphereGeometry(1500, 32, 16),
    new THREE.ShaderMaterial({ uniforms, vertexShader: vertex,
                               fragmentShader: fragment, side: THREE.BackSide }));
  scene.add(sky);
}

// ---------------------------------------------------------------------------
// Instanced low-poly trees on flatter slopes - environmental realism.
// ---------------------------------------------------------------------------
function buildTrees() {
  const W = meta.generated_grid.width;
  const H = meta.generated_grid.height;
  const cx = meta.cell_x_m, cy = meta.cell_y_m;
  const minE = meta.elev_min;

  // Approximate slope (degrees) at each cell from 4-neighbour differences.
  const slopeDeg = new Float32Array(W * H);
  for (let r = 1; r < H - 1; r++) {
    for (let c = 1; c < W - 1; c++) {
      const dzdx = (elevations[r * W + c + 1] - elevations[r * W + c - 1]) / (2 * cx);
      const dzdy = (elevations[(r + 1) * W + c] - elevations[(r - 1) * W + c]) / (2 * cy);
      slopeDeg[r * W + c] = Math.atan(Math.hypot(dzdx, dzdy)) * 180 / Math.PI;
    }
  }

  // Pick a random set of cells on plant-friendly slopes.
  const picks = [];
  let tries = 0;
  while (picks.length < TREE_TARGET_COUNT && tries < TREE_TARGET_COUNT * 10) {
    tries++;
    const r = 2 + Math.floor(Math.random() * (H - 4));
    const c = 2 + Math.floor(Math.random() * (W - 4));
    if (slopeDeg[r * W + c] > TREE_MAX_SLOPE_DEG) continue;
    picks.push({
      r, c,
      jitter: [(Math.random() - 0.5) * cx * 0.7, (Math.random() - 0.5) * cy * 0.7],
      scale: 0.7 + Math.random() * 0.7,
      rot: Math.random() * Math.PI * 2,
    });
  }

  // Two InstancedMeshes (trunk + crown) sharing the picks array.
  const trunkGeo = new THREE.CylinderGeometry(0.07, 0.10, 0.9, 6);
  const crownGeo = new THREE.ConeGeometry(0.55, 1.4, 8);
  const trunkMat = new THREE.MeshStandardMaterial({
    color: 0x4a3219, roughness: 0.95 });
  const crownMat = new THREE.MeshStandardMaterial({
    color: 0x2e7a3e, roughness: 0.85 });
  const trunkMesh = new THREE.InstancedMesh(trunkGeo, trunkMat, picks.length);
  const crownMesh = new THREE.InstancedMesh(crownGeo, crownMat, picks.length);
  trunkMesh.castShadow = crownMesh.castShadow = true;
  trunkMesh.receiveShadow = crownMesh.receiveShadow = true;

  const m = new THREE.Matrix4();
  const q = new THREE.Quaternion();
  const p = new THREE.Vector3();
  const s = new THREE.Vector3();
  const Y_AX = new THREE.Vector3(0, 1, 0);
  for (let i = 0; i < picks.length; i++) {
    const t = picks[i];
    const wx = (t.c - (W - 1) / 2) * cx * worldScale + t.jitter[0] * worldScale;
    const wz = (t.r - (H - 1) / 2) * cy * worldScale + t.jitter[1] * worldScale;
    const wy = (elevations[t.r * W + t.c] - minE) * worldScale;

    q.setFromAxisAngle(Y_AX, t.rot);
    s.set(t.scale, t.scale, t.scale);
    // Trunk: pivot is at its centre -> raise by 0.45*scale so base sits at wy.
    p.set(wx, wy + 0.45 * t.scale, wz);
    m.compose(p, q, s);
    trunkMesh.setMatrixAt(i, m);
    // Crown sits above the trunk.
    p.set(wx, wy + (0.9 + 0.7) * t.scale, wz);
    m.compose(p, q, s);
    crownMesh.setMatrixAt(i, m);
  }
  trunkMesh.instanceMatrix.needsUpdate = true;
  crownMesh.instanceMatrix.needsUpdate = true;

  treesGroup = new THREE.Group();
  treesGroup.add(trunkMesh);
  treesGroup.add(crownMesh);
  terrainGroup.add(treesGroup);
  console.log(`Planted ${picks.length} trees`);
}

function buildSkirt() {
  const W = meta.generated_grid.width;
  const H = meta.generated_grid.height;
  const pos = terrainMesh.geometry.attributes.position;
  const baseY = -8;

  const edge = [];
  for (let c = 0; c < W; c++) edge.push(c);
  for (let r = 1; r < H; r++) edge.push(r * W + (W - 1));
  for (let c = W - 2; c >= 0; c--) edge.push((H - 1) * W + c);
  for (let r = H - 2; r > 0; r--) edge.push(r * W);

  const N = edge.length;
  const positions = new Float32Array(N * 2 * 3);
  for (let i = 0; i < N; i++) {
    const idx = edge[i];
    positions[i * 6 + 0] = pos.getX(idx); positions[i * 6 + 1] = pos.getY(idx); positions[i * 6 + 2] = pos.getZ(idx);
    positions[i * 6 + 3] = pos.getX(idx); positions[i * 6 + 4] = baseY;         positions[i * 6 + 5] = pos.getZ(idx);
  }
  const indices = [];
  for (let i = 0; i < N; i++) {
    const j = (i + 1) % N;
    indices.push(i * 2, i * 2 + 1, j * 2, j * 2, i * 2 + 1, j * 2 + 1);
  }
  const geom = new THREE.BufferGeometry();
  geom.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geom.setIndex(indices);
  geom.computeVertexNormals();
  const mat = new THREE.MeshStandardMaterial({ color: 0x3a3328, roughness: 1.0 });
  skirtMesh = new THREE.Mesh(geom, mat);
  skirtMesh.receiveShadow = true;
  terrainGroup.add(skirtMesh);
}

function elevAt(rowF, colF) {
  const W = meta.generated_grid.width, H = meta.generated_grid.height;
  const r0 = Math.max(0, Math.min(H - 2, Math.floor(rowF)));
  const c0 = Math.max(0, Math.min(W - 2, Math.floor(colF)));
  const dr = rowF - r0, dc = colF - c0;
  const e00 = elevations[r0 * W + c0];
  const e01 = elevations[r0 * W + c0 + 1];
  const e10 = elevations[(r0 + 1) * W + c0];
  const e11 = elevations[(r0 + 1) * W + c0 + 1];
  return (1 - dr) * (1 - dc) * e00 + (1 - dr) * dc * e01
       + dr * (1 - dc) * e10 + dr * dc * e11;
}

// ---------------------------------------------------------------------------
// Floating text sprite (used by schoolhouse labels + Brgy. Malico marker).
// ---------------------------------------------------------------------------
function makeTextSprite(text, opts = {}) {
  const color = opts.color  || '#ffffff';
  const bg    = opts.bg     || 'rgba(15,18,26,0.88)';
  const stroke= opts.stroke || '#ff5252';
  const c = document.createElement('canvas');
  c.width = 512; c.height = 128;
  const x = c.getContext('2d');
  x.fillStyle = bg; x.fillRect(0, 0, 512, 128);
  x.strokeStyle = stroke; x.lineWidth = 4;
  x.strokeRect(2, 2, 508, 124);
  x.fillStyle = color; x.font = 'bold 50px Segoe UI, sans-serif';
  x.textAlign = 'center'; x.textBaseline = 'middle';
  x.fillText(text, 256, 64);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
    map: tex, depthTest: false, transparent: true }));
  sprite.scale.set(14, 3.5, 1);
  return sprite;
}

// ---------------------------------------------------------------------------
// OSM features - buildings + roads
// ---------------------------------------------------------------------------
function buildFeatures() {
  featuresGroup = new THREE.Group();
  buildingsGroup = new THREE.Group();
  roadsGroup = new THREE.Group();

  const minE = meta.elev_min;
  const ws = features.world_scale;

  // --- Buildings: procedural schoolhouse (body + pitched roof + flag) ---
  // Each OSM building polygon (4-point ring for OSM rectangles) is fitted
  // with an oriented schoolhouse: width comes from edge p0->p1, depth from
  // p1->p2. The schoolhouse is then rotated and translated to match.
  const bodyMat  = new THREE.MeshStandardMaterial({ color: SCHOOL_COLORS.body,  roughness: 0.7 });
  const roofMat  = new THREE.MeshStandardMaterial({ color: SCHOOL_COLORS.roof,  roughness: 0.55, side: THREE.DoubleSide });
  const baseMat  = new THREE.MeshStandardMaterial({ color: SCHOOL_COLORS.base,  roughness: 1.0 });
  const poleMat  = new THREE.MeshStandardMaterial({ color: SCHOOL_COLORS.flagPole, metalness: 0.2 });
  const flagMat  = new THREE.MeshStandardMaterial({ color: SCHOOL_COLORS.flag, emissive: SCHOOL_COLORS.flag, emissiveIntensity: 0.4, side: THREE.DoubleSide });

  for (const b of features.buildings) {
    const fp = b.footprint;
    if (fp.length < 3) continue;
    let cx = 0, cz = 0;
    for (const p of fp) { cx += p[0]; cz += p[1]; }
    cx /= fp.length; cz /= fp.length;

    // Width = first edge, depth = second edge, orientation = first edge angle.
    let W = Math.hypot(fp[1][0] - fp[0][0], fp[1][1] - fp[0][1]);
    let D = fp.length > 2
            ? Math.hypot(fp[2][0] - fp[1][0], fp[2][1] - fp[1][1])
            : W;
    const angle = Math.atan2(fp[1][1] - fp[0][1], fp[1][0] - fp[0][0]);
    W *= BUILDING_FOOTPRINT_SCALE;
    D *= BUILDING_FOOTPRINT_SCALE;
    if (W < 0.6) W = 0.6;       // floor so tiny rect-ish footprints stay visible
    if (D < 0.6) D = 0.6;

    const baseY = (b.base_elev_m - minE) * ws;
    const group = new THREE.Group();
    group.position.set(cx, baseY, cz);
    group.rotation.y = -angle;        // align with the long edge

    // Base trim (slightly larger than the body, dark)
    const base = new THREE.Mesh(
      new THREE.BoxGeometry(W * 1.08, BUILDING_BASE_HEIGHT, D * 1.08), baseMat);
    base.position.y = BUILDING_BASE_HEIGHT / 2;
    group.add(base);

    // Body (cream box)
    const body = new THREE.Mesh(
      new THREE.BoxGeometry(W, BUILDING_BODY_HEIGHT, D), bodyMat);
    body.position.y = BUILDING_BASE_HEIGHT + BUILDING_BODY_HEIGHT / 2;
    group.add(body);

    // Pitched roof - triangular prism with ridge along the width axis (X).
    const RH = BUILDING_ROOF_HEIGHT;
    const W2 = W / 2 * 1.05, D2 = D / 2 * 1.05;
    const roofPositions = new Float32Array([
      -W2, 0,  D2,    // 0 BFL
       W2, 0,  D2,    // 1 BFR
      -W2, 0, -D2,    // 2 BBL
       W2, 0, -D2,    // 3 BBR
      -W2, RH, 0,     // 4 ridge left
       W2, RH, 0,     // 5 ridge right
    ]);
    const roofIndices = [
      0, 1, 5,   0, 5, 4,        // front slope
      3, 2, 4,   3, 4, 5,        // back slope
      0, 4, 2,                   // left gable
      1, 3, 5,                   // right gable
    ];
    const roofGeom = new THREE.BufferGeometry();
    roofGeom.setAttribute('position', new THREE.BufferAttribute(roofPositions, 3));
    roofGeom.setIndex(roofIndices);
    roofGeom.computeVertexNormals();
    const roof = new THREE.Mesh(roofGeom, roofMat);
    roof.position.y = BUILDING_BASE_HEIGHT + BUILDING_BODY_HEIGHT;
    group.add(roof);

    // Flagpole + small flag on the roof ridge - acts as a distance locator.
    const pole = new THREE.Mesh(
      new THREE.CylinderGeometry(0.06, 0.06, BUILDING_FLAG_HEIGHT, 8), poleMat);
    pole.position.set(
      0,
      BUILDING_BASE_HEIGHT + BUILDING_BODY_HEIGHT + RH + BUILDING_FLAG_HEIGHT / 2,
      0);
    group.add(pole);
    const flag = new THREE.Mesh(new THREE.PlaneGeometry(1.4, 0.85), flagMat);
    flag.position.set(
      0.75,
      BUILDING_BASE_HEIGHT + BUILDING_BODY_HEIGHT + RH + BUILDING_FLAG_HEIGHT - 0.55,
      0);
    flag.rotation.y = Math.PI / 2;
    group.add(flag);

    // Shadows for body / base / roof.
    base.castShadow = base.receiveShadow = true;
    body.castShadow = body.receiveShadow = true;
    roof.castShadow = roof.receiveShadow = true;
    pole.castShadow = true;

    // -------- Detail children visible only when the camera is close ------
    const details = new THREE.Group();
    const winMat = new THREE.MeshStandardMaterial({
      color: 0x9adfff, emissive: 0x114455, emissiveIntensity: 0.6,
      roughness: 0.3 });
    const doorMat = new THREE.MeshStandardMaterial({
      color: 0x5a3a1f, roughness: 0.85 });
    // Door on the front (+Z) face.
    const door = new THREE.Mesh(
      new THREE.BoxGeometry(W * 0.18, BUILDING_BODY_HEIGHT * 0.62, 0.08), doorMat);
    door.position.set(0,
      BUILDING_BASE_HEIGHT + BUILDING_BODY_HEIGHT * 0.31,
      D / 2 + 0.05);
    details.add(door);
    // Windows: a strip of 4 on each long face, mid-height.
    const wW = W * 0.11, wH = BUILDING_BODY_HEIGHT * 0.35;
    for (let k = -2; k <= 2; k++) {
      if (k === 0) continue;
      for (const zSign of [+1, -1]) {
        const w = new THREE.Mesh(
          new THREE.BoxGeometry(wW, wH, 0.06), winMat);
        w.position.set(k * (W * 0.18),
          BUILDING_BASE_HEIGHT + BUILDING_BODY_HEIGHT * 0.58,
          zSign * (D / 2 + 0.04));
        details.add(w);
      }
    }
    // Windows on the short sides too.
    for (const xSign of [+1, -1]) {
      const w = new THREE.Mesh(
        new THREE.BoxGeometry(0.06, wH, D * 0.16), winMat);
      w.position.set(
        xSign * (W / 2 + 0.04),
        BUILDING_BASE_HEIGHT + BUILDING_BODY_HEIGHT * 0.58,
        0);
      details.add(w);
    }
    details.visible = false;            // off by default - animate() toggles
    group.add(details);

    // Floating text sprite ("School") shown only at close range.
    const label = makeTextSprite(b.tags?.name || 'School', {
      color: '#ffffff', bg: 'rgba(15,18,26,0.85)', stroke: '#ffc04a' });
    label.position.set(0,
      BUILDING_BASE_HEIGHT + BUILDING_BODY_HEIGHT + RH + 1.4, 0);
    label.visible = false;
    group.add(label);

    buildingLODs.push({ group, details, label });
    buildingsGroup.add(group);
  }

  // --- Roads: textured ribbons ---
  const roadColors = {
    'primary':       0xffd84a,
    'secondary':     0xffc04a,
    'tertiary':      0xffb000,
    'unclassified':  0xa0a0a0,
    'residential':   0x9090a0,
    'track':         0xa07050,
    'service':       0x808090,
    'path':          0x607080,
    'footway':       0x607080,
  };
  const halfW = (ROAD_WIDTH_M / 2) * ws;

  for (const road of features.roads) {
    const line = road.line;
    if (line.length < 2) continue;

    // Compute per-vertex left/right offsets perpendicular to local tangent.
    const positions = [];
    const indices = [];
    for (let i = 0; i < line.length; i++) {
      const p = line[i];
      let dx = 0, dz = 0;
      if (i > 0) {
        dx += p[0] - line[i - 1][0];
        dz += p[1] - line[i - 1][1];
      }
      if (i < line.length - 1) {
        dx += line[i + 1][0] - p[0];
        dz += line[i + 1][1] - p[1];
      }
      const len = Math.hypot(dx, dz) || 1;
      // perpendicular in xz plane: (-dz, dx)/len
      const px = -dz / len, pz = dx / len;
      const yWorld = (p[2] - minE) * ws + ROAD_Y_OFFSET;
      positions.push(p[0] + px * halfW, yWorld, p[1] + pz * halfW);
      positions.push(p[0] - px * halfW, yWorld, p[1] - pz * halfW);
    }
    for (let i = 0; i < line.length - 1; i++) {
      const a = i * 2;
      indices.push(a, a + 1, a + 2, a + 2, a + 1, a + 3);
    }
    const geom = new THREE.BufferGeometry();
    geom.setAttribute('position',
      new THREE.BufferAttribute(new Float32Array(positions), 3));
    geom.setIndex(indices);
    geom.computeVertexNormals();
    const color = roadColors[road.highway] ?? 0xaaaaaa;
    const isPrimary = road.highway === 'primary' || road.highway === 'secondary';
    const mat = new THREE.MeshStandardMaterial({
      color, emissive: color,
      emissiveIntensity: isPrimary ? 1.1 : 0.6,
      roughness: 0.4, metalness: 0.0, side: THREE.DoubleSide,
    });
    const roadMesh = new THREE.Mesh(geom, mat);
    roadMesh.receiveShadow = true;
    roadsGroup.add(roadMesh);
  }

  featuresGroup.add(buildingsGroup);
  featuresGroup.add(roadsGroup);
  terrainGroup.add(featuresGroup);
}

// ---------------------------------------------------------------------------
// Waterways - rivers / streams / creeks as blue draped ribbons.
// ---------------------------------------------------------------------------
function buildWaterways() {
  if (!features?.waterways?.length) return;
  waterwaysGroup = new THREE.Group();
  const ws = features.world_scale;
  const minE = meta.elev_min;
  const halfW = (WATERWAY_WIDTH_M / 2) * ws;
  const mat = new THREE.MeshStandardMaterial({
    color: WATERWAY_COLOR, emissive: WATERWAY_COLOR, emissiveIntensity: 0.55,
    roughness: 0.25, metalness: 0.0, side: THREE.DoubleSide, transparent: true,
    opacity: 0.92,
  });
  for (const w of features.waterways) {
    const line = w.line;
    if (line.length < 2) continue;
    const positions = []; const indices = [];
    for (let i = 0; i < line.length; i++) {
      const p = line[i];
      let dx = 0, dz = 0;
      if (i > 0) { dx += p[0] - line[i-1][0]; dz += p[1] - line[i-1][1]; }
      if (i < line.length - 1) { dx += line[i+1][0] - p[0]; dz += line[i+1][1] - p[1]; }
      const len = Math.hypot(dx, dz) || 1;
      const px = -dz / len, pz = dx / len;
      const yWorld = (p[2] - minE) * ws + WATERWAY_Y_OFFSET;
      positions.push(p[0] + px * halfW, yWorld, p[1] + pz * halfW);
      positions.push(p[0] - px * halfW, yWorld, p[1] - pz * halfW);
    }
    for (let i = 0; i < line.length - 1; i++) {
      const a = i * 2;
      indices.push(a, a+1, a+2, a+2, a+1, a+3);
    }
    const geom = new THREE.BufferGeometry();
    geom.setAttribute('position',
      new THREE.BufferAttribute(new Float32Array(positions), 3));
    geom.setIndex(indices);
    geom.computeVertexNormals();
    const mesh = new THREE.Mesh(geom, mat);
    waterwaysGroup.add(mesh);
  }
  terrainGroup.add(waterwaysGroup);
  console.log(`Rendered ${features.waterways.length} waterway segments`);
}

// ---------------------------------------------------------------------------
// Environment features - place names, POIs (Malico Viewpoint etc.), peaks,
// and named-road / named-river labels. Everything goes into a single group
// so users can toggle all annotations at once.
// ---------------------------------------------------------------------------
function buildEnvironmentFeatures() {
  if (!features) return;
  environmentGroup = new THREE.Group();
  const ws = features.world_scale;
  const minE = meta.elev_min;

  // --- Peaks: small brown cone + elevation label -----------------------
  const peakGeo = new THREE.ConeGeometry(1.6, 4, 6);
  const peakMat = new THREE.MeshStandardMaterial({
    color: 0x8b5a2b, emissive: 0x3a2410, emissiveIntensity: 0.4,
    roughness: 0.85 });
  for (const peak of features.peaks || []) {
    const wy = (peak.elev_m - minE) * ws;
    const cone = new THREE.Mesh(peakGeo, peakMat);
    cone.position.set(peak.x, wy + 2, peak.z);
    cone.castShadow = true;
    environmentGroup.add(cone);
    const label = peak.name
      ? `${peak.name} - ${peak.elev_m.toFixed(0)} m`
      : `Peak ${peak.elev_m.toFixed(0)} m`;
    const sprite = makeTextSprite(label, {
      bg: 'rgba(40,30,15,0.88)', stroke: '#c89060' });
    sprite.position.set(peak.x, wy + 8, peak.z);
    sprite.scale.set(20, 5, 1);
    environmentGroup.add(sprite);
  }

  // --- POIs (Malico Viewpoint, schools, churches, etc.) ---------------
  const poiGeo = new THREE.SphereGeometry(0.7, 12, 8);
  for (const poi of features.pois || []) {
    const wy = (poi.elev_m - minE) * ws;
    const isViewpoint = poi.subtype === 'viewpoint';
    const isReligion  = poi.subtype === 'place_of_worship';
    const isSchool    = poi.subtype === 'school' || poi.subtype === 'kindergarten';
    let markerColor = 0x4ec3ff, strokeHex = '#4ec3ff';
    if (isViewpoint) { markerColor = 0xffb05a; strokeHex = '#ffb05a'; }
    else if (isReligion) { markerColor = 0xc890ff; strokeHex = '#c890ff'; }
    else if (isSchool) { markerColor = 0xffd84a; strokeHex = '#ffd84a'; }
    const mat = new THREE.MeshStandardMaterial({
      color: markerColor, emissive: markerColor, emissiveIntensity: 0.7,
      roughness: 0.3 });
    const sphere = new THREE.Mesh(poiGeo, mat);
    sphere.position.set(poi.x, wy + 2.0, poi.z);
    environmentGroup.add(sphere);
    const label = poi.name || poi.subtype;
    const sprite = makeTextSprite(label, {
      bg: 'rgba(20,18,14,0.88)', stroke: strokeHex });
    sprite.position.set(poi.x, wy + 8, poi.z);
    sprite.scale.set(22, 5.5, 1);
    environmentGroup.add(sprite);
  }

  // --- Place names: villages / hamlets / sitios -----------------------
  for (const place of features.places || []) {
    const wy = (place.elev_m - minE) * ws;
    const big = (place.type === 'town' || place.type === 'village');
    const sprite = makeTextSprite(place.name || place.type, {
      bg: 'rgba(15,18,26,0.92)', stroke: '#ffffff' });
    sprite.position.set(place.x, wy + (big ? 14 : 9), place.z);
    sprite.scale.set(big ? 28 : 22, big ? 7 : 5.5, 1);
    environmentGroup.add(sprite);
  }

  // --- Named-road labels (place a sprite at the midpoint) ------------
  const seenRoadNames = new Set();
  for (const road of features.roads || []) {
    if (!road.name || road.line.length < 2) continue;
    if (seenRoadNames.has(road.name)) continue;       // avoid duplicates for both directions
    seenRoadNames.add(road.name);
    const mid = road.line[Math.floor(road.line.length / 2)];
    const wy = (mid[2] - minE) * ws + 3;
    const sprite = makeTextSprite(road.name, {
      bg: 'rgba(30,22,10,0.86)', stroke: '#ffd84a' });
    sprite.position.set(mid[0], wy, mid[1]);
    sprite.scale.set(22, 4.5, 1);
    environmentGroup.add(sprite);
  }

  // --- Named-river labels --------------------------------------------
  for (const w of features.waterways || []) {
    if (!w.name || w.line.length < 2) continue;
    const mid = w.line[Math.floor(w.line.length / 2)];
    const wy = (mid[2] - minE) * ws + 3;
    const sprite = makeTextSprite(w.name, {
      bg: 'rgba(10,30,60,0.88)', stroke: '#4ec3ff' });
    sprite.position.set(mid[0], wy, mid[1]);
    sprite.scale.set(20, 4.5, 1);
    environmentGroup.add(sprite);
  }

  terrainGroup.add(environmentGroup);
}

// ---------------------------------------------------------------------------
// Admin boundaries - "sakop" of each place rendered as colored draped walls.
// Each boundary gets a distinct hue. Segments outside the AOI are skipped
// (their terrain isn't visible anyway). Color is also stored on the boundary
// object so buildMinimap() can use the same hue on the 2D Leaflet view.
// ---------------------------------------------------------------------------
const BOUNDARY_WALL_HEIGHT = 8.0;       // world units; tall enough to read
const BOUNDARY_LABEL_HEIGHT = 12.0;

// Liang-Barsky line clip of segment (x1,z1)->(x2,z2) against AOI rectangle
// [-halfX, halfX] x [-halfZ, halfZ]. Returns clipped [x1',z1',e1', x2',z2',e2']
// (with elevations linearly interpolated) or null if the segment misses the
// rectangle entirely. This is what lets boundaries that pass THROUGH the AOI
// (both endpoints outside, but the middle crosses) still render correctly.
function _clipSegmentToAOI(x1, z1, e1, x2, z2, e2, halfX, halfZ) {
  let t0 = 0, t1 = 1;
  const dx = x2 - x1, dz = z2 - z1;
  const p = [-dx, dx, -dz, dz];
  const q = [x1 + halfX, halfX - x1, z1 + halfZ, halfZ - z1];
  for (let i = 0; i < 4; i++) {
    if (p[i] === 0) {
      if (q[i] < 0) return null;
    } else {
      const t = q[i] / p[i];
      if (p[i] < 0) { if (t > t1) return null; if (t > t0) t0 = t; }
      else          { if (t < t0) return null; if (t < t1) t1 = t; }
    }
  }
  return [
    x1 + t0 * dx, z1 + t0 * dz, e1 + (e2 - e1) * t0,
    x1 + t1 * dx, z1 + t1 * dz, e1 + (e2 - e1) * t1,
  ];
}

function buildBoundaries() {
  if (!features?.boundaries?.length) {
    console.warn('No boundary data available.');
    return;
  }
  boundariesGroup = new THREE.Group();
  const ws = features.world_scale;
  const minE = meta.elev_min;
  const W = meta.generated_grid.width;
  const H = meta.generated_grid.height;
  const cellX = meta.cell_x_m, cellY = meta.cell_y_m;
  const halfX = (W - 1) / 2 * cellX * ws;
  const halfZ = (H - 1) / 2 * cellY * ws;

  let totalRendered = 0;
  let totalSkipped = 0;

  features.boundaries.forEach((b, idx) => {
    // Distinct hue per boundary using the golden-angle increment for
    // good perceptual separation even with many polygons.
    const hue = (idx * 137.508) % 360;
    const isMuni = b.admin_level <= 6;
    const color = new THREE.Color().setHSL(
      hue / 360, isMuni ? 0.95 : 0.85, isMuni ? 0.58 : 0.55);
    const colorHex = `#${color.getHexString()}`;
    b._color = colorHex;                          // shared with Leaflet

    const verts = b.world;        // [[wx, wz, elev], ...]
    const positions = [];
    const indices = [];
    const inAOIWy = [];
    let inAOIxz = [];
    let vi = 0;
    let clippedSegs = 0;
    for (let i = 0; i < verts.length - 1; i++) {
      const [x1, z1, e1] = verts[i];
      const [x2, z2, e2] = verts[i + 1];
      const clip = _clipSegmentToAOI(x1, z1, e1, x2, z2, e2, halfX, halfZ);
      if (!clip) continue;
      clippedSegs++;
      const [cx1, cz1, ce1, cx2, cz2, ce2] = clip;
      const y1 = (ce1 - minE) * ws;
      const y2 = (ce2 - minE) * ws;
      positions.push(cx1, y1, cz1);
      positions.push(cx1, y1 + BOUNDARY_WALL_HEIGHT, cz1);
      positions.push(cx2, y2, cz2);
      positions.push(cx2, y2 + BOUNDARY_WALL_HEIGHT, cz2);
      indices.push(vi, vi + 1, vi + 2);
      indices.push(vi + 2, vi + 1, vi + 3);
      vi += 4;
      inAOIxz.push([cx1, cz1]); inAOIxz.push([cx2, cz2]);
      inAOIWy.push(y1, y2);
    }
    if (positions.length === 0) { totalSkipped++; return; }
    totalRendered++;

    const geom = new THREE.BufferGeometry();
    geom.setAttribute('position',
      new THREE.BufferAttribute(new Float32Array(positions), 3));
    geom.setIndex(indices);
    geom.computeVertexNormals();
    const mat = new THREE.MeshStandardMaterial({
      color: color.getHex(), emissive: color.getHex(), emissiveIntensity: 0.85,
      roughness: 0.3, metalness: 0.0, side: THREE.DoubleSide,
      transparent: true, opacity: 0.92,
      depthWrite: false,                  // avoid z-fighting on the terrain
    });
    const mesh = new THREE.Mesh(geom, mat);
    mesh.renderOrder = 5;                 // draw above terrain & overlays
    boundariesGroup.add(mesh);

    // Label: average of clipped (in-AOI) vertices.
    let lx = 0, lz = 0, ly = 0;
    for (const [x, z] of inAOIxz) { lx += x; lz += z; }
    for (const y of inAOIWy) ly += y;
    lx /= inAOIxz.length; lz /= inAOIxz.length; ly /= inAOIWy.length;
    const sprite = makeTextSprite(`${b.name} (AL${b.admin_level})`, {
      bg: 'rgba(15,18,26,0.95)', stroke: colorHex });
    sprite.position.set(lx, ly + BOUNDARY_LABEL_HEIGHT, lz);
    sprite.scale.set(34, 8.5, 1);
    sprite.renderOrder = 6;
    boundariesGroup.add(sprite);
    console.log(`  boundary ${b.name} (AL${b.admin_level}): `
                + `${clippedSegs} segments rendered, color=${colorHex}`);
  });

  terrainGroup.add(boundariesGroup);
  console.log(`buildBoundaries: ${totalRendered} rendered, `
              + `${totalSkipped} skipped (no AOI overlap). `
              + `Total objects in group: ${boundariesGroup.children.length}.`);
  if (totalRendered === 0) {
    console.warn('WARNING: zero boundaries cross the AOI. The boundary fetch '
      + 'may have pulled neighbouring admin units only. Re-fetch boundaries '
      + 'after deleting data/raw/osm_boundaries.json to retry, or check that '
      + 'OpenStreetMap has admin polygons mapped in this area.');
  }
}

// ---------------------------------------------------------------------------
// 2D Leaflet minimap - online OSM tiles give full street-level detail that
// the offline 3D viewer cannot show (every footpath, every contour name).
// ---------------------------------------------------------------------------
function buildMinimap() {
  if (typeof L === 'undefined') {
    console.warn('Leaflet not loaded - minimap disabled');
    return;
  }
  const aoi = meta.aoi_wgs84;
  const cy = (aoi.min_lat + aoi.max_lat) / 2;
  const cx = (aoi.min_lon + aoi.max_lon) / 2;

  leafletMap = L.map('minimap', {
    center: [cy, cx], zoom: 13,
    zoomControl: true, attributionControl: true,
    preferCanvas: true,
  });
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(leafletMap);

  // Boundaries first (so points render on top).
  for (const b of (features?.boundaries || [])) {
    const color = b._color || '#ff5a5a';
    const isMuni = b.admin_level <= 6;
    L.polygon(b.latlon, {
      color, weight: isMuni ? 3 : 2,
      fillColor: color, fillOpacity: isMuni ? 0.08 : 0.18,
      dashArray: isMuni ? '8 4' : null,
    }).addTo(leafletMap)
      .bindPopup(`<b>${b.name}</b><br>admin_level ${b.admin_level} `
                 + `(${isMuni ? 'municipality' : 'barangay'})`);
  }

  // AOI rectangle (the 3D model's footprint)
  L.rectangle([[aoi.min_lat, aoi.min_lon], [aoi.max_lat, aoi.max_lon]], {
    color: '#ff5a5a', weight: 2, fillOpacity: 0.0, dashArray: '6 4',
  }).addTo(leafletMap).bindTooltip('3D model AOI');

  // Site marker
  L.marker([meta.site.lat, meta.site.lon])
    .addTo(leafletMap)
    .bindPopup(`<b>${meta.site.label}</b><br>${meta.site.lat.toFixed(4)}, ${meta.site.lon.toFixed(4)}`);

  // Peaks
  for (const peak of (features?.peaks || [])) {
    L.circleMarker([peak.lat, peak.lon], {
      radius: 5, color: '#8b5a2b', fillColor: '#c89060',
      weight: 2, fillOpacity: 0.85,
    }).addTo(leafletMap)
      .bindPopup(`<b>Mountain peak</b><br>${peak.elev_m.toFixed(0)} m a.s.l.`);
  }
  // POIs
  for (const poi of (features?.pois || [])) {
    const color = poi.subtype === 'viewpoint' ? '#ffb05a'
                : poi.subtype === 'place_of_worship' ? '#c890ff'
                : (poi.subtype || '').includes('school') ? '#ffd84a'
                : '#4ec3ff';
    L.circleMarker([poi.lat, poi.lon], {
      radius: 6, color, fillColor: color, weight: 2, fillOpacity: 0.85,
    }).addTo(leafletMap)
      .bindPopup(`<b>${poi.name || poi.subtype}</b><br>${poi.category} / ${poi.subtype}`);
  }
  // Named places (villages/sitios)
  for (const place of (features?.places || [])) {
    L.marker([place.lat, place.lon]).addTo(leafletMap)
      .bindPopup(`<b>${place.name || place.type}</b><br>${place.type}`);
  }

  leafletMap.fitBounds(
    [[aoi.min_lat, aoi.min_lon], [aoi.max_lat, aoi.max_lon]],
    { padding: [8, 8] });
}

function toggleMinimap(show) {
  const el = document.getElementById('minimap-wrap');
  if (!el) return;
  // Desktop path: inline-style toggle (CSS default is display:flex via the
  // rule on #minimap-wrap). Mobile path: also clear inline style and let the
  // .mobile-show class on the wrapper decide visibility instead.
  const isMobile = window.matchMedia('(max-width: 768px)').matches;
  if (isMobile) {
    el.style.display = '';                    // hand control back to CSS
    el.classList.toggle('mobile-show', !!show);
    const fab = document.getElementById('fab-mini');
    if (fab) fab.classList.toggle('active', !!show);
  } else {
    el.style.display = show ? 'flex' : 'none';
  }
  if (show && leafletMap) setTimeout(() => leafletMap.invalidateSize(), 80);
}

// ---------------------------------------------------------------------------
// Marker
// ---------------------------------------------------------------------------
function buildMarker() {
  const W = meta.generated_grid.width, H = meta.generated_grid.height;
  const cx = meta.cell_x_m, cy = meta.cell_y_m;
  const site = meta.site;
  const x = (site.col - (W - 1) / 2) * cx * worldScale;
  const z = (site.row - (H - 1) / 2) * cy * worldScale;
  const y = (elevAt(site.row, site.col) - meta.elev_min) * worldScale;

  markerGroup = new THREE.Group();
  markerGroup.position.set(x, y, z);

  const poleH = 18;
  const pole = new THREE.Mesh(
    new THREE.CylinderGeometry(0.25, 0.25, poleH, 12),
    new THREE.MeshStandardMaterial({ color: 0xfff7d6 }));
  pole.position.y = poleH / 2;
  markerGroup.add(pole);

  const cone = new THREE.Mesh(
    new THREE.ConeGeometry(2.2, 4, 18),
    new THREE.MeshStandardMaterial({ color: 0xff3b3b, emissive: 0x551111 }));
  cone.position.y = poleH + 2;
  cone.rotation.x = Math.PI;
  markerGroup.add(cone);

  const cnv = document.createElement('canvas');
  cnv.width = 512; cnv.height = 128;
  const ctx = cnv.getContext('2d');
  ctx.fillStyle = 'rgba(15,18,26,0.88)';
  ctx.fillRect(0, 0, 512, 128);
  ctx.strokeStyle = '#ff5252'; ctx.lineWidth = 4;
  ctx.strokeRect(2, 2, 508, 124);
  ctx.fillStyle = '#fff';
  ctx.font = 'bold 50px Segoe UI, sans-serif';
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillText(site.label, 256, 64);
  const tex = new THREE.CanvasTexture(cnv);
  tex.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
    map: tex, depthTest: false, transparent: true }));
  sprite.scale.set(28, 7, 1);
  sprite.position.y = poleH + 9;
  markerGroup.add(sprite);

  terrainGroup.add(markerGroup);
}

// ---------------------------------------------------------------------------
// Controls / UI
// ---------------------------------------------------------------------------
function applyExaggeration(exag) {
  terrainGroup.scale.y = exag;
  if (markerGroup) markerGroup.scale.y = 1 / exag;
  document.getElementById('exag-val').textContent = `${exag.toFixed(1)}×`;
}

function activeLayerNeedsScenario(id) {
  const L = meta.layers.find(l => l.id === id);
  return L && L.scenarioTextures && !L.texture;
}

function refreshLayerTexture() {
  if (!terrainMesh) return;
  // The "plain" pseudo-layer = pure white terrain, no hazard texture.
  if (activeLayerId === 'plain') {
    terrainMesh.material = plainTerrainMat;
    texturedTerrainMat.map = null;
    texturedTerrainMat.needsUpdate = true;
    return;
  }
  terrainMesh.material = texturedTerrainMat;
  const L = meta.layers.find(l => l.id === activeLayerId);
  if (!L) return;
  let tex = layerTextures[L.id];
  if (L.scenarioTextures) {
    const isSusc = L.id === 'susceptibility';
    tex = scenarioTextures[currentScenario]?.[isSusc ? 'susc' : 'runout'];
  }
  if (tex) {
    texturedTerrainMat.map = tex;
    texturedTerrainMat.needsUpdate = true;
  }
}

// "Plain" mode = trees hidden only. Hazard layers are always interactive.
function setPlainMode(on) {
  plainMode = !!on;
  if (treesGroup) treesGroup.visible = !plainMode;
  const btn = document.getElementById('plain-toggle');
  if (btn) btn.textContent = plainMode ? 'Show trees' : 'Hide trees';
  const indicator = document.getElementById('mode-indicator');
  if (indicator) indicator.textContent = plainMode ? 'Hidden' : 'Visible';
}

function setLayer(id) {
  activeLayerId = id;
  refreshLayerTexture();
  const layer = meta.layers.find(l => l.id === id);
  document.getElementById('layer-desc').textContent = layer.description;
  const legend = document.getElementById('legend');
  legend.innerHTML = '';
  if (layer.legend) {
    for (const it of layer.legend) {
      const row = document.createElement('div');
      row.className = 'legend-row';
      row.innerHTML = `<span class="swatch" style="background:${it.color}"></span>${it.label}`;
      legend.appendChild(row);
    }
  } else {
    legend.innerHTML = '<div class="legend-row" style="color:var(--muted)">Base relief layer</div>';
  }
  document.querySelectorAll('#layers .layer').forEach(el => {
    el.classList.toggle('active', el.dataset.id === id);
  });
  // Highlight scenario panel as relevant when active layer is scenario-driven.
  document.querySelector('.scenario-hint').style.opacity =
    activeLayerNeedsScenario(id) ? 1 : 0.4;
}

function setScenario(id) {
  currentScenario = id;
  document.querySelectorAll('#scenarios .scenario').forEach(el => {
    el.classList.toggle('active', el.dataset.id === id);
  });
  if (activeLayerNeedsScenario(activeLayerId)) refreshLayerTexture();
  renderStats();
}

function setSunAzimuth(deg) {
  const az = THREE.MathUtils.degToRad(deg);
  const alt = THREE.MathUtils.degToRad(45);
  dirLight.position.set(
    Math.cos(alt) * Math.sin(az) * 250,
    Math.sin(alt) * 250,
    Math.cos(alt) * Math.cos(az) * 250,
  );
  const el = document.getElementById('sun-val');
  if (el) el.textContent = `${Math.round(deg)}°`;
}

function applyPreset(name) {
  const p = PRESETS[name];
  if (!p) return;
  camera.position.set(...p.pos);
  if (controls) {
    controls.target.set(...p.target);
    controls.update();
  }
}

function takeScreenshot() {
  renderer.render(scene, camera);            // ensure latest frame
  const dataURL = renderer.domElement.toDataURL('image/png');
  const a = document.createElement('a');
  a.href = dataURL;
  a.download = `malico-3d-${Date.now()}.png`;
  a.click();
}

function renderStats() {
  const ss = meta.shared_stats;
  const sc = meta.scenarios.find(s => s.id === currentScenario) ?? meta.scenarios[0];
  const s = sc.stats;
  const e = sc.exposure || {};

  const sharedRows = [
    ['Elevation range', `${ss.elev_min_m.toFixed(0)} - ${ss.elev_max_m.toFixed(0)} m`],
    ['Mean slope', `${ss.mean_slope_deg.toFixed(1)}°`],
    ['Max slope', `${ss.max_slope_deg.toFixed(1)}°`],
    ['Travel angle', `${ss.travel_angle_deg.toFixed(1)}°`],
    ['Drainage cells', `${ss.channel_cells.toLocaleString()}`],
    ['OSM buildings', `${ss.n_buildings}`],
    ['OSM roads', `${ss.n_roads}`],
  ];
  const scenarioRows = [
    [`<b style="color:var(--accent2)">${sc.name}</b> (m=${sc.m.toFixed(2)})`, '', true],
    ['Unstable area', `${s.unstable_percent.toFixed(1)} % (FS<1.0)`],
    ['Failure sources', `${s.n_sources.toLocaleString()}`],
    ['Runout footprint', `${s.runout_percent.toFixed(1)} % of AOI`],
    ['Max runout', `${s.max_runout_m.toFixed(0)} m`],
  ];
  document.getElementById('stats-body').innerHTML =
    sharedRows.map(([k, v]) =>
      `<div class="stat"><span>${k}</span><b>${v}</b></div>`).join('') +
    scenarioRows.map(([k, v, head]) =>
      head ? `<div class="stat bold"><span>${k}</span><b>${v}</b></div>`
           : `<div class="stat"><span>${k}</span><b>${v}</b></div>`).join('');

  const expRows = [
    ['Buildings exposed',
     `${e.buildings_in_runout ?? 0} / ${e.buildings_total ?? ss.n_buildings}`],
    ['Road length exposed',
     `${((e.roads_in_runout_m ?? 0) / 1000).toFixed(2)} km`],
    ['Road exposed %',
     `${(e.roads_in_runout_pct ?? 0).toFixed(1)} %`],
  ];
  document.getElementById('exposure-body').innerHTML =
    expRows.map(([k, v]) =>
      `<div class="stat"><span>${k}</span><b>${v}</b></div>`).join('');
}

function buildUI() {
  // Layer chooser
  const layersDiv = document.getElementById('layers');
  for (const L of meta.layers) {
    const el = document.createElement('div');
    el.className = 'layer';
    el.dataset.id = L.id;
    el.innerHTML = `<strong>${L.name}</strong>`;
    el.addEventListener('click', () => setLayer(L.id));
    layersDiv.appendChild(el);
  }
  // Scenario chooser
  const scDiv = document.getElementById('scenarios');
  for (const sc of meta.scenarios) {
    const el = document.createElement('div');
    el.className = 'scenario';
    el.dataset.id = sc.id;
    el.innerHTML = `<b>${sc.name}</b><span>m = ${sc.m.toFixed(2)}</span>`;
    el.addEventListener('click', () => setScenario(sc.id));
    scDiv.appendChild(el);
  }
  // Controls
  document.getElementById('exag').value = meta.vertical_exaggeration;
  document.getElementById('exag').addEventListener('input',
    e => applyExaggeration(parseFloat(e.target.value)));
  document.getElementById('sun').addEventListener('input',
    e => setSunAzimuth(parseFloat(e.target.value)));
  document.getElementById('marker-toggle').addEventListener('change',
    e => { markerGroup.visible = e.target.checked; });
  document.getElementById('features-toggle').addEventListener('change',
    e => { if (featuresGroup) featuresGroup.visible = e.target.checked; });
  const waterToggle = document.getElementById('waterways-toggle');
  if (waterToggle) waterToggle.addEventListener('change',
    e => { if (waterwaysGroup) waterwaysGroup.visible = e.target.checked; });
  const envToggle = document.getElementById('environment-toggle');
  if (envToggle) envToggle.addEventListener('change',
    e => { if (environmentGroup) environmentGroup.visible = e.target.checked; });
  const boundToggle = document.getElementById('boundaries-toggle');
  if (boundToggle) boundToggle.addEventListener('change',
    e => { if (boundariesGroup) boundariesGroup.visible = e.target.checked; });
  const minimapToggle = document.getElementById('minimap-toggle');
  if (minimapToggle) minimapToggle.addEventListener('change',
    e => toggleMinimap(e.target.checked));
  const minimapClose = document.getElementById('minimap-close');
  if (minimapClose) minimapClose.addEventListener('click', (e) => {
    e.preventDefault();
    toggleMinimap(false);
    if (minimapToggle) minimapToggle.checked = false;
  });
  document.getElementById('reset').addEventListener('click',
    () => applyPreset('oblique'));
  document.getElementById('screenshot').addEventListener('click', takeScreenshot);
  document.querySelectorAll('.btn-row button[data-preset]').forEach(b =>
    b.addEventListener('click', () => applyPreset(b.dataset.preset)));
  document.getElementById('sim-play').addEventListener('click',
    () => setSimulationRunning(!simRunning));
  document.getElementById('sim-reset').addEventListener('click',
    () => resetSimulation());
  document.getElementById('plain-toggle').addEventListener('click',
    () => setPlainMode(!plainMode));
  setPlainMode(plainMode);    // apply default plain state on load

  // -------------------------------------------------------------------------
  // Mobile FAB handlers: convert side panels to bottom-sheet drawers on
  // narrow screens. Hidden via CSS on desktop, so the listeners are no-ops
  // unless the user is on a phone.
  // -------------------------------------------------------------------------
  const panelEl   = document.getElementById('panel');
  const statsEl   = document.getElementById('stats');
  const miniEl    = document.getElementById('minimap-wrap');
  const fabPanel  = document.getElementById('fab-panel');
  const fabStats  = document.getElementById('fab-stats');
  const fabMini   = document.getElementById('fab-mini');

  function closeAllSheets() {
    panelEl.classList.remove('open');
    statsEl.classList.remove('open');
    fabPanel.classList.remove('active');
    fabStats.classList.remove('active');
  }
  fabPanel?.addEventListener('click', () => {
    const willOpen = !panelEl.classList.contains('open');
    closeAllSheets();
    if (willOpen) {
      panelEl.classList.add('open');
      fabPanel.classList.add('active');
    }
  });
  fabStats?.addEventListener('click', () => {
    const willOpen = !statsEl.classList.contains('open');
    closeAllSheets();
    if (willOpen) {
      statsEl.classList.add('open');
      fabStats.classList.add('active');
    }
  });
  fabMini?.addEventListener('click', () => {
    // Mirror Leaflet visibility in the View Controls checkbox + use the
    // canonical toggleMinimap() so desktop/mobile state stays consistent.
    const willShow = !miniEl.classList.contains('mobile-show');
    toggleMinimap(willShow);
    const cbox = document.getElementById('minimap-toggle');
    if (cbox) cbox.checked = willShow;
  });

  // In-panel close buttons (mobile only - hidden via CSS on desktop)
  document.querySelectorAll('.panel-close').forEach(btn => {
    btn.addEventListener('click', () => closeAllSheets());
  });

  renderStats();
}

function onResize() {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
}

// ---------------------------------------------------------------------------
// Live runout-simulation particle system.
//
// Spawns ~1200 debris particles at steep cells (proxy for failure sources)
// and routes each via steepest-descent gradient flow on the DEM. Velocity
// builds with slope (gravity), particles deposit when terrain flattens.
// This is the *animated* counterpart to the static, scenario-baked
// energy-line runout maps - it shows the landslide unfolding in time.
// ---------------------------------------------------------------------------
function precomputeSlopeGrid() {
  if (simSlopeGrid) return simSlopeGrid;
  const W = meta.generated_grid.width;
  const H = meta.generated_grid.height;
  const cx = meta.cell_x_m, cy = meta.cell_y_m;
  simSlopeGrid = new Float32Array(W * H);
  for (let r = 1; r < H - 1; r++) {
    for (let c = 1; c < W - 1; c++) {
      const dzdx = (elevations[r*W + c+1] - elevations[r*W + c-1]) / (2 * cx);
      const dzdy = (elevations[(r+1)*W + c] - elevations[(r-1)*W + c]) / (2 * cy);
      simSlopeGrid[r*W + c] = Math.atan(Math.hypot(dzdx, dzdy)) * 180 / Math.PI;
    }
  }
  return simSlopeGrid;
}

function spawnParticle(p) {
  const W = meta.generated_grid.width;
  const H = meta.generated_grid.height;
  const slope = precomputeSlopeGrid();
  for (let tries = 0; tries < 60; tries++) {
    const r = 2 + Math.random() * (H - 4);
    const c = 2 + Math.random() * (W - 4);
    if (slope[Math.floor(r) * W + Math.floor(c)] > SIM_SOURCE_SLOPE_MIN) {
      p.row = r; p.col = c; p.vr = 0; p.vc = 0;
      p.age = Math.floor(Math.random() * 30);
      p.deposited = false; p.speed = 0;
      return p;
    }
  }
  // Fallback - any cell.
  p.row = H / 2; p.col = W / 2; p.vr = 0; p.vc = 0;
  p.age = 0; p.deposited = true; p.speed = 0;
  return p;
}

function buildSimulation() {
  precomputeSlopeGrid();
  for (let i = 0; i < SIM_PARTICLE_COUNT; i++) {
    particles.push(spawnParticle({}));
  }
  simPositions = new Float32Array(SIM_PARTICLE_COUNT * 3);
  simColors    = new Float32Array(SIM_PARTICLE_COUNT * 3);
  const geom = new THREE.BufferGeometry();
  geom.setAttribute('position', new THREE.BufferAttribute(simPositions, 3));
  geom.setAttribute('color',    new THREE.BufferAttribute(simColors, 3));
  const mat = new THREE.PointsMaterial({
    size: 1.6, vertexColors: true, sizeAttenuation: true,
    transparent: true, opacity: 0.92, depthWrite: false,
  });
  simPoints = new THREE.Points(geom, mat);
  simPoints.frustumCulled = false;
  simPoints.visible = false;
  terrainGroup.add(simPoints);
}

function sampleElev(row, col) {
  const W = meta.generated_grid.width, H = meta.generated_grid.height;
  const r0 = Math.max(0, Math.min(H - 2, Math.floor(row)));
  const c0 = Math.max(0, Math.min(W - 2, Math.floor(col)));
  const dr = row - r0, dc = col - c0;
  const e00 = elevations[r0*W + c0];
  const e01 = elevations[r0*W + c0 + 1];
  const e10 = elevations[(r0+1)*W + c0];
  const e11 = elevations[(r0+1)*W + c0 + 1];
  return (1-dr)*(1-dc)*e00 + (1-dr)*dc*e01 + dr*(1-dc)*e10 + dr*dc*e11;
}

function updateSimulation() {
  if (!simRunning || !simPoints) return;
  simFrame++;
  const W = meta.generated_grid.width;
  const H = meta.generated_grid.height;
  const cx = meta.cell_x_m, cy = meta.cell_y_m;
  const minE = meta.elev_min;
  const slope = simSlopeGrid;
  for (let i = 0; i < particles.length; i++) {
    const p = particles[i];
    if (!p.deposited) {
      const r = p.row, c = p.col;
      // Bilinear gradient
      const r0 = Math.max(1, Math.min(H - 2, Math.floor(r)));
      const c0 = Math.max(1, Math.min(W - 2, Math.floor(c)));
      const dzdx = (elevations[r0*W + c0+1] - elevations[r0*W + c0-1]) / (2 * cx);
      const dzdy = (elevations[(r0+1)*W + c0] - elevations[(r0-1)*W + c0]) / (2 * cy);
      const localSlope = slope[r0*W + c0];
      // Steepest descent direction in (row, col) space.
      // In row direction (south +), the slope component is -dzdy (going down
      // means decreasing elevation, and dzdy was computed with row+1 minus row-1).
      const len = Math.hypot(dzdx, dzdy) || 1e-6;
      const dirC = -dzdx / len;   // cell-column direction (east +)
      const dirR =  dzdy / len;   // cell-row direction (south +). Note sign: row index increases southward where elevation decreases on a south-facing slope.
      p.vc = SIM_VEL_DAMP * p.vc + SIM_VEL_GAIN * localSlope * dirC;
      p.vr = SIM_VEL_DAMP * p.vr + SIM_VEL_GAIN * localSlope * dirR;
      p.col += p.vc;
      p.row += p.vr;
      p.speed = Math.hypot(p.vc, p.vr);
      if (localSlope < SIM_DEPOSIT_SLOPE && p.speed < 0.05) p.deposited = true;
      if (p.col < 1 || p.col > W - 2 || p.row < 1 || p.row > H - 2) p.deposited = true;
    }
    p.age++;
    if (p.age > SIM_MAX_AGE || p.deposited) spawnParticle(p);

    // World position
    const wx = (p.col - (W - 1) / 2) * cx * worldScale;
    const wz = (p.row - (H - 1) / 2) * cy * worldScale;
    const wy = (sampleElev(p.row, p.col) - minE) * worldScale + 0.4;
    simPositions[i*3]   = wx;
    simPositions[i*3+1] = wy;
    simPositions[i*3+2] = wz;
    // Color: fast = bright orange/red, slow = yellow, deposited = purple/grey
    let cr, cg, cb;
    if (p.deposited) {
      cr = 0.5; cg = 0.3; cb = 0.55;             // muted purple
    } else {
      const t = Math.min(p.speed / 0.35, 1.0);
      cr = 1.0;
      cg = 0.85 - 0.7 * t;
      cb = 0.2 - 0.2 * t;
    }
    simColors[i*3]   = cr;
    simColors[i*3+1] = cg;
    simColors[i*3+2] = cb;
  }
  simPoints.geometry.attributes.position.needsUpdate = true;
  simPoints.geometry.attributes.color.needsUpdate = true;
}

function setSimulationRunning(on) {
  simRunning = on;
  if (simPoints) simPoints.visible = on;
  document.getElementById('sim-play').textContent = on ? 'Pause' : 'Play';
  document.getElementById('sim-status').textContent =
    on ? 'Running' : (simFrame ? 'Paused' : 'Idle');
}

function resetSimulation() {
  simFrame = 0;
  for (const p of particles) spawnParticle(p);
  document.getElementById('sim-status').textContent =
    simRunning ? 'Running' : 'Idle';
}

// Toggle close-up details (windows, door, label) on each building based on
// how close the camera is to it - cheap per-frame LOD.
const _bv = new THREE.Vector3();
function updateBuildingLOD() {
  if (!buildingLODs.length) return;
  const exag = terrainGroup.scale.y;
  for (const item of buildingLODs) {
    // World position of the schoolhouse (terrainGroup applies scale.y).
    _bv.copy(item.group.position);
    _bv.y *= exag;
    const dist = camera.position.distanceTo(_bv);
    item.details.visible = dist < DETAIL_DISTANCE;
    item.label.visible   = dist < LABEL_DISTANCE;
  }
}

function animate() {
  requestAnimationFrame(animate);
  controls.update();
  updateBuildingLOD();
  updateSimulation();
  renderer.render(scene, camera);
}
