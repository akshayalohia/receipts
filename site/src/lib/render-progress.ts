// Render progress bar: real stages from the API status, smooth time-based fill inside each stage.
// Stages: concept (POST /api/render: sketch image + queue the mesh), mesh (GET state queued/building),
// preview (GET done: server-side preview mesh + loading it in the viewer).
// Inside a stage the bar follows t / (t + k): ~60% of the stage at its expected warm time, then it keeps
// creeping toward the end without reaching it, so a cold start (60-80 s) never looks frozen or finished.
// Styles: .rprog in src/styles/global.css.

export type Stage = 'concept' | 'mesh' | 'preview';

const STAGES: Record<Stage, { label: string; from: number; to: number; warmMs: number }> = {
  concept: { label: 'Sketching your idea', from: 2, to: 25, warmMs: 3000 },
  mesh: { label: 'Sculpting in 3D', from: 25, to: 85, warmMs: 6000 },
  preview: { label: 'Preparing preview', from: 85, to: 100, warmMs: 2500 },
};
const ORDER: Stage[] = ['concept', 'mesh', 'preview'];
const COLD_AFTER_MS = 20000;
const NOTE_WARM = 'Keep this tab open. Most models are ready in about 15 seconds.';
const NOTE_COLD = 'The first render of the hour takes up to a minute while the sculptor warms up. Keep this tab open.';
const HANDOFF_KEY = 'render-progress';

export interface RenderProgress {
  /** Move to a stage (never backwards in fill). `label` overrides the stage text, `warmMs` its expected time. */
  set(stage: Stage, opts?: { label?: string; warmMs?: number }): void;
  /** Fill to 100% and hide shortly after. */
  done(): void;
  /** Stop and hide (the caller shows its own error). */
  fail(): void;
  /** Start over from 0 with a fresh clock (e.g. an edit after the first model finished). */
  reset(): void;
  /** Drop the leave-page warning (call before navigating away on purpose). */
  release(): void;
  /** Remember where the bar is so the next page (/r?id=) can continue it instead of restarting. */
  handoff(id: string): void;
}

export function readHandoff(id: string): { t0: number; pct: number } | null {
  try {
    const h = JSON.parse(sessionStorage.getItem(HANDOFF_KEY) || 'null');
    sessionStorage.removeItem(HANDOFF_KEY);
    if (h && h.id === id && Date.now() - h.t0 < 10 * 60 * 1000) return { t0: h.t0, pct: h.pct };
  } catch { /* storage blocked: start fresh */ }
  return null;
}

export function mountRenderProgress(host: HTMLElement, init: { t0?: number; pct?: number } = {}): RenderProgress {
  host.classList.add('rprog');
  host.hidden = true;
  host.innerHTML = `
    <div class="rprog-head"><span class="rprog-label" aria-live="polite"></span><span class="rprog-time" aria-hidden="true"></span></div>
    <div class="rprog-track" role="progressbar" aria-label="Render progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><div class="rprog-fill"></div></div>
    <ol class="rprog-steps">${ORDER.map((s, i) => `<li data-step="${s}"><span>${i + 1}</span> ${STAGES[s].label}</li>`).join('')}</ol>
    <p class="rprog-note"></p>`;
  const q = <T extends HTMLElement>(sel: string) => host.querySelector(sel) as T;
  const labelEl = q('.rprog-label'), timeEl = q('.rprog-time'), track = q('.rprog-track'), fill = q('.rprog-fill'), note = q('.rprog-note');
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;

  let t0 = init.t0 ?? Date.now();
  let pct = init.pct ?? 0;
  let stage: Stage | null = null;
  let stageT0 = 0;
  let warmMs = 0;
  let label = '';
  let timer: ReturnType<typeof setInterval> | undefined;
  let guarded = false;

  const onBeforeUnload = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ''; return ''; };
  const guard = (on: boolean) => {
    if (on === guarded) return;
    guarded = on;
    if (on) addEventListener('beforeunload', onBeforeUnload);
    else removeEventListener('beforeunload', onBeforeUnload);
  };
  const setText = (el: HTMLElement, text: string) => { if (el.textContent !== text) el.textContent = text; };

  function paint() {
    if (!stage) return;
    const S = STAGES[stage];
    const t = Date.now() - stageT0;
    const f = t / (t + warmMs / 1.5); // 60% of the stage at warmMs, asymptotic after
    pct = Math.max(pct, S.from + (S.to - S.from) * f * 0.97);
    fill.style.width = `${pct.toFixed(1)}%`;
    track.setAttribute('aria-valuenow', String(Math.round(pct)));
    const total = Date.now() - t0;
    setText(timeEl, `${Math.floor(total / 1000)} s`);
    const cold = total > COLD_AFTER_MS && stage !== 'preview';
    setText(labelEl, cold && stage === 'mesh' && !label ? 'Still sculpting in 3D' : label || S.label);
    setText(note, cold ? NOTE_COLD : NOTE_WARM);
    note.classList.toggle('is-cold', cold);
    track.setAttribute('aria-valuetext', `${labelEl.textContent}, ${Math.round(pct)}%`);
  }

  function stop() { if (timer) clearInterval(timer); timer = undefined; }
  function reset() { stop(); guard(false); stage = null; pct = 0; t0 = Date.now(); fill.style.width = '0%'; }

  return {
    set(next, opts = {}) {
      if (next !== stage) { stage = next; stageT0 = Date.now(); }
      warmMs = opts.warmMs ?? STAGES[next].warmMs;
      label = opts.label ?? '';
      host.hidden = false;
      host.classList.remove('is-done');
      const idx = ORDER.indexOf(next);
      for (const li of host.querySelectorAll<HTMLElement>('[data-step]')) {
        const i = ORDER.indexOf(li.dataset.step as Stage);
        li.classList.toggle('is-done', i < idx);
        li.classList.toggle('is-active', i === idx);
        if (i === idx) li.setAttribute('aria-current', 'step'); else li.removeAttribute('aria-current');
      }
      guard(next !== 'preview'); // only while the render itself is in flight
      paint();
      if (!timer) timer = setInterval(paint, reduce ? 1000 : 200);
    },
    done() {
      stop(); guard(false);
      pct = 100; fill.style.width = '100%'; track.setAttribute('aria-valuenow', '100');
      host.classList.add('is-done');
      stage = null;
      setTimeout(() => { if (host.classList.contains('is-done')) host.hidden = true; }, reduce ? 0 : 700);
    },
    fail() { reset(); host.hidden = true; },
    reset,
    release() { guard(false); },
    handoff(id) {
      try { sessionStorage.setItem(HANDOFF_KEY, JSON.stringify({ id, t0, pct })); } catch { /* fine */ }
    },
  };
}
