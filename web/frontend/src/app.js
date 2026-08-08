import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { CSS2DRenderer, CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';

// ─── State ───
const state = {
  products: [],
  robots: [],
  gridInfo: null,
  wsConnected: false,
  sidebarOpen: window.innerWidth > 768,
  selectedProduct: null,
};

let editMode = false;
let selectedGridCell = null;
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
let hoverHighlight = null;

// ─── DOM refs ───
const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);
const dom = {
  view3d: $('#view3d'),
  sidebar: $('#sidebar'),
  menuToggle: $('#menuToggle'),
  overlay: $('#mobile-overlay'),
  status: $('#statusIndicator'),
  productSelect: $('#productSelect'),
  newRobotSelect: $('#newRobotProduct'),
  qtyInput: $('#qtyInput'),
  btnSupply: $('#btnSupply'),
  btnUnlabeled: $('#btnUnlabeled'),
  btnRequest: $('#btnRequest'),
  btnCreateRobot: $('#btnCreateRobot'),
  btnCreateProduct: $('#btnCreateProduct'),
  btnRebalance: $('#btnRebalance'),
  newProductName: $('#newProductName'),
  newProductColor: $('#newProductColor'),
  robotsContent: $('#robots-content'),
  statsContent: $('#stats-content'),
  logContent: $('#log-content'),
  gridWidth: $('#gridWidth'),
  gridHeight: $('#gridHeight'),
  btnApplyGrid: $('#btnApplyGrid'),
  btnEditMode: $('#btnEditMode'),
  editStatus: $('#editStatus'),
  editCellInfo: $('#editCellInfo'),
  cellInfoText: $('#cellInfoText'),
  btnSetExit: $('#btnSetExit'),
  btnSetInbound: $('#btnSetInbound'),
  btnSetPick: $('#btnSetPick'),
  btnAddShelf: $('#btnAddShelf'),
  btnRemoveShelf: $('#btnRemoveShelf'),
  editShelfInfo: $('#editShelfInfo'),
  editShelfCapacity: $('#editShelfCapacity'),
  btnApplyShelfCapacity: $('#btnApplyShelfCapacity'),
  editShelfProducts: $('#editShelfProducts'),
  btnApplyShelfProducts: $('#btnApplyShelfProducts'),
  editRobotHomeInfo: $('#editRobotHomeInfo'),
  editRobotHomeSelect: $('#editRobotHomeSelect'),
  btnSetRobotHome: $('#btnSetRobotHome'),
  btnTheme: $('#btnTheme'),
  uavColorPicker: $('#uavColorPicker'),
  btnSetUavColor: $('#btnSetUavColor'),
  btnExcel: $('#btnExcel'),
  btnAnalytics: $('#btnAnalytics'),
  analyticsModal: $('#analyticsModal'),
  btnAnalyticsClose: $('#btnAnalyticsClose'),
  btnRunAllTests: $('#btnRunAllTests'),
  testResults: $('#testResults'),
  scenarioButtons: $('#scenarioButtons'),
  analyticsTbody: $('#analyticsTbody'),
  analyticsSummary: $('#analyticsSummary'),
};

let analyticsChartInstance = null;

// ─── Three.js Scene ───
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0a0e1a);
let _sceneBgIsLight = false;
function setSceneTheme(isLight) {
  _sceneBgIsLight = isLight;
  scene.background = new THREE.Color(isLight ? 0xe8ecf1 : 0x0a0e1a);
}

const camera = new THREE.PerspectiveCamera(40, dom.view3d.clientWidth / dom.view3d.clientHeight, 0.1, 100);
camera.position.set(12, 14, 16);
camera.lookAt(0, 0, 0);

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(dom.view3d.clientWidth, dom.view3d.clientHeight);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.2;
dom.view3d.prepend(renderer.domElement);

const labelRenderer = new CSS2DRenderer();
labelRenderer.setSize(dom.view3d.clientWidth, dom.view3d.clientHeight);
labelRenderer.domElement.style.position = 'absolute';
labelRenderer.domElement.style.top = '0';
labelRenderer.domElement.style.left = '0';
labelRenderer.domElement.style.pointerEvents = 'none';
dom.view3d.appendChild(labelRenderer.domElement);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.maxPolarAngle = Math.PI / 2.3;
controls.minDistance = 4;
controls.maxDistance = 40;
controls.target.set(0, 0, 0);

// ─── Lights ───
const ambientLight = new THREE.AmbientLight(0x404060, 0.6);
scene.add(ambientLight);

const dirLight = new THREE.DirectionalLight(0xffeedd, 1.8);
dirLight.position.set(10, 20, 8);
dirLight.castShadow = true;
dirLight.shadow.mapSize.width = 2048;
dirLight.shadow.mapSize.height = 2048;
dirLight.shadow.camera.near = 1;
dirLight.shadow.camera.far = 40;
dirLight.shadow.camera.left = -15;
dirLight.shadow.camera.right = 15;
dirLight.shadow.camera.top = 15;
dirLight.shadow.camera.bottom = -15;
scene.add(dirLight);

const fillLight = new THREE.DirectionalLight(0x8888ff, 0.4);
fillLight.position.set(-8, 6, -10);
scene.add(fillLight);

// ─── Ground ───
const groundGeo = new THREE.PlaneGeometry(50, 50);
const groundMat = new THREE.ShadowMaterial({ opacity: 0.3 });
const ground = new THREE.Mesh(groundGeo, groundMat);
ground.rotation.x = -Math.PI / 2;
ground.position.y = -0.05;
ground.receiveShadow = true;
scene.add(ground);

// ─── Objects maps ───
const objects = {
  shelves: new Map(),
  robots: new Map(),
  specialCells: [],
  gridHelper: null,
  floorTiles: [],
  labels: new Map(),
  carryMeshes: new Map(),
  uav: { group: null, beam: null, props: null },
};

// ─── Helpers ───
function gridToWorld(x, y) {
  const w = state.gridInfo ? state.gridInfo.width : 16;
  const h = state.gridInfo ? state.gridInfo.height : 12;
  return { x: x - w / 2, z: y - h / 2 };
}

function hexToThree(hex) {
  return new THREE.Color(hex);
}

function makeLabel(text, color = '#f3f4f6', size = '12px', yOff = 0) {
  const div = document.createElement('div');
  div.textContent = text;
  div.style.color = color;
  div.style.fontSize = size;
  div.style.fontWeight = '600';
  div.style.textShadow = '0 1px 4px rgba(0,0,0,0.8)';
  div.style.padding = '2px 6px';
  div.style.borderRadius = '4px';
  div.style.background = 'rgba(0,0,0,0.5)';
  div.style.backdropFilter = 'blur(4px)';
  div.style.pointerEvents = 'none';
  div.style.whiteSpace = 'nowrap';
  const label = new CSS2DObject(div);
  label.position.y = yOff;
  return label;
}

