// Small UI primitives shared by every screen: icons, buttons, step header, dialogs.
import React, { useEffect, useRef } from "react";
import { useLang } from "./lang";

// ----------------------------------------------------------------------- icons
type IconProps = { size?: number; className?: string };
const svg = (path: React.ReactNode) => (p: IconProps) => (
  <svg width={p.size || 20} height={p.size || 20} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" className={p.className} aria-hidden="true">{path}</svg>
);
export const Icon = {
  arrowUp: svg(<><path d="M12 19V5" /><path d="m5 12 7-7 7 7" /></>),
  arrowRight: svg(<><path d="M5 12h14" /><path d="m13 5 7 7-7 7" /></>),
  back: svg(<path d="m15 18-6-6 6-6" />),
  check: svg(<path d="m5 12.5 4.5 4.5L19 7.5" />),
  close: svg(<><path d="M18 6 6 18" /><path d="m6 6 12 12" /></>),
  image: svg(<><rect x="3" y="4" width="18" height="16" rx="3" /><circle cx="9" cy="10" r="2" /><path d="m21 16-5-5-9 9" /></>),
  upload: svg(<><path d="M12 16V4" /><path d="m7 9 5-5 5 5" /><path d="M5 20h14" /></>),
  ruler: svg(<><path d="M3 17 17 3l4 4L7 21z" /><path d="m7 13 2 2M10 10l2 2M13 7l2 2" /></>),
  palette: svg(<><path d="M12 3a9 9 0 1 0 0 18c1 0 1.5-.8 1.5-1.6 0-1.3-1-1.7-1-2.9 0-1 .8-1.5 1.8-1.5H17a4 4 0 0 0 4-4c0-4.4-4-8-9-8z" /><circle cx="7.5" cy="11" r="1" /><circle cx="10.5" cy="7.5" r="1" /><circle cx="15" cy="7.5" r="1" /></>),
  receipt: svg(<><path d="M6 3h12v18l-3-2-3 2-3-2-3 2z" /><path d="M9 8h6M9 12h6M9 16h3" /></>),
  sparkle: svg(<><path d="M12 3v4M12 17v4M3 12h4M17 12h4" /><path d="m6 6 2 2M16 16l2 2M6 18l2-2M16 8l2-2" /></>),
  plus: svg(<><path d="M12 5v14" /><path d="M5 12h14" /></>),
  minus: svg(<path d="M5 12h14" />),
  info: svg(<><circle cx="12" cy="12" r="9" /><path d="M12 11v5" /><path d="M12 8h.01" /></>),
  compare: svg(<><rect x="3" y="4" width="18" height="16" rx="3" /><path d="M12 4v16" /></>),
  calendar: svg(<><rect x="3" y="5" width="18" height="16" rx="3" /><path d="M3 10h18M8 3v4M16 3v4" /></>),
  grid: svg(<><rect x="3" y="3" width="8" height="8" rx="2" /><rect x="13" y="3" width="8" height="8" rx="2" /><rect x="3" y="13" width="8" height="8" rx="2" /><rect x="13" y="13" width="8" height="8" rx="2" /></>),
  globe: svg(<><circle cx="12" cy="12" r="9" /><path d="M3 12h18" /><path d="M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" /></>),
  share: svg(<><circle cx="18" cy="5" r="2.5" /><circle cx="6" cy="12" r="2.5" /><circle cx="18" cy="19" r="2.5" /><path d="m8.2 10.8 7.6-4.4M8.2 13.2l7.6 4.4" /></>),
  printer: svg(<><path d="M7 9V3h10v6" /><rect x="3" y="9" width="18" height="8" rx="2" /><path d="M7 14h10v7H7z" /></>),
  chat: svg(<><path d="M20 12a8 8 0 0 1-11.7 7.1L4 20l1-4A8 8 0 1 1 20 12z" /><path d="M9 10.5c.3 1.8 2.2 3.8 4.2 4.2l1.1-1.1 1.7.7" /></>),
  phone: svg(<path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z" />),
  pin: svg(<><path d="M12 21s-7-6.2-7-11.5a7 7 0 0 1 14 0C19 14.8 12 21 12 21z" /><circle cx="12" cy="9.5" r="2.5" /></>),
  copy: svg(<><rect x="8" y="8" width="13" height="13" rx="2.5" /><path d="M16 8V5.5A2.5 2.5 0 0 0 13.5 3h-8A2.5 2.5 0 0 0 3 5.5v8A2.5 2.5 0 0 0 5.5 16H8" /></>),
  refresh: svg(<><path d="M20 12a8 8 0 1 1-2.3-5.7" /><path d="M20 4v5h-5" /></>),
};

export function BrandMark(props: { size?: number }) {
  const s = props.size || 26;
  return (
    <svg width={s} height={s} viewBox="0 0 32 32" aria-hidden="true">
      <defs>
        <linearGradient id="bm" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#FF9A5A" /><stop offset="0.55" stopColor="#E0602F" /><stop offset="1" stopColor="#B8432A" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill="url(#bm)" />
      <path d="M7 19.5h18v4.5H7z" fill="#fff" opacity=".95" />
      <path d="M9 8.5h14v8H9z" fill="#fff" opacity=".55" />
    </svg>
  );
}

// ------------------------------------------------------------------- building blocks
export const go = (hash: string) => { window.location.hash = hash; };

export function ErrorLine(props: { error: string | null }) {
  const { t } = useLang();
  return props.error ? <p className="alert alert-bad" role="alert">{t.error}: {props.error}</p> : null;
}

export function StepHeader(props: { step: 1 | 2 | 3 | 4; title: string; sub?: string; onBack?: () => void }) {
  const { t } = useLang();
  return (
    <header className="step-header">
      <div className="step-top">
        {props.onBack ? (
          <button className="link-back" onClick={props.onBack}><Icon.back size={18} />{t.back}</button>
        ) : <span />}
        <span className="step-count">{t.step(props.step)} · {t.stepNames[props.step - 1]}</span>
      </div>
      <div className="step-bar" aria-hidden="true">
        {[1, 2, 3, 4].map((n) => <span key={n} className={n <= props.step ? "on" : ""} />)}
      </div>
      <h1 className="h1">{props.title}</h1>
      {props.sub && <p className="lead">{props.sub}</p>}
    </header>
  );
}

export function Skeleton(props: { height?: number; radius?: number }) {
  return <div className="skeleton" style={{ height: props.height || 320, borderRadius: props.radius }} />;
}

export function Modal(props: { label: string; onClose: () => void; children: React.ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") props.onClose(); };
    window.addEventListener("keydown", onKey);
    ref.current?.querySelector<HTMLElement>("h2, [tabindex='-1']")?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return (
    <div className="modal" role="dialog" aria-modal="true" aria-label={props.label}
      onMouseDown={(e) => { if (e.target === e.currentTarget) props.onClose(); }}>
      <div ref={ref} className={`modal-card${props.wide ? " modal-wide" : ""}`}>{props.children}</div>
    </div>
  );
}

export function Sheet(props: { label: string; onClose: () => void; children: React.ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") props.onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return (
    <aside className="sheet" role="dialog" aria-label={props.label}>
      <button className="icon-btn sheet-close" onClick={props.onClose} aria-label="close"><Icon.close /></button>
      {props.children}
    </aside>
  );
}

export function Stepper(props: { value: number; min: number; max: number; onChange: (v: number) => void; label: string }) {
  return (
    <div className="stepper" role="group" aria-label={props.label}>
      <button type="button" className="icon-btn" onClick={() => props.onChange(Math.max(props.min, props.value - 1))}
        disabled={props.value <= props.min} aria-label="-"><Icon.minus size={16} /></button>
      <output aria-live="polite">{props.value}</output>
      <button type="button" className="icon-btn" onClick={() => props.onChange(Math.min(props.max, props.value + 1))}
        disabled={props.value >= props.max} aria-label="+"><Icon.plus size={16} /></button>
    </div>
  );
}
