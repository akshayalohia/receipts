// Loads SITE-3D's preview module if it exists. import.meta.glob keeps the build green before it lands.
export interface PreviewParams {
  product: 'tweet' | 'milestone' | 'fullcolour' | 'team';
  colour: string;
  author_name?: string;
  handle?: string;
  text?: string;
  likes?: string;
  date?: string;
  number?: string;
  label?: string;
  name?: string;
  team?: string;
  subline?: string;
  image_url?: string;
  founding?: string;
}
export interface PreviewHandle {
  update(p: PreviewParams): void;
  snapshot(): Promise<Blob>;
  destroy(): void;
}
type PreviewModule = { mountPreview: (el: HTMLElement, p: PreviewParams) => PreviewHandle };

const modules = import.meta.glob<PreviewModule>('../lib/preview/index.ts');

export async function loadPreview(): Promise<PreviewModule | null> {
  const loader = Object.values(modules)[0];
  if (!loader) return null; // TODO(preview): SITE-3D module not present at build time
  try {
    return await loader();
  } catch (e) {
    console.warn('preview failed to load', e);
    return null;
  }
}

export async function mountPreviewSafe(el: HTMLElement, p: PreviewParams): Promise<PreviewHandle | null> {
  const mod = await loadPreview();
  if (!mod) return null;
  try {
    const h = mod.mountPreview(el, p);
    el.dataset.ready = '1';
    return h;
  } catch (e) {
    console.warn('preview mount failed', e);
    return null;
  }
}

export function debounce<A extends unknown[]>(fn: (...a: A) => void, ms: number) {
  let t: ReturnType<typeof setTimeout> | undefined;
  return (...a: A) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...a), ms);
  };
}