// ─── Build scene ───
function buildGrid(gridInfo) {
  // Remove old grid
  if (objects.gridHelper) { scene.remove(objects.gridHelper); objects.gridHelper = null; }
  objects.floorTiles.forEach(m => scene.remove(m));
  objects.floorTiles = [];
  objects.specialCells.forEach(m => scene.remove(m));
  objects.specialCells = [];

  const w = gridInfo.width;
  const h = gridInfo.height;
  const shelfX = new Set(gridInfo.shelf_x);
  const homes = new Set(gridInfo.home_cells.map(p => `${p[0]},${p[1]}`));
  const customs = new Set(gridInfo.custom_shelves.map(p => `${p[0]},${p[1]}`));
  const removed = new Set(gridInfo.removed_shelves.map(p => `${p[0]},${p[1]}`));
  const exit = `${gridInfo.exit_cell[0]},${gridInfo.exit_cell[1]}`;
  const inbound = `${gridInfo.inbound_cell[0]},${gridInfo.inbound_cell[1]}`;
  const pick = `${gridInfo.inbound_pick_cell[0]},${gridInfo.inbound_pick_cell[1]}`;

  // Grid lines
  const gridHelper = new THREE.Group();
  const mat = new THREE.LineBasicMaterial({ color: 0x2a2a4a, transparent: true, opacity: 0.5 });
  for (let x = 0; x <= w; x++) {
    const p = gridToWorld(x, 0);
    const q = gridToWorld(x, h);
    const geo = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(p.x, 0, p.z), new THREE.Vector3(q.x, 0, q.z)
    ]);
    gridHelper.add(new THREE.Line(geo, mat));
  }
  for (let y = 0; y <= h; y++) {
    const p = gridToWorld(0, y);
    const q = gridToWorld(w, y);
    const geo = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(p.x, 0, p.z), new THREE.Vector3(q.x, 0, q.z)
    ]);
    gridHelper.add(new THREE.Line(geo, mat));
  }
  scene.add(gridHelper);
  objects.gridHelper = gridHelper;

  // Floor tiles and special cells
  for (let x = 0; x < w; x++) {
    for (let y = 0; y < h; y++) {
      const key = `${x},${y}`;
      const pos = gridToWorld(x, y);
      const isShelfRow = shelfX.has(x);
      const yExcl = y === 0 || y === 1 || y === 2 || y === 7 || y === 8 || y === 9;
      const isShelf = (isShelfRow && !yExcl && !removed.has(key)) || customs.has(key);
      const isHome = homes.has(key);

      let color = 0x15152a;
      if (isShelf) color = 0x1a1a35;
      if (isHome) color = 0x1a2a1a;
      if (key === exit) color = 0x2a1515;
      if (key === inbound) color = 0x152a15;
      if (key === pick) color = 0x15152a;

      const tileGeo = new THREE.PlaneGeometry(0.95, 0.95);
      const tileMat = new THREE.MeshStandardMaterial({ color, roughness: 0.8, metalness: 0.1 });
      const tile = new THREE.Mesh(tileGeo, tileMat);
      tile.rotation.x = -Math.PI / 2;
      tile.position.set(pos.x, 0.001, pos.z);
      tile.receiveShadow = true;
      scene.add(tile);
      objects.floorTiles.push(tile);

      // Special cell indicators
      if (key === exit) {
        const m = makeSpecialLabel(pos.x, pos.z, 'ВЫХОД', '#ef4444');
        objects.specialCells.push(m);
      } else if (key === inbound) {
        const m = makeSpecialLabel(pos.x, pos.z, 'ПРИЁМ', '#10b981');
        objects.specialCells.push(m);
      } else if (key === pick) {
        const m = makeSpecialLabel(pos.x, pos.z, 'ЗАБОР', '#3b82f6');
        objects.specialCells.push(m);
      } else if (key === `${gridInfo.uav_home[0]},${gridInfo.uav_home[1]}`) {
        const m = makeSpecialLabel(pos.x, pos.z, 'БВС', '#f59e0b');
        objects.specialCells.push(m);
      }
    }
  }
}

function makeSpecialLabel(wx, wz, text, color) {
  const div = document.createElement('div');
  div.textContent = text;
  div.style.color = color;
  div.style.fontSize = '10px';
  div.style.fontWeight = '700';
  div.style.textShadow = '0 1px 3px rgba(0,0,0,0.9)';
  div.style.background = 'rgba(0,0,0,0.6)';
  div.style.padding = '1px 5px';
  div.style.borderRadius = '3px';
  div.style.border = `1px solid ${color}`;
  const label = new CSS2DObject(div);
  label.position.set(wx, 0.05, wz);
  scene.add(label);
  return label;
}

// ─── Update shelves ───
function updateShelves(shelvesData) {
  const current = new Set();

  for (const s of shelvesData) {
    const x = s.x !== undefined ? s.x : s[0];
    const y = s.y !== undefined ? s.y : s[1];
    const product = s.product !== undefined ? s.product : s[2];
    const count = s.count !== undefined ? s.count : s[3];
    const key = `${x},${y}`;
    current.add(key);
    const pos = gridToWorld(x, y);

    if (objects.shelves.has(key)) {
      const obj = objects.shelves.get(key);
      const height = Math.max(0.1, count * 0.25 + 0.05);
      obj.geometry.dispose();
      obj.geometry = new THREE.BoxGeometry(0.85, height, 0.85);
      obj.position.set(pos.x, height / 2, pos.z);
      if (product && count > 0) {
        const c = state.products.find(p => p.name === product);
        obj.material.color = c ? hexToThree(c.color) : new THREE.Color(0x666666);
        obj.material.opacity = 1;
      } else {
        obj.material.color = new THREE.Color(0x333355);
        obj.material.opacity = 0.4;
      }
      if (objects.labels.has(key + '_shelf')) {
        const lbl = objects.labels.get(key + '_shelf');
        lbl.element.textContent = product ? `${product} [${count}]` : '';
        lbl.position.set(pos.x, height + 0.6, pos.z);
      }
    } else {
      const height = Math.max(0.1, count * 0.25 + 0.05);
      const geo = new THREE.BoxGeometry(0.85, height, 0.85);
      const mat = new THREE.MeshStandardMaterial({
        roughness: 0.6, metalness: 0.2,
      });
      const mesh = new THREE.Mesh(geo, mat);
      if (product && count > 0) {
        const c = state.products.find(p => p.name === product);
        mat.color = c ? hexToThree(c.color) : new THREE.Color(0x666666);
      } else {
        mat.color = new THREE.Color(0x333355);
        mat.transparent = true;
        mat.opacity = 0.4;
      }
      mesh.position.set(pos.x, height / 2, pos.z);
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      scene.add(mesh);
      objects.shelves.set(key, mesh);

      const lblText = product ? `${product} [${count}]` : '';
      const lbl = makeLabel(lblText, '#9ca3af', '10px', height + 0.6);
      lbl.position.set(pos.x, height + 0.6, pos.z);
      scene.add(lbl);
      objects.labels.set(key + '_shelf', lbl);
    }
  }

  for (const [key, mesh] of objects.shelves) {
    if (!current.has(key)) {
      scene.remove(mesh);
      mesh.geometry.dispose();
      mesh.material.dispose();
      objects.shelves.delete(key);
    }
  }
  for (const [key, lbl] of objects.labels) {
    if (key.endsWith('_shelf')) {
      const shelfKey = key.replace('_shelf', '');
      if (!current.has(shelfKey)) {
        scene.remove(lbl);
        objects.labels.delete(key);
      }
    }
  }
}

