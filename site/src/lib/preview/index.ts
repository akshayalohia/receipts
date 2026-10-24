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
  MeshPhysicalMaterial,
  NeutralToneMapping,
  PCFSoftShadowMap,
  PerspectiveCamera,
  PlaneGeometry,
  PMREMGenerator,
  RepeatWrapping,
  Scene,
  ShadowMaterial,
  SRGBColorSpace,
  TextureLoader,
  Vector2,
  Vector3,
  WebGLRenderer,
  type Material,
  type Object3D,
  type Texture,
} from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import type { Font } from 'three/examples/jsm/loaders/FontLoader.js';
import { buildFrame, partSpecs, type Assets, type Frame, type Mats, type Norm } from './layout';
import { loadHeightMap } from './relief';
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
// Default camera direction per product: near face-on (the slab leans back 15 deg) with a little 3/4 turn.
const VIEW_DIRS: Record<PreviewProduct, Vector3> = {
  tweet: new Vector3(0.2, 0.3, 1).normalize(),
  milestone: new Vector3(0.24, 0.3, 1).normalize(),
  team: new Vector3(0.5, 0.34, 1).normalize(),
  fullcolour: new Vector3(0.28, 0.32, 1).normalize(),
};
const FIT_PAD = 1.1;
// Raking key from the upper left (~60 deg off the face normal) so 0.8-1 mm relief throws readable shadows.
const KEY_OFFSET = new Vector3(-230, 250, 105);
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
    replies: str(p.replies),
    reposts: str(p.reposts),
    verified: p.verified === true,
    date: str(p.date),
    number: str(p.number),
    label: str(p.label),
    name: str(p.name),
    team: str(p.team),
    subline: str(p.subline),
    image_url: str(p.image_url),
    avatar_url: str(p.avatar_url),
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

/** Faint top-surface print texture (diagonal extrusion lines) as a normal map, 0.4 mm pitch. */
function printLinesNormalMap(): CanvasTexture {
  const n = 64;
  const c = document.createElement('canvas');
  c.width = c.height = n;
  const g = c.getContext('2d');
  if (g) {
    const img = g.createImageData(n, n);
    for (let y = 0; y < n; y++) {
      for (let x = 0; x < n; x++) {
        // 4 periods across the tile along the diagonal; normal tilts across the bead.
        const t = ((x + y) / n) * 4 * Math.PI * 2;
        const d = Math.sin(t) * 0.5;
        const i = (y * n + x) * 4;
        img.data[i] = 128 + d * 90;
        img.data[i + 1] = 128 + d * 90;
        img.data[i + 2] = 255;
        img.data[i + 3] = 255;
      }
    }
    g.putImageData(img, 0, 0);
  }
  const t = new CanvasTexture(c);
  t.wrapS = t.wrapT = RepeatWrapping;
  // ExtrudeGeometry cap UVs are in mm, so 1/1.6 repeats gives a 0.4 mm bead pitch.
  t.repeat.set(1 / 1.6, 1 / 1.6);
  return t;
}

