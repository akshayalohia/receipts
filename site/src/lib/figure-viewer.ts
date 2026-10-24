// High-quality viewer for custom AI figures: PBR PETG material, studio environment, soft contact
// shadow, live colour and a live plinth preview that matches what printify adds at print time.
import {
  ACESFilmicToneMapping, Box3, BoxGeometry, Color, CylinderGeometry, DirectionalLight, Group, HemisphereLight, Mesh,
  MeshPhysicalMaterial, PCFSoftShadowMap, PerspectiveCamera, PlaneGeometry, PMREMGenerator, Scene, ShadowMaterial,
  SRGBColorSpace, Vector3, WebGLRenderer,
} from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';

export type Base = 'round' | 'square' | 'none';
export interface FigureViewer {
  load(url: string): Promise<void>;
  setColour(hex: string): void;
  setBase(b: Base): void;
  destroy(): void;
}

export function mountFigureViewer(el: HTMLElement): FigureViewer {
  const renderer = new WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = SRGBColorSpace;
  renderer.toneMapping = ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = PCFSoftShadowMap;
  el.appendChild(renderer.domElement);

  const scene = new Scene();
  const pmrem = new PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.add(new HemisphereLight(0xffffff, 0xd8d2c4, 0.35));
  const key = new DirectionalLight(0xffffff, 2.2);
  key.position.set(2.5, 4, 3);
  key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048);
  key.shadow.radius = 6;
  key.shadow.bias = -0.0004;
  const sc = key.shadow.camera;
  sc.left = sc.bottom = -2; sc.right = sc.top = 2; sc.near = 0.1; sc.far = 20;
  scene.add(key);

  const floor = new Mesh(new PlaneGeometry(20, 20), new ShadowMaterial({ opacity: 0.18 }));
  floor.rotation.x = -Math.PI / 2;
  floor.receiveShadow = true;
  scene.add(floor);

  const camera = new PerspectiveCamera(32, 1, 0.01, 100);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.enablePan = false;
  controls.autoRotate = true;
  controls.autoRotateSpeed = 1.6;
  controls.minPolarAngle = 0.2;
  controls.maxPolarAngle = Math.PI / 2 - 0.05;
  controls.addEventListener('start', () => (controls.autoRotate = false));

  const material = new MeshPhysicalMaterial({ color: '#9a9a9a', roughness: 0.42, metalness: 0, clearcoat: 0.25, clearcoatRoughness: 0.5, sheen: 0.2 });
  const plinthMat = material; // same filament: it's one print
  const root = new Group();
  scene.add(root);
  let figure: Group | null = null;
  let plinth: Mesh | null = null;
  let base: Base = 'round';
  let foot = 0.75; // figure footprint (after normalising height to 1)

  function resize() {
    const w = el.clientWidth || 400, h = el.clientHeight || 400;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  const ro = new ResizeObserver(resize);
  ro.observe(el);
  resize();

  function rebuildPlinth() {
    if (plinth) { root.remove(plinth); plinth.geometry.dispose(); plinth = null; }
    if (!figure) return;
    const bh = 0.06;
    if (base !== 'none') {
      const r = foot / 2 + 0.04;
      const g = base === 'round' ? new CylinderGeometry(r, r * 1.02, bh, 96) : new BoxGeometry(foot + 0.08, bh, foot + 0.08);
      plinth = new Mesh(g, plinthMat);
      plinth.position.y = bh / 2;
      plinth.castShadow = plinth.receiveShadow = true;
      root.add(plinth);
    }
    figure.position.y = base === 'none' ? 0 : bh - 0.005;
    frame();
  }

  function frame() {
    const box = new Box3().setFromObject(root);
    const size = box.getSize(new Vector3());
    const center = box.getCenter(new Vector3());
    const radius = Math.max(size.x, size.y, size.z) * 0.62;
    const dist = radius / Math.sin((camera.fov * Math.PI) / 360) * 1.05;
    camera.position.set(center.x + dist * 0.45, center.y + dist * 0.28, center.z + dist * 0.85);
    controls.target.copy(center);
    controls.update();
  }

  let raf = 0;
  const tick = () => { controls.update(); renderer.render(scene, camera); raf = requestAnimationFrame(tick); };
  tick();

  return {
    async load(url: string) {
      const gltf = await new GLTFLoader().loadAsync(url);
      if (figure) root.remove(figure);
      const g = new Group();
      gltf.scene.traverse((o: any) => {
        if (o.isMesh) {
          o.material = material;
          o.castShadow = true;
          o.receiveShadow = true;
          if (!o.geometry.attributes.normal) o.geometry.computeVertexNormals();
        }
      });
      g.add(gltf.scene);
      // normalise: height 1, centred on x/z, standing on y=0
      const box = new Box3().setFromObject(g);
      const s = 1 / Math.max(box.max.y - box.min.y, 1e-6);
      gltf.scene.scale.setScalar(s);
      const b2 = new Box3().setFromObject(g);
      const c = b2.getCenter(new Vector3());
      gltf.scene.position.set(-c.x, -b2.min.y, -c.z);
      const b3 = new Box3().setFromObject(g);
      foot = Math.max(b3.max.x - b3.min.x, b3.max.z - b3.min.z) * 0.75;
      figure = g;
      root.add(g);
      rebuildPlinth();
      el.dataset.ready = '1';
    },
    setColour(hex: string) { material.color = new Color(hex); },
    setBase(b: Base) { base = b; rebuildPlinth(); },
    destroy() { cancelAnimationFrame(raf); ro.disconnect(); controls.dispose(); renderer.dispose(); el.removeChild(renderer.domElement); },
  };
}