// ─── Recolor floor tiles when shelf config changes ───
function recolorFloorTiles(gridInfo) {
  if (!gridInfo || objects.floorTiles.length === 0) return;
  const w = gridInfo.width;
  const h = gridInfo.height;
  const shelfX = new Set(gridInfo.shelf_x);
  const homes = new Set(gridInfo.home_cells.map(p => `${p[0]},${p[1]}`));
  const customs = new Set(gridInfo.custom_shelves.map(p => `${p[0]},${p[1]}`));
  const removed = new Set(gridInfo.removed_shelves.map(p => `${p[0]},${p[1]}`));
  const exit = `${gridInfo.exit_cell[0]},${gridInfo.exit_cell[1]}`;
  const inbound = `${gridInfo.inbound_cell[0]},${gridInfo.inbound_cell[1]}`;
  const pick = `${gridInfo.inbound_pick_cell[0]},${gridInfo.inbound_pick_cell[1]}`;

  let idx = 0;
  for (let x = 0; x < w; x++) {
    for (let y = 0; y < h; y++) {
      if (idx >= objects.floorTiles.length) return;
      const key = `${x},${y}`;
      const isShelfRow = shelfX.has(x);
      const yExcl = y === 0 || y === 1 || y === 2 || y === 7 || y === 8 || y === 9;
      const isShelf = (isShelfRow && !yExcl && !removed.has(key)) || customs.has(key);
      const isHome = homes.has(key);

      let color = 0x15152a;
      if (isShelf) color = 0x1a1a35;
      if (isHome) color = 0x1a2a1a;
      if (key === exit) color = 0x2a1515;
      if (key === inbound) color = 0x152a15;
      if (key === pick) color = 0x15152a;

      objects.floorTiles[idx].material.color.setHex(color);
      idx++;
    }
  }
}

// ─── Update robots ───
function updateRobots(robotsData) {
  const current = new Set();

  for (const r of robotsData) {
    current.add(r.id);
    const pos = gridToWorld(r.draw_pos[0], r.draw_pos[1]);
    const color = hexToThree(r.color);

    if (objects.robots.has(r.id)) {
      const obj = objects.robots.get(r.id);
      obj.group.position.lerp(new THREE.Vector3(pos.x, 0.15, pos.z), 0.3);
      obj.head.material.color.lerp(color, 0.2);

      // Update label
      const lbl = objects.labels.get('robot_' + r.id);
      if (lbl) {
        lbl.position.copy(obj.group.position);
        lbl.position.y += 0.7;
        lbl.element.textContent = r.name + (r.carry ? ` [${r.carry}]` : '');
        lbl.element.style.color = r.phase === 'idle' ? '#9ca3af' : '#f3f4f6';
      }

      // Carry indicator
      if (objects.carryMeshes.has(r.id)) {
        const c = objects.carryMeshes.get(r.id);
        if (r.carry) {
          c.visible = true;
          const prod = state.products.find(p => p.name === r.carry);
          if (prod) c.material.color = hexToThree(prod.color);
          c.position.copy(obj.group.position);
          c.position.y += 0.45 + r.carry_bob;
        } else {
          c.visible = false;
        }
      }
    } else {
      const group = new THREE.Group();
      group.position.set(pos.x, 0.15, pos.z);

      // Body
      const body = new THREE.Mesh(
        new THREE.BoxGeometry(0.35, 0.18, 0.28),
        new THREE.MeshStandardMaterial({ color: 0x2a2a4a, roughness: 0.5, metalness: 0.3 })
      );
      body.position.y = 0.09;
      body.castShadow = true;
      group.add(body);

      // Head
      const head = new THREE.Mesh(
        new THREE.CylinderGeometry(0.14, 0.16, 0.14, 10),
        new THREE.MeshStandardMaterial({ color, roughness: 0.3, metalness: 0.5 })
      );
      head.position.y = 0.27;
      head.castShadow = true;
      group.add(head);

      // Eyes
      const eyeMat = new THREE.MeshStandardMaterial({ color: 0x00ff88, emissive: 0x00ff88, emissiveIntensity: 0.4 });
      for (const side of [-1, 1]) {
        const eye = new THREE.Mesh(new THREE.SphereGeometry(0.035, 6, 6), eyeMat);
        eye.position.set(side * 0.07, 0.3, 0.12);
        group.add(eye);
      }

      // Antenna
      const ant = new THREE.Mesh(
        new THREE.CylinderGeometry(0.008, 0.008, 0.1, 4),
        new THREE.MeshStandardMaterial({ color: 0x888888, metalness: 0.6 })
      );
      ant.position.y = 0.36;
      group.add(ant);
      const antBall = new THREE.Mesh(
        new THREE.SphereGeometry(0.02, 6, 6),
        new THREE.MeshStandardMaterial({ color: 0xff4444, emissive: 0xff4444, emissiveIntensity: 0.3 })
      );
      antBall.position.y = 0.42;
      group.add(antBall);

      // Wheels
      const wheelMat = new THREE.MeshStandardMaterial({ color: 0x111111, roughness: 0.9 });
      for (const side of [-1, 1]) {
        for (const front of [-1, 1]) {
          const wheel = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.04, 0.035, 8), wheelMat);
          wheel.rotation.x = Math.PI / 2;
          wheel.position.set(side * 0.19, 0.03, front * 0.13);
          group.add(wheel);
        }
      }

      scene.add(group);
      objects.robots.set(r.id, { group, head });

      // Label
      const lbl = makeLabel(r.name, '#f3f4f6', '11px', 0.8);
      lbl.position.set(pos.x, 0.7, pos.z);
      scene.add(lbl);
      objects.labels.set('robot_' + r.id, lbl);

      // Carry indicator box
      const carryMesh = new THREE.Mesh(
        new THREE.BoxGeometry(0.18, 0.18, 0.18),
        new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xffffff, emissiveIntensity: 0.2 })
      );
      carryMesh.visible = false;
      scene.add(carryMesh);
      objects.carryMeshes.set(r.id, carryMesh);
    }
  }

  // Remove old robots
  for (const [id, obj] of objects.robots) {
    if (!current.has(id)) {
      scene.remove(obj.group);
      obj.group.traverse(c => { if (c.isMesh) { c.geometry.dispose(); c.material.dispose(); } });
      objects.robots.delete(id);
      const lbl = objects.labels.get('robot_' + id);
      if (lbl) { scene.remove(lbl); objects.labels.delete('robot_' + id); }
      const c = objects.carryMeshes.get(id);
      if (c) { scene.remove(c); c.geometry.dispose(); c.material.dispose(); objects.carryMeshes.delete(id); }
    }
  }
}