export function mountPreview(el: HTMLElement, params: PreviewParams): PreviewHandle {
  const renderer = new WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance', preserveDrawingBuffer: false });
  // Crisp on retina without melting phones: cap at 2x (1.5x on small screens).
  const maxRatio = Math.min(window.innerWidth, window.innerHeight) < 500 ? 1.5 : 2;
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, maxRatio));
  renderer.setClearColor(0x000000, 0);
  renderer.outputColorSpace = SRGBColorSpace;
  renderer.toneMapping = NeutralToneMapping;
  renderer.toneMappingExposure = 1.0;
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
  const envTex = pmrem.fromScene(room, 0.035).texture;
  room.dispose();
  pmrem.dispose();
  scene.environment = envTex;
  scene.environmentIntensity = 0.5;

  // Studio lighting: soft hemisphere fill, a warm raking key from the upper left (makes the relief read and
  // casts the soft shadow), a low cool fill from the right and a rim from behind to separate the silhouette.
  scene.add(new HemisphereLight(0xffffff, 0xd9d0c3, 0.4));
  const key = new DirectionalLight(0xfff2e2, 2.7);
  key.position.copy(KEY_OFFSET);
  key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048);
  key.shadow.bias = -0.00025;
  key.shadow.normalBias = 0.25;
  const sc = key.shadow.camera;
  sc.near = 10;
  sc.far = 900;
  scene.add(key);
  scene.add(key.target);
  const fill = new DirectionalLight(0xe9f0ff, 0.35);
  fill.position.set(220, 60, 160);
  scene.add(fill);
  const rim = new DirectionalLight(0xeef3ff, 1.1);
  rim.position.set(160, 180, -260);
  scene.add(rim);

  const groundGeo = new PlaneGeometry(1200, 1200);
  groundGeo.rotateX(-Math.PI / 2);
  const groundMat = new ShadowMaterial({ opacity: 0.13 });
  const ground = new Mesh(groundGeo, groundMat);
  ground.receiveShadow = true;
  scene.add(ground);
  const blobTex = contactShadowTexture();
  const blobGeo = new PlaneGeometry(1, 1);
  blobGeo.rotateX(-Math.PI / 2);
  const blobMat = new MeshBasicMaterial({ map: blobTex, transparent: true, depthWrite: false, opacity: 0.55 });
  const blob = new Mesh(blobGeo, blobMat);
  blob.position.y = 0.05;
  blob.renderOrder = -1;
  scene.add(blob);

  const camera = new PerspectiveCamera(24, 1, 1, 5000); // longish lens: product-shot perspective
  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.rotateSpeed = 0.45;
  controls.enableZoom = false; // never hijack page scroll
  controls.enablePan = false;
  controls.minPolarAngle = Math.PI * 0.18;
  controls.maxPolarAngle = Math.PI * 0.5;
  canvas.style.touchAction = 'pan-y'; // vertical swipes still scroll the page; horizontal drags rotate

  // PETG: a satin plastic with a soft sheen, no metal (gold is silk PETG: a little metallic sparkle).
  const linesTex = printLinesNormalMap();
  const petg = (): MeshPhysicalMaterial =>
    new MeshPhysicalMaterial({
      roughness: 0.46,
      metalness: 0,
      clearcoat: 0.15,
      clearcoatRoughness: 0.5,
      specularIntensity: 0.6,
      normalMap: linesTex,
      normalScale: new Vector2(0.06, 0.06),
    });
  const mats: Mats & { body: MeshPhysicalMaterial; text: MeshPhysicalMaterial; front: MeshPhysicalMaterial } = {
    body: petg(),
    text: petg(),
    front: new MeshPhysicalMaterial({ roughness: 0.45, metalness: 0, color: 0xe8e5df }),
  };
  const assets: Assets = { avatar: null, avatarKey: '' };
  let avatarUrl = '';
  let avatarToken = 0;
  let avatarLoad: Promise<void> = Promise.resolve();

  const spin = new Group(); // idle sway is applied here, not to the camera
  scene.add(spin);

  let current: PreviewParams = params;
  let frame: Frame | null = null;
  let frameProduct: PreviewProduct | null = null;
  const parts = new Map<string, { key: string; obj: Object3D | null; clones: Object3D[] }>();
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
    const gold = key === 'gold';
    mats.body.metalness = gold ? 0.45 : 0;
    mats.body.roughness = gold ? 0.38 : key === 'black' ? 0.5 : 0.46;
    mats.body.clearcoat = gold ? 0.35 : key === 'black' ? 0.08 : 0.15;
    // Single-colour print: the relief is the same filament. Shift its shade a touch so it reads on screen
    // the way raking light makes it read in the hand.
    const hsl = { h: 0, s: 0, l: 0 };
    c.getHSL(hsl);
    const t = c.clone();
    if (hsl.l < 0.2) t.offsetHSL(0, 0, 0.12);
    else if (hsl.l > 0.8) t.offsetHSL(0, 0, -0.15);
    else t.offsetHSL(0, -0.05, 0.08);
    mats.text.color.copy(t);
    mats.text.metalness = mats.body.metalness;
    mats.text.roughness = mats.body.roughness - 0.06;
    mats.text.clearcoat = mats.body.clearcoat;
    kick();
  }

  /** Tight framing: the camera distance that fits every corner of the object's box, plus padding. */
  function fit(): void {
    if (!frame || width === 0 || height === 0) return;
    const saved = spin.rotation.y;
    spin.rotation.y = 0;
    spin.updateMatrixWorld(true);
    const box = new Box3().setFromObject(frame.root);
    spin.rotation.y = saved;
    const center = box.getCenter(new Vector3());
    const dir = camera.position.clone().sub(controls.target);
    if (dir.lengthSq() < 1e-6) dir.copy(VIEW_DIRS[frameProduct ?? 'tweet']);
    dir.normalize();
    const up = new Vector3(0, 1, 0);
    const right = new Vector3().crossVectors(up, dir).normalize();
    const camUp = new Vector3().crossVectors(dir, right).normalize();
    const tanV = Math.tan((camera.fov * Math.PI) / 360);
    const tanH = tanV * camera.aspect;
    let dist = 0;
    const v = new Vector3();
    for (let i = 0; i < 8; i++) {
      v.set(i & 1 ? box.max.x : box.min.x, i & 2 ? box.max.y : box.min.y, i & 4 ? box.max.z : box.min.z).sub(center);
      const z = v.dot(dir);
      dist = Math.max(dist, z + Math.abs(v.dot(right)) / tanH, z + Math.abs(v.dot(camUp)) / tanV);
    }
    dist *= FIT_PAD;
    const radius = box.getSize(new Vector3()).length() / 2;
    controls.target.copy(center);
    camera.position.copy(center).addScaledVector(dir, dist);
    camera.near = Math.max(1, dist - radius * 3);
    camera.far = dist + radius * 6;
    camera.updateProjectionMatrix();
    // Shadow frustum hugs the object so the 2k map stays sharp.
    key.target.position.copy(center);
    key.position.copy(center).add(KEY_OFFSET);
    sc.left = -radius * 1.6;
    sc.right = radius * 1.6;
    sc.top = radius * 1.6;
    sc.bottom = -radius * 1.6;
    sc.updateProjectionMatrix();
    const sx = (box.max.x - box.min.x) * 1.3;
    const sz = (box.max.z - box.min.z) * 1.8;
    blob.scale.set(sx, 1, sz);
    blob.position.x = center.x;
    blob.position.z = center.z;
    controls.update();
  }

  function loadAvatar(url: string): void {
    const token = ++avatarToken;
    assets.avatar = null;
    assets.avatarKey = '';
    if (!url) {
      avatarLoad = Promise.resolve();
      return;
    }
    avatarLoad = loadHeightMap(url)
      .then((hm) => {
        if (token !== avatarToken || destroyed) return;
        assets.avatar = hm;
        assets.avatarKey = url;
        rebuild();
      })
      .catch((e: unknown) => {
        if (token === avatarToken) console.warn('[preview] avatar failed to load; using the initial', e);
      });
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
      for (const part of parts.values()) part.clones.forEach((c) => c.removeFromParent());
      parts.clear();
      frame = buildFrame(p.product, mats);
      frameProduct = p.product;
      spin.add(frame.root);
      imageUrl = null;
      // New product: start from its designed camera angle.
      camera.position.copy(controls.target).add(VIEW_DIRS[p.product]);
      fit();
    }
    if (!frame) return;

    if (p.product === 'tweet' && p.avatar_url !== avatarUrl) {
      avatarUrl = p.avatar_url;
      loadAvatar(avatarUrl);
    }

    if (font) {
      const seen = new Set<string>();
      for (const spec of partSpecs(p)) {
        seen.add(spec.id);
        const key = spec.key + '|' + assets.avatarKey;
        const old = parts.get(spec.id);
        if (old && old.key === key) continue;
        if (old) {
          old.clones.forEach((c) => c.removeFromParent());
          if (old.obj) disposeTree(old.obj);
        }
        const obj = spec.build(font, mats.text, assets);
        const anchor = frame.anchors[spec.anchor];
        const clones: Object3D[] = [];
        if (obj && anchor) {
          anchor.add(obj);
          if (spec.anchor === 'front') for (const copy of frame.copies ?? []) clones.push(copy.add(obj.clone()).children.at(-1)!);
        }
        parts.set(spec.id, { key, obj, clones });
      }
      for (const [id, part] of parts) {
        if (!seen.has(id)) {
          part.clones.forEach((c) => c.removeFromParent());
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
      await Promise.all([imageLoad, avatarLoad]);
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
      camera.position.copy(controls.target).add(VIEW_DIRS[frameProduct ?? 'tweet']);
      width = SNAP_W;
      height = SNAP_H;
      fit();
      // Pull back a little so the object sits centred with breathing room.
      camera.position.sub(controls.target).multiplyScalar(1.08).add(controls.target);
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
      avatarToken++;
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
      linesTex.dispose();
      envTex.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
      canvas.remove();
    },
  };
}
