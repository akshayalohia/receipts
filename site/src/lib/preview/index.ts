// In-browser 3D preview of each product. Geometry follows docs/CONTRACT.md "Print geometry" (units: mm).
import {
  Box3,
  CanvasTexture,
  Color,
  DirectionalLight,
  Group,
  HemisphereLight,
  Mesh,
  MeshBasicMaterial,
  MeshStandardMaterial,
  NeutralToneMapping,
  PCFSoftShadowMap,
  PerspectiveCamera,
  PlaneGeometry,
  PMREMGenerator,
  Scene,
  ShadowMaterial,
  Sphere,
  SRGBColorSpace,
  TextureLoader,
  Vector3,
  WebGLRenderer,
  type Material,
  type Object3D,
  type Texture,
} from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import type { Font } from 'three/examples/jsm/loaders/FontLoader.js';
import { buildFrame, partSpecs, type Frame, type Mats, type Norm } from './layout';
import { loadFont } from './text';
import type { PreviewHandle, PreviewParams, PreviewProduct } from './types';

export type { PreviewParams, PreviewHandle, PreviewProduct, PreviewColour } from './types';

const PALETTE = {
  black: '#1d1d1f',
  white: '#f2f1ed',
  red: '#c3302c',
  blue: '#2554c7',
  green: '#2d8550',
  gold: '#c9a24b',
} as const;
const SNAP_W = 1200;
const SNAP_H = 630;
const SNAP_BG = '#F2EEE6';
const PRODUCTS: readonly PreviewProduct[] = ['tweet', 'milestone', 'fullcolour', 'team'];
const VIEW_DIR = new Vector3(0.28, 0.32, 1).normalize();
const SWAY_AMP = 0.14; // radians
const IDLE_MS = 2500;
const REBUILD_DEBOUNCE_MS = 40;

function str(v: unknown): string {
  return v === undefined || v === null ? '' : String(v).trim();
}

function normalize(p: PreviewParams): Norm {
  return {
    product: PRODUCTS.includes(p.product) ? p.product : 'tweet',
    author_name: str(p.author_name),
    handle: str(p.handle),
    text: p.text === undefined || p.text === null ? '' : String(p.text),
    likes: str(p.likes),
    date: str(p.date),
    number: str(p.number),
    label: str(p.label),
    name: str(p.name),
    team: str(p.team),
    subline: str(p.subline),
    image_url: str(p.image_url),
    founding: str(p.founding),
  };
}

function disposeTree(o: Object3D): void {
  o.traverse((c) => {
    if ((c as Mesh).isMesh) (c as Mesh).geometry.dispose();
  });
  o.removeFromParent();
}

function contactShadowTexture(): CanvasTexture {
  const c = document.createElement('canvas');
  c.width = c.height = 128;
  const g = c.getContext('2d');
  if (g) {
    const grad = g.createRadialGradient(64, 64, 0, 64, 64, 64);
    grad.addColorStop(0, 'rgba(40,32,24,0.55)');
    grad.addColorStop(0.55, 'rgba(40,32,24,0.18)');
    grad.addColorStop(1, 'rgba(40,32,24,0)');
    g.fillStyle = grad;
    g.fillRect(0, 0, 128, 128);
  }
  return new CanvasTexture(c);
}