// ─── Update UAV ───
function updateUAV(uavData) {
  const pos = gridToWorld(uavData.pos[0], uavData.pos[1]);
  const yAlt = uavData.pos[2];

  // Compute UAV color: custom uav_color if set and not white, else fallback amber
  const uavColor = (uavData.uav_color && uavData.uav_color.toLowerCase() !== '#ffffff')
    ? uavData.uav_color : '#f59e0b';
  const uavCol = hexToThree(uavColor);

  if (!objects.uav.group) {
    const group = new THREE.Group();
    const props = [];

    // Central body
    const body = new THREE.Mesh(
      new THREE.BoxGeometry(0.18, 0.06, 0.12),
      new THREE.MeshStandardMaterial({ color: uavCol, emissive: uavCol, emissiveIntensity: 0.3, roughness: 0.4, metalness: 0.3 })
    );
    body.position.y = 0.03;
    group.add(body);

    // Arms
    const armMat = new THREE.MeshStandardMaterial({ color: 0x666666, metalness: 0.5 });
    const armLen = 0.25;
    for (let i = 0; i < 4; i++) {
      const angle = (i / 4) * Math.PI * 2 + Math.PI / 4;
      const arm = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.012, armLen, 4), armMat);
      arm.rotation.z = Math.PI / 2;
      arm.position.set(Math.cos(angle) * armLen / 2, 0.03, Math.sin(angle) * armLen / 2);
      group.add(arm);
    }

    // Propellers
    const propMat = new THREE.MeshStandardMaterial({
      color: 0x444444, transparent: true, opacity: 0.4, side: THREE.DoubleSide
    });
    for (let i = 0; i < 4; i++) {
      const angle = (i / 4) * Math.PI * 2 + Math.PI / 4;
      const prop = new THREE.Mesh(new THREE.CircleGeometry(0.08, 12), propMat);
      prop.rotation.x = Math.PI / 2;
      prop.position.set(Math.cos(angle) * armLen, 0.06, Math.sin(angle) * armLen);
      group.add(prop);
      props.push(prop);
    }

    // Landing skids
    const skidMat = new THREE.MeshStandardMaterial({ color: 0x333333 });
    for (const side of [-1, 1]) {
      const skid = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.012, 0.012), skidMat);
      skid.position.set(side * 0.08, 0, 0);
      group.add(skid);
      const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.006, 0.006, 0.04, 4), skidMat);
      leg.position.set(side * 0.08, -0.025, 0);
      group.add(leg);
    }

    // Camera underneath
    const cam = new THREE.Mesh(
      new THREE.SphereGeometry(0.025, 8, 8),
      new THREE.MeshStandardMaterial({ color: 0x222244, emissive: 0x4444ff, emissiveIntensity: 0.15 })
    );
    cam.position.y = -0.02;
    group.add(cam);

    scene.add(group);
    objects.uav.group = group;
    objects.uav.props = props;

    // Scan beam
    const beamGeo = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(0, 0, 0), new THREE.Vector3(0, -yAlt, 0)
    ]);
    const beam = new THREE.Line(
      beamGeo,
      new THREE.LineBasicMaterial({ color: uavCol, transparent: true, opacity: 0.3 })
    );
    scene.add(beam);
    objects.uav.beam = beam;
  }

  const group = objects.uav.group;
  group.position.set(pos.x, yAlt + 0.2, pos.z);
  group.rotation.y += 0.03;
  group.position.y += Math.sin(Date.now() / 400) * 0.02;

  // Spin propellers
  if (objects.uav.props) {
    for (const prop of objects.uav.props) {
      prop.rotation.z += 0.8;
    }
  }

  // Update body + beam color
  group.children[0].material.color.copy(uavCol);
  if (objects.uav.beam) objects.uav.beam.material.color.copy(uavCol);

  // Pulsing scan effect
  if (uavData.state === 'scanning') {
    const pulse = 0.3 + Math.sin(Date.now() / 200) * 0.2;
    group.children[0].material.emissiveIntensity = pulse;
    if (objects.uav.beam) {
      objects.uav.beam.material.opacity = pulse;
      const pos2 = gridToWorld(uavData.pos[0], uavData.pos[1]);
      const positions = objects.uav.beam.geometry.attributes.position;
      if (positions) {
        positions.setXYZ(0, 0, 0, 0);
        positions.setXYZ(1, 0, -yAlt, 0);
        positions.needsUpdate = true;
      }
      objects.uav.beam.visible = true;
    }
  } else {
    if (objects.uav.beam) objects.uav.beam.visible = false;
  }
}

// ─── UI Updates ───
let _prevProductsStr = '';

function updateControls() {
  const prodStr = JSON.stringify(state.products.map(p => p.name));
  if (prodStr === _prevProductsStr) return;
  _prevProductsStr = prodStr;

  const sel = dom.productSelect;
  const prev = sel.value;
  const prevRobot = dom.newRobotSelect.value;
  sel.innerHTML = state.products.map(p =>
    `<option value="${p.name}">${p.name}</option>`
  ).join('');
  dom.newRobotSelect.innerHTML = state.products.map(p =>
    `<option value="${p.name}">${p.name}</option>`
  ).join('');
  if (prev && sel.querySelector(`option[value="${prev}"]`)) sel.value = prev;
  if (prevRobot && dom.newRobotSelect.querySelector(`option[value="${prevRobot}"]`)) dom.newRobotSelect.value = prevRobot;
}

function updateRobotsUI(robotsData) {
  const container = dom.robotsContent;

  // Preserve focused rename inputs and active slider/capacity values across HTML rebuild
  const focused = {};
  container.querySelectorAll('.robot-name-input:focus').forEach(inp => {
    focused[inp.dataset.rid] = inp.value;
  });
  const sliderVals = {};
  container.querySelectorAll('input[type="range"][data-action="speed"]').forEach(sl => {
    if (sl.matches(':active')) sliderVals[sl.dataset.rid] = sl.value;
  });
  const capVals = {};
  container.querySelectorAll('input[type="number"][data-action="capacity"]').forEach(inp => {
    if (inp.matches(':focus')) capVals[inp.dataset.rid] = inp.value;
  });

  container.innerHTML = robotsData.map(r => {
    const phaseClass = r.phase === 'idle' ? 'idle' : (r.phase.includes('exit') || r.phase.includes('deliver') ? 'to_exit' : (r.carry ? 'carrying' : 'active'));
    const productCheckboxes = state.products.map(p => {
      const checked = r.products.includes(p.name);
      return `<label><input type="checkbox" data-rid="${r.id}" data-prod="${p.name}" ${checked ? 'checked' : ''}>${p.name}</label>`;
    }).join('');
    const nameVal = focused[r.id] !== undefined ? focused[r.id] : r.name;
    const spdVal = sliderVals[r.id] !== undefined ? sliderVals[r.id] : r.speed;
    const capVal = capVals[r.id] !== undefined ? capVals[r.id] : r.capacity;
    return `<div class="robot-card" style="border-left-color:${r.color}">
      <div class="robot-header">
        <span class="robot-dot" style="background:${r.color}"></span>
        <input type="text" class="robot-name-input" value="${nameVal.replace(/"/g, '&quot;')}" data-rid="${r.id}" data-action="rename">
        <span class="robot-phase ${phaseClass}">${r.phase}${r.carry ? ' ['+r.carry+']' : ''}</span>
      </div>
      <div class="robot-details">
        <span>🚀 ${parseFloat(spdVal).toFixed(2)}</span>
        <span>📦 ${capVal}</span>
        <span>📍 ${r.draw_pos[0].toFixed(1)},${r.draw_pos[1].toFixed(1)}</span>
        <span>🏠 (${r.home[0]},${r.home[1]})</span>
      </div>
      <div class="product-checkboxes">${productCheckboxes}</div>
      <div class="robot-controls">
        <label>Скорость <input type="range" min="0" max="1" step="0.01" value="${spdVal}" data-rid="${r.id}" data-action="speed"></label>
        <label>Вмест. <input type="number" min="1" max="10" value="${capVal}" data-rid="${r.id}" data-action="capacity" class="cap-input"></label>
        <div class="color-picker-wrapper" style="display:inline-flex"><input type="color" value="${r.color}" data-rid="${r.id}" data-action="robotcolor" style="width:28px;height:24px;padding:1px;border-radius:3px;"></div>
        <button class="btn btn-danger btn-sm" data-rid="${r.id}" data-action="reset">Сброс</button>
      </div>
    </div>`;
  }).join('');

  // Restore focus to edited name inputs
  Object.keys(focused).forEach(rid => {
    const inp = container.querySelector(`.robot-name-input[data-rid="${rid}"]`);
    if (inp) {
      inp.value = focused[rid];
      inp.focus();
      const len = inp.value.length;
      inp.setSelectionRange(len, len);
    }
  });

  // Checkboxes handled by delegated click on robotsContent (see setupHandlers)
}

