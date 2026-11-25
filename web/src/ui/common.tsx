import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { ThinkingOrb, type OrbState } from 'thinking-orbs';
import { BrandMark } from './Pixels';

export function Brand({ small }: { small?: boolean }) {
  return <span className="brand"><BrandMark size={small ? 22 : 28} /><span className="brand-word">Memo</span></span>;
}

export function Orb({ state, size = 64, label }: { state: OrbState; size?: 64 | 32 | 20; label: string }) {
  return <ThinkingOrb state={state} size={size} theme="dark" aria-label={label} role="img" />;
}

export function Spinner({ text }: { text: string }) {
  return <div className="spinner-row" role="status"><Orb state="working" size={20} label={text} /><span>{text}</span></div>;
}

const modalStack: symbol[] = [];
const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]):not([type=hidden]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

export type ModalSize = 'sm' | 'md' | 'lg';

/**
 * Centered pop-up over the current view. Focus trap, Esc and backdrop close (blocked while busy),
 * focus returns on close, stacks (only the top one reacts), bottom sheet on phones.
 */
export function Modal({ title, onClose, children, wide, size, label, footer, busy }: {
  title: string; onClose: () => void; children: ReactNode; wide?: boolean; size?: ModalSize; label?: string; footer?: ReactNode; busy?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose); closeRef.current = onClose;
  const busyRef = useRef(!!busy); busyRef.current = !!busy;
  const titleId = useId();
  const sz: ModalSize = size ?? (wide ? 'lg' : 'md');
  useEffect(() => {
    const me = Symbol('modal');
    modalStack.push(me);
    const prev = document.activeElement as HTMLElement | null;
    const el = ref.current;
    const first = el?.querySelector<HTMLElement>('[data-autofocus],.modal-body input:not([type=hidden]),.modal-body select,.modal-body textarea');
    (first ?? el)?.focus({ preventScroll: true });
    const k = (e: KeyboardEvent) => {
      if (modalStack[modalStack.length - 1] !== me) return;
      if (e.key === 'Escape') { e.stopPropagation(); e.preventDefault(); if (!busyRef.current) closeRef.current(); return; }
      if (e.key === 'Tab' && el) {
        const items = Array.from(el.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((n) => n.offsetParent !== null || n === document.activeElement);
        if (items.length === 0) { e.preventDefault(); el.focus(); return; }
        const f = items[0], l = items[items.length - 1], a = document.activeElement;
        if (e.shiftKey && (a === f || a === el)) { e.preventDefault(); l.focus(); }
        else if (!e.shiftKey && a === l) { e.preventDefault(); f.focus(); }
        else if (!el.contains(a)) { e.preventDefault(); f.focus(); }
      }
    };
    window.addEventListener('keydown', k, true);
    return () => {
      window.removeEventListener('keydown', k, true);
      const i = modalStack.indexOf(me); if (i >= 0) modalStack.splice(i, 1);
      if (prev && document.contains(prev)) prev.focus?.({ preventScroll: true });
    };
  }, []);
  return createPortal(
    <div className="modal-layer" onMouseDown={(e) => { if (e.target === e.currentTarget && !busy) onClose(); }}>
      <div className={`modal modal--${sz}`} role="dialog" aria-modal="true" aria-label={label ?? title} aria-labelledby={label ? undefined : titleId} aria-busy={busy || undefined} tabIndex={-1} ref={ref}>
        <div className="modal-head"><h2 className="modal-title" id={titleId}>{title}</h2><button className="btn icon-btn" onClick={onClose} disabled={busy} aria-label="Close">X</button></div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

/** Small confirm pop-up, stacks over whatever is open. */
export function ConfirmModal({ title, children, confirmLabel, cancelLabel = 'Cancel', danger, busy, error, confirmDisabled, onConfirm, onCancel }: {
  title: string; children?: ReactNode; confirmLabel: string; cancelLabel?: string; danger?: boolean; busy?: boolean; error?: string | null; confirmDisabled?: boolean; onConfirm: () => void; onCancel: () => void;
}) {
  return (
    <Modal title={title} size="sm" onClose={onCancel} busy={busy} footer={
      <>
        <button className="btn" onClick={onCancel} disabled={busy} data-autofocus>{cancelLabel}</button>
        <button className={'btn ' + (danger ? 'btn-danger' : 'btn-primary')} onClick={onConfirm} disabled={busy || confirmDisabled}>{confirmLabel}</button>
      </>
    }>
      {children}
      {error && <p className="err" role="alert">{error}</p>}
    </Modal>
  );
}

export function Drawer({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, [onClose]);
  return (
    <aside className={'drawer hud-hit' + (wide ? ' drawer--wide' : '')} role="dialog" aria-label={title}>
      <div className="modal-head"><h2 className="modal-title">{title}</h2><button className="btn icon-btn" onClick={onClose} aria-label={`Close ${title}`}>X</button></div>
      {children}
    </aside>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return <div className="field"><label>{label}</label>{children}{hint && <span className="muted" style={{ fontSize: 13 }}>{hint}</span>}</div>;
}

/** Run an async action with busy + error state. */
export function useAction<A extends unknown[], R>(fn: (...a: A) => Promise<R>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = useCallback(async (...a: A): Promise<R | undefined> => {
    setBusy(true); setError(null);
    try { return await fn(...a); } catch (e) { setError(e instanceof Error ? e.message : 'Something went wrong.'); return undefined; } finally { setBusy(false); }
  }, [fn]);
  return { run, busy, error, setError };
}

/** Load data on mount / when deps change. */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    setLoading(true);
    fn().then((d) => { if (live) { setData(d); setError(null); } }).catch((e) => { if (live) setError(e instanceof Error ? e.message : 'Could not load.'); }).finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { data, error, loading, reload: () => setTick((t) => t + 1), setData };
}

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 / 1024).toFixed(0)} MB`;
  return `${(n / 1024 ** 3).toFixed(1)} GB`;
}

export const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
export const monthName = (m: number) => MONTHS[m - 1] ?? String(m);
export const LANGS: { id: 'en-IN' | 'hi-IN' | 'kn-IN'; label: string }[] = [
  { id: 'en-IN', label: 'English' }, { id: 'hi-IN', label: 'हिन्दी' }, { id: 'kn-IN', label: 'ಕನ್ನಡ' },
];