export function mountPreview(el: HTMLElement, params: PreviewParams): PreviewHandle {
  const renderer = new WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setClearColor(0x000000, 0);
  renderer.outputColorSpace = SRGBColorSpace;
  renderer.toneMapping = NeutralToneMapping;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = PCFSoftShadowMap;
  const canvas = renderer.domElement;
  canvas.style.display = 'block';
  canvas.style.width = '100%';
  canvas.style.height = '100%';
  canvas.style.cursor = 'grab';
  canvas.setAttribute('role', 'img');
  canvas.setAttribute('aria-label', '3D preview of your print. Drag to rotate.');
  el.appendChild(canvas);

  const scene = new Scene();
  const pmrem = new PMREMGenerator(renderer);
  const room = new RoomEnvironment();
  const envTex = pmrem.fromScene(room, 0.04).texture;
  room.dispose();
  pmrem.dispose();
  scene.environment = envTex;
  scene.environmentIntensity = 0.45;

  // Soft studio lighting: hemisphere fill + warm key (casts the soft shadow) + cool rim from behind.
  scene.add(new HemisphereLight(0xffffff, 0xd9d0c3, 0.9));
  const key = new DirectionalLight(0xfff4e6, 2.1);
  key.position.set(-140, 280, 220);
  key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024);
  key.shadow.radius = 6;
  key.shadow.bias = -0.0004;
  key.shadow.normalBias = 0.3;
  const sc = key.shadow.camera;
  sc.left = -140;
  sc.right = 140;
  sc.top = 140;
  sc.bottom = -140;
  sc.near = 10;
  sc.far = 800;
  scene.add(key);
  const rim = new DirectionalLight(0xe8f0ff, 1.3);
  rim.position.set(160, 160, -260);
  scene.add(rim);

  const groundGeo = new PlaneGeometry(600, 600);
  groundGeo.rotateX(-Math.PI / 2);
  const groundMat = new ShadowMaterial({ opacity: 0.16 });
  const ground = new Mesh(groundGeo, groundMat);
  ground.receiveShadow = true;
  scene.add(ground);
  const blobTex = contactShadowTexture();
  const blobGeo = new PlaneGeometry(1, 1);
  blobGeo.rotateX(-Math.PI / 2);
  const blobMat = new MeshBasicMaterial({ map: blobTex, transparent: true, depthWrite: false, opacity: 0.6 });
  const blob = new Mesh(blobGeo, blobMat);
  blob.position.y = 0.05;
  scene.add(blob);

  const camera = new PerspectiveCamera(30, 1, 1, 5000);
  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.rotateSpeed = 0.45;
  controls.enableZoom = false; // never hijack page scroll
  controls.enablePan = false;
  controls.minPolarAngle = Math.PI * 0.18;
  controls.maxPolarAngle = Math.PI * 0.5;
  canvas.style.touchAction = 'pan-y'; // vertical swipes still scroll the page; horizontal drags rotate

  const mats: Mats & { body: MeshStandardMaterial; text: MeshStandardMaterial; front: MeshStandardMaterial } = {
    body: new MeshStandardMaterial({ roughness: 0.6, metalness: 0 }),
    text: new MeshStandardMaterial({ roughness: 0.6, metalness: 0 }),
    front: new MeshStandardMaterial({ roughness: 0.45, metalness: 0, color: 0xe8e5df }),
  };

  const spin = new Group(); // idle sway is applied here, not to the camera
  scene.add(spin);

  let current: PreviewParams = params;
  let frame: Frame | null = null;
  let frameProduct: PreviewProduct | null = null;
  const parts = new Map<string, { key: string; obj: Object3D | null }>();
  let font: Font | null = null;
  let imageUrl: string | null = null;
  let imageToken = 0;
  let imageLoad: Promise<void> = Promise.resolve();
  let imageTex: Texture | null = null;
  let rebuildTimer: ReturnType<typeof setTimeout> | null = null;
  let destroyed = false;
  let visible = true;
  let width = 0;
  let height = 0;
  let raf = 0;
  let lastInteraction = -Infinity;
  let interacting = false;
  let swayAmp = 0;
  const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;

  const fontReady = loadFont()
    .then((f) => {
      font = f;
      if (!destroyed) rebuild();
    })
    .catch((e: unknown) => console.error('[preview] font failed to load', e));

  function applyColour(colour: string): void {
    const key = colour.trim().toLowerCase();
    const hex: string | undefined = (PALETTE as Record<string, string>)[key];
    const c = new Color();
    if (hex) c.set(hex);
    else {
      try {
        c.setStyle(colour);
      } catch {
        c.set(PALETTE.white);
      }
    }
    mats.body.color.copy(c);
    mats.body.metalness = key === 'gold' ? 0.6 : 0;
    mats.body.roughness = key === 'gold' ? 0.45 : 0.6;
    mats.text.color.set(key === 'white' ? PALETTE.black : key === 'black' ? PALETTE.white : '#f7f6f2');
    kick();
  }

  function fit(): void {
    if (!frame || width === 0 || height === 0) return;
    const saved = spin.rotation.y;
    spin.rotation.y = 0;
    const sphere = new Box3().setFromObject(frame.root).getBoundingSphere(new Sphere());
    spin.rotation.y = saved;
    const vfov = (camera.fov * Math.PI) / 180;
    const hfov = 2 * Math.atan(Math.tan(vfov / 2) * camera.aspect);
    const dist = (sphere.radius / Math.sin(Math.min(vfov, hfov) / 2)) * 1.02;
    const dir = camera.position.clone().sub(controls.target);
    if (dir.lengthSq() < 1e-6) dir.copy(VIEW_DIR);
    dir.normalize();
    controls.target.copy(sphere.center);
    camera.position.copy(sphere.center).addScaledVector(dir, dist);
    camera.near = Math.max(1, dist - sphere.radius * 3);
    camera.far = dist + sphere.radius * 6;
    camera.updateProjectionMatrix();
    const box = new Box3().setFromObject(frame.root);
    const sx = (box.max.x - box.min.x) * 1.35;
    const sz = (box.max.z - box.min.z) * 1.9;
    blob.scale.set(sx, 1, sz);
    blob.position.x = (box.min.x + box.max.x) / 2;
    blob.position.z = (box.min.z + box.max.z) / 2;
    controls.update();
  }

  function loadImage(url: string): void {
    const token = ++imageToken;
    const clear = (): void => {
      if (imageTex) imageTex.dispose();
      imageTex = null;
      mats.front.map = null;
      mats.front.color.set(0xe8e5df);
      mats.front.needsUpdate = true;
    };
    clear();
    if (!url) {
      imageLoad = Promise.resolve();
      kick();
      return;
    }
    const loader = new TextureLoader();
    loader.setCrossOrigin('anonymous');
    imageLoad = loader
      .loadAsync(url)
      .then((tex) => {
        if (token !== imageToken || destroyed) {
          tex.dispose();
          return;
        }
        tex.colorSpace = SRGBColorSpace;
        tex.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy());
        const img = tex.image as { width?: number; height?: number } | undefined;
        const aspect = img?.width && img?.height ? img.width / img.height : 1.5;
        const panel = 150 / 100;
        // Cover-fit; tall screenshots keep their top edge.
        // TODO(geometry): confirm crop rule (cover, top-anchored) matches the backend OBJ/PNG export.
        if (aspect > panel) {
          tex.repeat.set(panel / aspect, 1);
          tex.offset.set((1 - panel / aspect) / 2, 0);
        } else {
          tex.repeat.set(1, aspect / panel);
          tex.offset.set(0, 1 - aspect / panel);
        }
        imageTex = tex;
        mats.front.map = tex;
        mats.front.color.set(0xffffff);
        mats.front.needsUpdate = true;
        kick();
      })
      .catch((e: unknown) => {
        if (token === imageToken) console.warn('[preview] image failed to load', url, e);
      });
  }

  function rebuild(): void {
    if (rebuildTimer !== null) {
      clearTimeout(rebuildTimer);
      rebuildTimer = null;
    }
    if (destroyed) return;
    const p = normalize(current);
    applyColour(current.colour ?? 'white');

    if (p.product !== frameProduct) {
      if (frame) disposeTree(frame.root);
      parts.clear();
      frame = buildFrame(p.product, mats);
      frameProduct = p.product;
      spin.add(frame.root);
      imageUrl = null;
      fit();
    }
    if (!frame) return;

    if (font) {
      const seen = new Set<string>();
      for (const spec of partSpecs(p)) {
        seen.add(spec.id);
        const old = parts.get(spec.id);
        if (old && old.key === spec.key) continue;
        if (old?.obj) disposeTree(old.obj);
        const obj = spec.build(font, mats.text);
        const anchor = frame.anchors[spec.anchor];
        if (obj && anchor) anchor.add(obj);
        parts.set(spec.id, { key: spec.key, obj });
      }
      for (const [id, part] of parts) {
        if (!seen.has(id)) {
          if (part.obj) disposeTree(part.obj);
          parts.delete(id);
        }
      }
    }

    if (frame.imagePlane) {
      if (p.image_url !== imageUrl) {
        imageUrl = p.image_url;
        loadImage(p.image_url);
      }
    } else if (imageUrl !== null) {
      imageUrl = null;
      loadImage('');
    }
    kick();
  }

  function running(): boolean {
    return !destroyed && visible && !document.hidden && width > 0 && height > 0;
  }

  function tick(t: number): void {
    raf = 0;
    if (!running()) return;
    const idle = !interacting && t - lastInteraction > IDLE_MS;
    const target = idle && !reduceMotion ? SWAY_AMP : 0;
    swayAmp += (target - swayAmp) * 0.02;
    spin.rotation.y = swayAmp * Math.sin(t * 0.00045);
    controls.update();
    renderer.render(scene, camera);
    raf = requestAnimationFrame(tick);
  }

  function kick(): void {
    if (!raf && running()) raf = requestAnimationFrame(tick);
  }

  controls.addEventListener('start', () => {
    interacting = true;
    canvas.style.cursor = 'grabbing';
    kick();
  });
  controls.addEventListener('end', () => {
    interacting = false;
    lastInteraction = performance.now();
    canvas.style.cursor = 'grab';
  });

  function resize(w: number, h: number): void {
    width = Math.max(0, Math.floor(w));
    height = Math.max(0, Math.floor(h));
    if (width === 0 || height === 0) return;
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    fit();
    kick();
  }

  const ro = new ResizeObserver((entries) => {
    const r = entries[entries.length - 1]?.contentRect;
    if (r) resize(r.width, r.height);
  });
  ro.observe(el);
  const io = new IntersectionObserver((entries) => {
    const e = entries[entries.length - 1];
    if (!e) return;
    visible = e.isIntersecting;
    kick();
  });
  io.observe(el);
  const onVisibility = (): void => kick();
  document.addEventListener('visibilitychange', onVisibility);

  resize(el.clientWidth, el.clientHeight);
  rebuild();

  return {
    update(p: PreviewParams): void {
      if (destroyed) return;
      current = p;
      applyColour(p.colour ?? 'white'); // instant; geometry rebuild is debounced
      if (rebuildTimer !== null) clearTimeout(rebuildTimer);
      rebuildTimer = setTimeout(rebuild, REBUILD_DEBOUNCE_MS);
    },

    async snapshot(): Promise<Blob> {
      if (destroyed) throw new Error('preview destroyed');
      await fontReady;
      rebuild();
      await imageLoad;
      if (destroyed || !frame) throw new Error('preview destroyed');

      // Render a 1200x630 frame from the default front view, then restore, all in one task.
      const prev = {
        ratio: renderer.getPixelRatio(),
        aspect: camera.aspect,
        pos: camera.position.clone(),
        target: controls.target.clone(),
        sway: spin.rotation.y,
      };
      const prevW = width;
      const prevH = height;
      spin.rotation.y = 0;
      renderer.setPixelRatio(1);
      renderer.setSize(SNAP_W, SNAP_H, false);
      camera.aspect = SNAP_W / SNAP_H;
      camera.position.copy(controls.target).add(VIEW_DIR);
      width = SNAP_W;
      height = SNAP_H;
      fit();
      // Pull back a little so the object sits centred with breathing room.
      camera.position.sub(controls.target).multiplyScalar(1.12).add(controls.target);
      scene.background = new Color(SNAP_BG);
      renderer.render(scene, camera);
      const blobPromise = new Promise<Blob>((resolve, reject) =>
        canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('snapshot failed'))), 'image/png'),
      );
      scene.background = null;
      spin.rotation.y = prev.sway;
      renderer.setPixelRatio(prev.ratio);
      width = prevW;
      height = prevH;
      if (prevW > 0 && prevH > 0) renderer.setSize(prevW, prevH, false);
      camera.aspect = prev.aspect;
      camera.updateProjectionMatrix();
      camera.position.copy(prev.pos);
      controls.target.copy(prev.target);
      controls.update();
      if (running()) renderer.render(scene, camera);
      return blobPromise;
    },

    destroy(): void {
      if (destroyed) return;
      destroyed = true;
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
      if (rebuildTimer !== null) clearTimeout(rebuildTimer);
      imageToken++;
      ro.disconnect();
      io.disconnect();
      document.removeEventListener('visibilitychange', onVisibility);
      controls.dispose();
      if (frame) disposeTree(frame.root);
      parts.clear();
      imageTex?.dispose();
      const materials: Material[] = [mats.body, mats.text, mats.front, groundMat, blobMat];
      for (const m of materials) m.dispose();
      groundGeo.dispose();
      blobGeo.dispose();
      blobTex.dispose();
      envTex.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
      canvas.remove();
    },
  };
}