function updateStatsUI(products) {
  const container = dom.statsContent;
  const totalStock = products.reduce((s, p) => s + p.stock_total, 0);
  const totalDelivered = products.reduce((s, p) => s + p.delivered, 0);
  const totalRetrieved = products.reduce((s, p) => s + (p.retrieved || 0), 0);
  let html = `<div class="stats-summary">
    <span class="stat-chip" style="border-left-color:var(--accent)"><strong>${totalStock}</strong> Было</span>
    <span class="stat-chip" style="border-left-color:var(--success)"><strong>${totalDelivered}</strong> Отправлено</span>
    <span class="stat-chip" style="border-left-color:var(--danger)"><strong>${totalRetrieved}</strong> Забрано</span>
  </div>`;
  html += `<table class="stats-table">
    <tr><th></th><th>Материал</th><th>Всего</th><th>Спрос</th><th>Доставлено</th><th>Забрано</th><th>В очереди</th></tr>`;
  for (const p of products) {
    html += `<tr>
      <td><span class="color-dot" style="background:${p.color}"></span></td>
      <td>${p.name}</td>
      <td>${p.stock_total}</td>
      <td>${p.demand}</td>
      <td>${p.delivered}</td>
      <td>${p.retrieved || 0}</td>
      <td>${p.queue_length}</td>
    </tr>`;
  }
  html += `</table>`;
  container.innerHTML = html;
}

function updateLogUI(logData) {
  const container = dom.logContent;
  container.innerHTML = logData.slice(0, 100).map(msg => {
    let cls = 'log-entry';
    if (msg.includes('⚠')) cls += ' warn';
    else if (msg.includes('ВНИМАНИЕ')) cls += ' error';
    else if (msg.includes('доставил') || msg.includes('разместил') || msg.includes('завершен')) cls += ' success';
    else cls += ' info';
    return `<div class="${cls}">${msg}</div>`;
  }).join('');
}

// ─── WebSocket ───
let ws = null;
let reconnectTimer = null;
let isReconnecting = false;

function connectWS() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const url = `${protocol}//${window.location.host}/ws`;
  dom.status.textContent = 'Подключение...';
  dom.status.className = 'connecting';

  ws = new WebSocket(url);
  ws.onopen = () => {
    state.wsConnected = true;
    dom.status.textContent = 'Подключено';
    dom.status.className = 'connected';
    isReconnecting = false;
  };
  ws.onclose = () => {
    state.wsConnected = false;
    dom.status.textContent = 'Отключено';
    dom.status.className = '';
    scheduleReconnect();
  };
  ws.onerror = () => {
    if (!isReconnecting) {
      dom.status.textContent = 'Ошибка';
      dom.status.className = '';
    }
  };
  ws.onmessage = (evt) => {
    try {
      const msg = JSON.parse(evt.data);
      if (msg.type === 'state_update') {
        onStateUpdate(msg.data);
      }
    } catch (e) {
      console.error('WS parse error', e);
    }
  };
}

function send(data) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(data));
  }
}

function scheduleReconnect() {
  if (reconnectTimer) clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(() => {
    isReconnecting = true;
    connectWS();
  }, 2000);
}

// ─── State update handler ───
function onStateUpdate(data) {
  state.robots = data.robots;
  state.products = data.products;
  state.gridInfo = data.grid_info;

  // Cache shelf metadata for edit panel
  state.shelfCapacityCache = {};
  state.shelfAllowedCache = {};
  for (const s of (data.shelves || [])) {
    const x = s.x !== undefined ? s.x : s[0];
    const y = s.y !== undefined ? s.y : s[1];
    const key = `${x},${y}`;
    if (s.capacity !== undefined) state.shelfCapacityCache[key] = s.capacity;
    if (s.allowed_products !== undefined) state.shelfAllowedCache[key] = s.allowed_products;
  }

  checkGridRebuild(data.grid_info);
  recolorFloorTiles(data.grid_info);
  updateShelves(data.shelves);
  updateRobots(data.robots);
  updateUAV(data.uav);
  // Sync UAV color picker with current state
  if (data.uav && data.uav.uav_color) {
    dom.uavColorPicker.value = data.uav.uav_color;
  }
  updateControls();
  updateRobotsUI(data.robots);
  updateStatsUI(data.products);
  updateLogUI(data.log);
}

// ─── Grid / Edit mode ───
function getGridCellFromMouse(event) {
  const rect = renderer.domElement.getBoundingClientRect();
  pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
  const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
  const intersection = new THREE.Vector3();
  if (!raycaster.ray.intersectPlane(plane, intersection)) return null;
  if (!state.gridInfo) return null;
  const w = state.gridInfo.width;
  const h = state.gridInfo.height;
  const gx = Math.round(intersection.x + w / 2 - 0.5);
  const gy = Math.round(intersection.z + h / 2 - 0.5);
  if (gx < 0 || gx >= w || gy < 0 || gy >= h) return null;
  return { x: gx, y: gy };
}

function updateHoverHighlight(cell) {
  if (!hoverHighlight) {
    const geo = new THREE.PlaneGeometry(0.95, 0.95);
    const mat = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.2, depthWrite: false, side: THREE.DoubleSide });
    hoverHighlight = new THREE.Mesh(geo, mat);
    hoverHighlight.rotation.x = -Math.PI / 2;
    hoverHighlight.position.y = 0.01;
    scene.add(hoverHighlight);
  }
  if (cell) {
    const pos = gridToWorld(cell.x, cell.y);
    hoverHighlight.position.set(pos.x, 0.01, pos.z);
    hoverHighlight.visible = true;
  } else {
    hoverHighlight.visible = false;
  }
}

function updateEditPanel(cell) {
  dom.editShelfInfo.style.display = 'none';
  dom.editRobotHomeInfo.style.display = 'none';
  if (!cell || !state.gridInfo) return;

  const { x, y } = cell;
  const key = `${x},${y}`;
  const isShelfRow = new Set(state.gridInfo.shelf_x).has(x);
  const yExcl = [0,1,2,7,8,9].includes(y);
  const removed = new Set(state.gridInfo.removed_shelves.map(p => `${p[0]},${p[1]}`));
  const customs = new Set(state.gridInfo.custom_shelves.map(p => `${p[0]},${p[1]}`));
  const isShelf = (isShelfRow && !yExcl && !removed.has(key)) || customs.has(key);

  if (isShelf) {
    dom.editShelfInfo.style.display = 'flex';
    dom.editShelfCapacity.value = state.shelfCapacityCache ? (state.shelfCapacityCache[key] || 5) : 5;
    // Build product checkboxes for this shelf
    const allowed = state.shelfAllowedCache ? state.shelfAllowedCache[key] : null;
    dom.editShelfProducts.innerHTML = state.products.map(p => {
      const ch = !allowed || allowed.includes(p.name);
      return `<label><input type="checkbox" value="${p.name}" ${ch ? 'checked' : ''}>${p.name}</label>`;
    }).join('');
  }

  // Robot home assignment (show for any non-shelf cell)
  if (!isShelf) {
    dom.editRobotHomeInfo.style.display = 'flex';
    dom.editRobotHomeSelect.innerHTML = state.robots.map(r =>
      `<option value="${r.id}">${r.name} (${r.home[0]},${r.home[1]})</option>`
    ).join('');
  }
}

function setupGridHandlers() {
  dom.btnEditMode.addEventListener('click', () => {
    editMode = !editMode;
    dom.editStatus.textContent = editMode ? 'вкл' : 'выкл';
    dom.editStatus.style.color = editMode ? 'var(--warning)' : 'var(--text-muted)';
    dom.editCellInfo.style.display = editMode ? 'flex' : 'none';
    renderer.domElement.style.cursor = editMode ? 'crosshair' : 'default';
    if (!editMode) {
      selectedGridCell = null;
      dom.cellInfoText.textContent = '—';
      updateHoverHighlight(null);
      dom.editShelfInfo.style.display = 'none';
      dom.editRobotHomeInfo.style.display = 'none';
    }
  });

  dom.btnApplyGrid.addEventListener('click', () => {
    const w = parseInt(dom.gridWidth.value) || 16;
    const h = parseInt(dom.gridHeight.value) || 12;
    send({ type: 'set_grid_size', data: { width: Math.min(30, Math.max(8, w)), height: Math.min(20, Math.max(6, h)) } });
  });

  dom.btnSetExit.addEventListener('click', () => {
    if (!selectedGridCell) return;
    send({ type: 'set_exit_cell', data: { x: selectedGridCell.x, y: selectedGridCell.y } });
  });
  dom.btnSetInbound.addEventListener('click', () => {
    if (!selectedGridCell) return;
    send({ type: 'set_inbound_cell', data: { x: selectedGridCell.x, y: selectedGridCell.y } });
  });
  dom.btnSetPick.addEventListener('click', () => {
    if (!selectedGridCell) return;
    send({ type: 'set_inbound_pick_cell', data: { x: selectedGridCell.x, y: selectedGridCell.y } });
  });
  dom.btnAddShelf.addEventListener('click', () => {
    if (!selectedGridCell) return;
    const { x, y } = selectedGridCell;
    send({ type: 'add_custom_shelf', data: { x, y } });
  });
  dom.btnRemoveShelf.addEventListener('click', () => {
    if (!selectedGridCell) return;
    const { x, y } = selectedGridCell;
    send({ type: 'remove_custom_shelf', data: { x, y } });
  });

  // Shelf capacity apply
  dom.btnApplyShelfCapacity.addEventListener('click', () => {
    if (!selectedGridCell) return;
    const cap = parseInt(dom.editShelfCapacity.value) || 5;
    send({ type: 'set_shelf_capacity', data: { x: selectedGridCell.x, y: selectedGridCell.y, capacity: cap } });
  });

  // Shelf allowed products apply — all checked = any
  dom.btnApplyShelfProducts.addEventListener('click', () => {
    if (!selectedGridCell) return;
    const checked = [...dom.editShelfProducts.querySelectorAll('input[type="checkbox"]:checked')].map(el => el.value);
    const allChecked = checked.length === state.products.length && state.products.every(p => checked.includes(p.name));
    send({
      type: 'set_shelf_allowed_products',
      data: { x: selectedGridCell.x, y: selectedGridCell.y, products: allChecked ? null : checked }
    });
  });

  // Robot home assignment
  dom.btnSetRobotHome.addEventListener('click', () => {
    if (!selectedGridCell) return;
    const rid = parseInt(dom.editRobotHomeSelect.value);
    if (isNaN(rid)) return;
    send({ type: 'set_robot_home', data: { robot_id: rid, home_x: selectedGridCell.x, home_y: selectedGridCell.y } });
  });
  dom.btnSetUavColor.addEventListener('click', () => {
    send({ type: 'set_uav_color', data: { color: dom.uavColorPicker.value } });
  });

  // Mouse events for cell selection
  renderer.domElement.addEventListener('mousemove', (event) => {
    if (!editMode) { updateHoverHighlight(null); return; }
    const cell = getGridCellFromMouse(event);
    updateHoverHighlight(cell);
  });

  renderer.domElement.addEventListener('click', (event) => {
    if (!editMode) return;
    if (event.button !== 0) return;
    const cell = getGridCellFromMouse(event);
    if (!cell) return;
    selectedGridCell = cell;
    dom.cellInfoText.textContent = `Ячейка: (${cell.x}, ${cell.y})`;
    updateEditPanel(cell);
  });

  // Update grid size inputs when state changes
  if (state.gridInfo) {
    dom.gridWidth.value = state.gridInfo.width;
    dom.gridHeight.value = state.gridInfo.height;
  }
}

// ─── Grid rebuild ───
let lastGridDim = null;

function checkGridRebuild(gridInfo) {
  if (!gridInfo) return;
  const dim = `${gridInfo.width}x${gridInfo.height}`;
  if (lastGridDim !== dim) {
    // Full rebuild
    if (objects.gridHelper) scene.remove(objects.gridHelper);
    objects.floorTiles.forEach(m => scene.remove(m));
    objects.floorTiles = [];
    objects.specialCells.forEach(m => scene.remove(m));
    objects.specialCells = [];
    objects.shelves.forEach((m, k) => { scene.remove(m); m.geometry.dispose(); m.material.dispose(); });
    objects.shelves.clear();
    objects.labels.forEach((l, k) => { if (k.endsWith('_shelf')) scene.remove(l); });
    // Clear shelf labels only
    for (const [k, l] of objects.labels) { if (k.endsWith('_shelf')) { scene.remove(l); } }
    objects.labels = new Map([...objects.labels].filter(([k]) => !k.endsWith('_shelf')));
    buildGrid(gridInfo);
    lastGridDim = dim;
    dom.gridWidth.value = gridInfo.width;
    dom.gridHeight.value = gridInfo.height;
  }
}

// ─── Animation loop ───
function animate() {
  requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene, camera);
  labelRenderer.render(scene, camera);
}

// ─── Event handlers ───
function setupHandlers() {
  // Menu toggle (mobile)
  dom.menuToggle.addEventListener('click', () => {
    state.sidebarOpen = !state.sidebarOpen;
    dom.sidebar.classList.toggle('open', state.sidebarOpen);
    dom.overlay.classList.toggle('visible', state.sidebarOpen);
  });
  dom.overlay.addEventListener('click', () => {
    state.sidebarOpen = false;
    dom.sidebar.classList.remove('open');
    dom.overlay.classList.remove('visible');
  });

  // Panel collapse
  $$('.panel-header').forEach(h => {
    h.addEventListener('click', () => {
      h.classList.toggle('collapsed');
    });
  });

  // Controls
  dom.btnSupply.addEventListener('click', () => {
    send({ type: 'supply_labeled', data: { product: dom.productSelect.value, qty: parseInt(dom.qtyInput.value) || 1 } });
  });
  dom.btnUnlabeled.addEventListener('click', () => {
    send({ type: 'supply_unlabeled', data: { qty: parseInt(dom.qtyInput.value) || 1 } });
  });
  dom.btnRequest.addEventListener('click', () => {
    send({ type: 'request_product', data: { product: dom.productSelect.value, qty: parseInt(dom.qtyInput.value) || 1 } });
  });
  dom.btnCreateRobot.addEventListener('click', () => {
    send({ type: 'create_robot', data: { product: dom.newRobotSelect.value } });
  });
  dom.btnCreateProduct.addEventListener('click', () => {
    const name = dom.newProductName.value.trim();
    if (!name) return;
    const hex = dom.newProductColor.value;
    const r = parseInt(hex.slice(1, 3), 16) / 255;
    const g = parseInt(hex.slice(3, 5), 16) / 255;
    const b = parseInt(hex.slice(5, 7), 16) / 255;
    send({ type: 'create_product', data: { name, color: [r, g, b, 1.0] } });
    dom.newProductName.value = '';
  });
  dom.btnRebalance.addEventListener('click', () => {
    send({ type: 'rebalance', data: {} });
  });

  // Delegated events for robot controls
  // change stays on range (fires on mouseup on the NEW slider, survives rebuild)
  dom.robotsContent.addEventListener('change', (e) => {
    const el = e.target;
    if (el.type === 'range') {
      send({
        type: 'set_robot_speed',
        data: { robot_id: parseInt(el.dataset.rid), speed: parseFloat(el.value) }
      });
    }
  });
  // input fires synchronously on value change, before the tick rebuild can
  // detach the element — use it for capacity and rename.
  dom.robotsContent.addEventListener('input', (e) => {
    const el = e.target;
    if (el.type === 'number' && el.dataset.action === 'capacity') {
      send({
        type: 'set_robot_capacity',
        data: { robot_id: parseInt(el.dataset.rid), capacity: parseInt(el.value) || 1 }
      });
    }
    if (el.dataset.action === 'rename') {
      send({
        type: 'rename_robot',
        data: { robot_id: parseInt(el.dataset.rid), name: el.value }
      });
    }
  });
  // Everything is handled on mousedown because the 50ms tick rebuilds HTML
  // between mousedown and mouseup/click, causing click to fire on a detached
  // element whose event never bubbles to robotsContent.
  dom.robotsContent.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;

    // Reset button
    const btn = e.target.closest('[data-action="reset"]');
    if (btn) {
      send({ type: 'reset_robot', data: { robot_id: parseInt(btn.dataset.rid) } });
      return;
    }

    // Colour picker — use a temp input to open the native browser dialog
    // since the original may be detached by the time click fires.
    const colorInput = e.target.closest('input[type="color"][data-action="robotcolor"]');
    if (colorInput) {
      e.preventDefault();
      const temp = document.createElement('input');
      temp.type = 'color';
      temp.value = colorInput.value;
      temp.style.position = 'fixed';
      temp.style.left = '-9999px';
      temp.style.top = '-9999px';
      temp.style.opacity = '0';
      temp.style.pointerEvents = 'none';
      document.body.appendChild(temp);
      const rid = colorInput.dataset.rid;
      temp.addEventListener('change', function handler() {
        send({ type: 'set_robot_color', data: { robot_id: parseInt(rid), color: temp.value } });
        if (temp.parentNode) document.body.removeChild(temp);
      });
      temp.addEventListener('blur', function handler() {
        if (temp.parentNode) document.body.removeChild(temp);
      });
      temp.click();
      return;
    }

    // Checkbox — mousedown fires before the native toggle, so send OPPOSITE state
    let input = e.target.closest('input[type="checkbox"]');
    if (!input) {
      const label = e.target.closest('label');
      if (label) input = label.querySelector('input[type="checkbox"]');
    }
    if (!input) return;
    send({
      type: 'set_robot_product',
      data: { robot_id: parseInt(input.dataset.rid), product: input.dataset.prod, enabled: !input.checked }
    });
  });

  // Excel export
  dom.btnExcel.addEventListener('click', () => {
    const a = document.createElement('a');
    a.href = '/api/export/excel';
    a.download = 'magsim_report.xlsx';
    a.click();
  });

  // Analytics modal
  dom.btnAnalytics.addEventListener('click', () => {
    dom.analyticsModal.style.display = 'flex';
    fetchAnalytics();
  });
  dom.btnAnalyticsClose.addEventListener('click', () => {
    dom.analyticsModal.style.display = 'none';
  });
  dom.analyticsModal.addEventListener('click', (e) => {
    if (e.target === dom.analyticsModal) dom.analyticsModal.style.display = 'none';
  });

  // Resize
  window.addEventListener('resize', () => {
    const w = dom.view3d.clientWidth;
    const h = dom.view3d.clientHeight;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
    labelRenderer.setSize(w, h);
    if (window.innerWidth > 768) {
      state.sidebarOpen = true;
      dom.sidebar.classList.remove('open');
      dom.overlay.classList.remove('visible');
    }
  });

  // Theme toggle
  dom.btnTheme.addEventListener('click', () => {
    const on = document.body.classList.toggle('light-theme');
    dom.btnTheme.textContent = on ? '\u263D' : '\u2600';
    setSceneTheme(on);
    localStorage.setItem('magsim_theme', on ? 'light' : 'dark');
  });

  // Keyboard shortcuts
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && e.target === dom.newProductName) {
      dom.btnCreateProduct.click();
    }
  });

  // ─── Test panel ───
  async function loadScenarioButtons() {
    try {
      const res = await fetch('/api/scenarios');
      const scenarios = await res.json();
      dom.scenarioButtons.innerHTML = scenarios.map(s =>
        `<button class="btn btn-sm btn-outline scenario-btn" data-id="${s.id}"
          title="${s.expected}">${s.id}. ${s.name}</button>`
      ).join('');
      dom.scenarioButtons.querySelectorAll('.scenario-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
          const id = btn.dataset.id;
          dom.testResults.innerHTML = `<div>⏳ Выполняется сценарий ${id}…</div>`;
          try {
            const r = await fetch(`/api/run-scenario/${id}`);
            const data = await r.json();
            const icon = data.passed ? '✅' : '❌';
            const statusColor = data.passed ? 'var(--success)' : 'var(--danger)';
            dom.testResults.innerHTML = `
              <div style="background:var(--bg-card);border-radius:var(--radius-sm);padding:8px;margin-bottom:6px;">
                <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">
                  <span>${icon}</span>
                  <b>${data.id}. ${data.name}</b>
                  <span style="color:${statusColor};font-weight:bold;margin-left:auto;">${data.passed ? 'ПРОЙДЕН' : 'ПРОВАЛЕН'}</span>
                </div>
                <div style="font-size:11px;color:var(--text-secondary);margin-bottom:2px;">
                  <span style="color:var(--text-muted);">Ожидалось:</span> ${data.expected}
                </div>
                <div style="font-size:11px;">
                  <span style="color:var(--text-muted);">Результат:</span> ${data.detail}
                </div>
              </div>`;
          } catch (e) {
            dom.testResults.innerHTML = `<div style="color:red;">Ошибка: ${e.message}</div>`;
          }
        });
      });
    } catch (e) {
      dom.scenarioButtons.innerHTML = `<span style="color:red;">Ошибка загрузки: ${e.message}</span>`;
    }
  }

  dom.btnRunAllTests.addEventListener('click', async () => {
    dom.testResults.innerHTML = '<div>⏳ Запуск всех тестов…</div>';
    try {
      const res = await fetch('/api/run-tests');
      const data = await res.json();

      let html = '';
      const t = data.tests;
      html += `<div style="font-weight:bold;margin-bottom:6px;">📋 Unit-тесты: ${t.passed}/${t.total} пройдено${t.failed ? ', ' + t.failed + ' пало' : ''}</div>`;

      html += `<div style="font-weight:bold;margin:8px 0 4px;">📜 Сценарии (${data.scenarios.length}):</div>`;
      for (const s of data.scenarios) {
        const icon = s.passed ? '✅' : '❌';
        const statusColor = s.passed ? 'var(--success)' : 'var(--danger)';
        html += `
          <div style="background:var(--bg-card);border-radius:var(--radius-sm);padding:6px;margin-bottom:4px;">
            <div style="display:flex;align-items:center;gap:4px;margin-bottom:2px;">
              ${icon} <b>${s.id}. ${s.name}</b>
              <span style="color:${statusColor};margin-left:auto;font-size:10px;">${s.passed ? 'OK' : 'FAIL'}</span>
            </div>
            <div style="font-size:10px;color:var(--text-muted);">Ожидалось: ${s.expected}</div>
            <div style="font-size:10px;">Результат: ${s.detail}</div>
          </div>`;
      }
      dom.testResults.innerHTML = html;
    } catch (e) {
      dom.testResults.innerHTML = `<div style="color:red;">Ошибка: ${e.message}</div>`;
    }
  });

  loadScenarioButtons();
}

// ─── Analytics ───
const analyticsFilterEl = document.getElementById('analyticsProductFilter');
let _analyticsData = null;

async function fetchAnalytics() {
  try {
    const res = await fetch('/api/stats');
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    _analyticsData = data;
    // Populate filter dropdown
    const sel = analyticsFilterEl;
    if (sel) {
      const cur = sel.value;
      sel.innerHTML = '<option value="all">Все продукты</option>' +
        data.products.map(p => `<option value="${p.name}">${p.name}</option>`).join('');
      if (cur && sel.querySelector(`option[value="${cur}"]`)) sel.value = cur;
    }
    renderAnalytics(data);
  } catch (e) {
    dom.analyticsTbody.innerHTML = `<tr><td colspan="8" style="color:var(--danger);text-align:center;">Ошибка загрузки статистики: ${e.message}</td></tr>`;
  }
}

function renderAnalytics(data) {
  const products = data.products || [];
  const filter = analyticsFilterEl ? analyticsFilterEl.value : 'all';
  const filtered = filter === 'all' ? products : products.filter(p => p.name === filter);
  const chartLabels = filter === 'all' ? products.map(p => p.name) : [filter];

  const totalStock = products.reduce((s, p) => s + p.stock_total, 0);
  const totalDemand = products.reduce((s, p) => s + p.demand, 0);
  const totalDelivered = products.reduce((s, p) => s + p.delivered, 0);
  const totalRetrieved = products.reduce((s, p) => s + p.retrieved, 0);
  const totalQueue = products.reduce((s, p) => s + p.queue_length, 0);
  const totalOnShelves = products.reduce((s, p) => s + p.on_shelves, 0);

  dom.analyticsSummary.innerHTML = [
    { label: 'Всего поставок', value: totalStock, color: 'var(--accent)' },
    { label: 'Спрос', value: totalDemand, color: 'var(--warning)' },
    { label: 'Доставлено на склад', value: totalDelivered, color: 'var(--success)' },
    { label: 'Забрано со склада', value: totalRetrieved, color: 'var(--danger)' },
    { label: 'В очереди', value: totalQueue, color: '#8b5cf6' },
    { label: 'Занято полок', value: totalOnShelves, color: '#ec4899' },
  ].map(s => `<div class="stat-card" style="border-left-color:${s.color}">
    <div class="stat-value">${s.value}</div>
    <div class="stat-label">${s.label}</div>
  </div>`).join('');

  // Table
  dom.analyticsTbody.innerHTML = products.map(p => `<tr>
    <td><span class="color-dot" style="background:${p.color}"></span></td>
    <td>${p.name}</td>
    <td>${p.stock_total}</td>
    <td>${p.demand}</td>
    <td>${p.delivered}</td>
    <td>${p.retrieved}</td>
    <td>${p.queue_length}</td>
    <td>${p.on_shelves}</td>
  </tr>`).join('') + `<tr class="total-row">
    <td></td><td>Итого</td>
    <td>${totalStock}</td>
    <td>${totalDemand}</td>
    <td>${totalDelivered}</td>
    <td>${totalRetrieved}</td>
    <td>${totalQueue}</td>
    <td>${totalOnShelves}</td>
  </tr>`;

  // Chart
  const canvas = document.getElementById('analyticsChart');
  if (!canvas) return;
  if (analyticsChartInstance) analyticsChartInstance.destroy();

  const ctx = canvas.getContext('2d');
  analyticsChartInstance = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: chartLabels,
      datasets: [
        { label: 'Поставки', data: filtered.map(p => p.stock_total), backgroundColor: filtered.map(p => p.color + '80'), borderColor: filtered.map(p => p.color), borderWidth: 1 },
        { label: 'Спрос', data: filtered.map(p => p.demand), backgroundColor: filtered.map(p => p.color + '60'), borderColor: filtered.map(p => p.color), borderWidth: 1 },
        { label: 'Доставлено', data: filtered.map(p => p.delivered), backgroundColor: filtered.map(p => p.color + '40'), borderColor: filtered.map(p => p.color), borderWidth: 1 },
        { label: 'Забрано', data: filtered.map(p => p.retrieved), backgroundColor: filtered.map(p => p.color + '20'), borderColor: filtered.map(p => p.color), borderWidth: 1 },
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: '#9ca3af', font: { size: 11 } } },
      },
      scales: {
        x: { ticks: { color: '#9ca3af' }, grid: { color: '#1f2937' } },
        y: { ticks: { color: '#9ca3af', precision: 0 }, grid: { color: '#1f2937' }, beginAtZero: true },
      }
    }
  });
}

// Filter change handler
if (analyticsFilterEl) {
  analyticsFilterEl.addEventListener('change', () => {
    if (_analyticsData) renderAnalytics(_analyticsData);
  });
}

// ─── Init ───
setupHandlers();
setupGridHandlers();

// Apply saved theme
if (localStorage.getItem('magsim_theme') === 'light') {
  document.body.classList.add('light-theme');
  dom.btnTheme.textContent = '\u263D';
  setSceneTheme(true);
}
connectWS();
animate();
