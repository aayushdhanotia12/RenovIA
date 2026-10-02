import React, { useEffect, useMemo, useRef, useState } from "react";
import { followJob, type Design, type JobEvent, type Point, type Quote, type SurfaceItem } from "./api";
import { money, moneyRange } from "./format";
import { useLang } from "./lang";
import { Icon } from "./ui";

// ---------------------------------------------------------------- working view
// The progress screen: the customer's own photo, a scan line while we work, and
// the real pipeline stages ticking off as the server reports them.
export function WorkingView(props: { jobId: string; stages: string[]; kind: string; photoUrl?: string;
  onDone: (result: any) => void; onFail: (msg: string) => void }) {
  const { t } = useLang();
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [elapsed, setElapsed] = useState(0);
  const [fact, setFact] = useState(0);
  useEffect(() => {
    setEvents([]);
    const started = Date.now();
    const tick = window.setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 1000);
    const facts = window.setInterval(() => setFact((f) => (f + 1) % t.facts.length), 6000);
    const stop = followJob(props.jobId, (e) => {
      setEvents((prev) => [...prev, e]);
      if (e.stage === "JOB") {
        if (e.status === "done") props.onDone(e.result);
        else props.onFail(e.detail || "failed");
      }
    });
    return () => { stop(); window.clearInterval(tick); window.clearInterval(facts); };
  }, [props.jobId]);
  const doneCount = props.stages.filter((s) => events.some((e) => e.stage === s && e.status === "done")).length;
  return (
    <div className="working">
      <div className="working-media">
        {props.photoUrl ? <img src={props.photoUrl} alt="" /> : <div className="working-blank" />}
        <div className="scanline" aria-hidden="true" />
        <div className="working-badge"><span className="dot-live" />{t.working[props.kind] || t.working.design}</div>
      </div>
      <div className="working-side" role="status" aria-live="polite">
        <div className="progress-track" aria-hidden="true">
          <span style={{ width: `${Math.max(8, (100 * doneCount) / props.stages.length)}%` }} />
        </div>
        <ol className="stages">
          {props.stages.map((stage) => {
            const mine = events.filter((e) => e.stage === stage);
            const last = mine[mine.length - 1];
            const state = !last ? "todo" : last.status === "done" ? "done" : last.status === "failed" ? "failed" : "running";
            return (
              <li key={stage} className={`stage stage-${state}`}>
                <span className="stage-dot" aria-hidden="true">{state === "done" ? <Icon.check size={14} /> : null}</span>
                <div>
                  <div className="stage-title">{t.stages[stage] || stage}</div>
                  {last?.detail && state !== "todo" && <div className="stage-detail">{last.detail}</div>}
                </div>
              </li>
            );
          })}
        </ol>
        <p className="fact" key={fact}><Icon.sparkle size={16} />{t.facts[fact]}</p>
        {elapsed > 45 && <p className="muted small">{t.slow}</p>}
      </div>
    </div>
  );
}

// ------------------------------------------------------------- corner editor
const CLASS_COLOUR: Record<string, string> = { countertop: "#F08A5D", backsplash: "#7AB6F5" };

export function QuadEditor(props: { imageUrl: string; width: number; height: number; items: SurfaceItem[];
  onChange: (items: SurfaceItem[]) => void; labels: (it: SurfaceItem) => string }) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [drag, setDrag] = useState<{ item: number; corner: number } | null>(null);
  const [shown, setShown] = useState(0);
  const pad = Math.round(props.width * 0.12);
  // Handles and labels keep a constant on-screen size, so corners stay grabbable on a phone.
  const px = shown ? (props.width + 2 * pad) / shown : (props.width + 2 * pad) / 800;
  const handleR = 9 * px;
  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setShown(el.getBoundingClientRect().width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const toImage = (clientX: number, clientY: number): Point => {
    const svg = svgRef.current!;
    const pt = svg.createSVGPoint();
    pt.x = clientX; pt.y = clientY;
    const p = pt.matrixTransform(svg.getScreenCTM()!.inverse());
    return [Math.round(p.x), Math.round(p.y)];
  };
  const move = (e: React.PointerEvent) => {
    if (!drag) return;
    const [x, y] = toImage(e.clientX, e.clientY);
    props.onChange(props.items.map((it, i) => i !== drag.item ? it : {
      ...it, quad: it.quad.map((q, c) => (c === drag.corner ? [x, y] : q)) as Point[],
      // the detected mask still decides which pixels are repainted; a hand-placed
      // surface without a mask uses its corners as the outline
      polygon: it.mask_file ? it.polygon : null,
    }));
  };
  return (
    <div className="quad-editor">
      <svg ref={svgRef} viewBox={`${-pad} ${-pad} ${props.width + 2 * pad} ${props.height + 2 * pad}`}
        onPointerMove={move} onPointerUp={() => setDrag(null)} onPointerLeave={() => setDrag(null)}>
        <defs>
          <pattern id="qe-grid" width="40" height="40" patternUnits="userSpaceOnUse">
            <path d="M40 0H0V40" fill="none" stroke="rgba(28,28,28,.06)" strokeWidth="2" />
          </pattern>
        </defs>
        <rect x={-pad} y={-pad} width={props.width + 2 * pad} height={props.height + 2 * pad} fill="url(#qe-grid)" />
        <image href={props.imageUrl} x={0} y={0} width={props.width} height={props.height} />
        {props.items.map((it, i) => (
          <g key={it.surface_id}>
            {it.polygon && it.polygon.length > 2 && (
              <polygon points={it.polygon.map((p) => p.join(",")).join(" ")} fill={CLASS_COLOUR[it.surface_class]}
                fillOpacity={0.22} stroke="none" />
            )}
            <polygon points={it.quad.map((p) => p.join(",")).join(" ")} fill="none" stroke="white"
              strokeWidth={5} vectorEffect="non-scaling-stroke" strokeOpacity={0.85} />
            <polygon points={it.quad.map((p) => p.join(",")).join(" ")} fill="none" stroke={CLASS_COLOUR[it.surface_class]}
              strokeWidth={2.5} vectorEffect="non-scaling-stroke" strokeDasharray="10 6" />
            <text x={(it.quad[0][0] + it.quad[1][0]) / 2} y={(it.quad[0][1] + it.quad[1][1]) / 2 - handleR * 1.6}
              className="quad-label" textAnchor="middle" fontSize={13 * px}>{props.labels(it)}</text>
            {it.quad.map((p, c) => (
              <g key={c} className={`quad-corner${drag && drag.item === i && drag.corner === c ? " dragging" : ""}`}
                onPointerDown={(e) => { (e.target as Element).setPointerCapture?.(e.pointerId); setDrag({ item: i, corner: c }); }}>
                <circle cx={p[0]} cy={p[1]} r={handleR * 2.4} className="quad-hit" />
                <circle cx={p[0]} cy={p[1]} r={handleR} className="quad-handle"
                  fill={CLASS_COLOUR[it.surface_class]} stroke="white" strokeWidth={3} vectorEffect="non-scaling-stroke"
                  role="slider" aria-label={`${props.labels(it)} corner ${c + 1}`} tabIndex={0}
                  onKeyDown={(e) => {
                    const step = e.shiftKey ? 20 : 4;
                    const d: Record<string, Point> = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
                    if (!d[e.key]) return;
                    e.preventDefault();
                    props.onChange(props.items.map((x, xi) => xi !== i ? x : {
                      ...x, quad: x.quad.map((q, qc) => (qc === c ? [q[0] + d[e.key][0], q[1] + d[e.key][1]] : q)) as Point[] }));
                  }} />
              </g>
            ))}
          </g>
        ))}
      </svg>
    </div>
  );
}

// -------------------------------------------------------- before/after + hotspots
export type CanvasLayer = { id: string; label: string; sub: string; polygon: Point[]; centroid: Point; area: number };

// One image with clickable surfaces and a draggable before/after divider. Used for the
// landing demo and for the design review; the overlay shares the image's pixel space,
// so polygons from the render manifest are used as they are.
export function CompareCanvas(props: { before: string; after: string; width: number; height: number;
  layers: CanvasLayer[]; selected: string | null; onSelect: (id: string) => void; alt: string;
  compare: boolean; startAt?: number }) {
  const { t } = useLang();
  const [pos, setPos] = useState(props.startAt ?? 50);
  const [hover, setHover] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [pulse, setPulse] = useState(true);
  const [shown, setShown] = useState(0); // displayed width in CSS pixels
  const boxRef = useRef<HTMLDivElement>(null);
  const hitOrder = useMemo(() => [...props.layers].sort((a, b) => b.area - a.area), [props.layers]);
  const active = props.layers.find((l) => l.id === (hover || props.selected));
  const outlined = props.layers.filter((l) => l.id === hover || l.id === props.selected);
  // Pins keep a constant on-screen size: 13px radius drawn, 22px radius to tap (UI-SPEC 9.2).
  const px = shown ? props.width / shown : props.width / 900;
  const pinR = 13 * px;
  useEffect(() => { const id = window.setTimeout(() => setPulse(false), 7500); return () => window.clearTimeout(id); }, []);
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setShown(el.getBoundingClientRect().width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const setFromPointer = (clientX: number) => {
    const r = boxRef.current!.getBoundingClientRect();
    setPos(Math.min(100, Math.max(0, ((clientX - r.left) / r.width) * 100)));
  };
  const clip = props.compare ? `inset(0 0 0 ${pos}%)` : "none";
  const points = (l: CanvasLayer) => l.polygon.map((p) => p.join(",")).join(" ");
  const chipBelow = active ? active.centroid[1] / props.height < 0.22 : false;
  return (
    <div className="canvas" ref={boxRef} style={{ aspectRatio: `${props.width} / ${props.height}` }}
      onPointerMove={(e) => { if (dragging) setFromPointer(e.clientX); }}
      onPointerUp={() => setDragging(false)} onPointerLeave={() => setDragging(false)}>
      <img src={props.before} alt="" className="canvas-img" draggable={false} />
      <img src={props.after} alt={props.alt} className="canvas-img canvas-after" style={{ clipPath: clip }} draggable={false} />
      <svg viewBox={`0 0 ${props.width} ${props.height}`} className="canvas-overlay"
        style={{ pointerEvents: props.compare ? "none" : "auto" }} aria-hidden={props.compare}>
        {hitOrder.map((layer) => {
          const on = layer.id === props.selected || layer.id === hover;
          return (
            <polygon key={layer.id} points={points(layer)}
              className={`hotspot${on ? " hotspot-on" : ""}${layer.id === props.selected ? " hotspot-selected" : ""}`}
              tabIndex={props.compare ? -1 : 0} role="button"
              aria-label={`${layer.label}: ${layer.sub}`}
              onClick={() => props.onSelect(layer.id)}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); props.onSelect(layer.id); } }}
              onPointerEnter={() => setHover(layer.id)} onPointerLeave={() => setHover(null)}
              onFocus={() => setHover(layer.id)} onBlur={() => setHover(null)} />
          );
        })}
        {!props.compare && outlined.map((layer) => (
          <g key={`outline-${layer.id}`} className="hotspot-outline" aria-hidden="true">
            <polygon points={points(layer)} className="outline-shadow" />
            <polygon points={points(layer)} className="outline-line" />
          </g>
        ))}
        {!props.compare && props.layers.map((layer, i) => (
          <g key={`pin-${layer.id}`} className={`pin${pulse ? " pin-pulse" : ""}${layer.id === props.selected ? " pin-on" : ""}`}
            onClick={() => props.onSelect(layer.id)}
            onPointerEnter={() => setHover(layer.id)} onPointerLeave={() => setHover(null)}>
            <circle cx={layer.centroid[0]} cy={layer.centroid[1]} r={pinR * 1.7} className="pin-hit" />
            <circle cx={layer.centroid[0]} cy={layer.centroid[1]} r={pinR * 1.9} className="pin-halo" />
            <circle cx={layer.centroid[0]} cy={layer.centroid[1]} r={pinR} className="pin-dot" />
            <text x={layer.centroid[0]} y={layer.centroid[1] + pinR * 0.38} textAnchor="middle" fontSize={pinR * 1.08}>{i + 1}</text>
          </g>
        ))}
      </svg>
      {!props.compare && active && (
        <div className={`hot-chip${chipBelow ? " hot-chip-below" : ""}`} key={active.id}
          style={{ left: `${Math.min(88, Math.max(12, (100 * active.centroid[0]) / props.width))}%`,
            top: `${(100 * active.centroid[1]) / props.height}%` }}>
          <strong>{active.label}</strong><span>{active.sub}</span>
        </div>
      )}
      {props.compare && (
        <>
          <span className="tag tag-left">{t.before}</span><span className="tag tag-right">{t.after}</span>
          <div className="divider" style={{ left: `${pos}%` }}
            onPointerDown={(e) => { (e.target as Element).setPointerCapture?.(e.pointerId); setDragging(true); }}>
            <span className="divider-knob"><Icon.compare size={18} /></span>
          </div>
          <input className="sr-only" type="range" min={0} max={100} value={Math.round(pos)} aria-label={t.demoDrag}
            onChange={(e) => setPos(Number(e.target.value))} />
        </>
      )}
    </div>
  );
}

export function designLayers(design: Design, t: { countertop: string; backsplash: string }): CanvasLayer[] {
  return design.manifest.layers.map((l) => ({
    id: l.surface_id, label: `${l.surface_class === "countertop" ? t.countertop : t.backsplash} ${l.run_id}`,
    sub: l.finish_name, polygon: l.polygon, centroid: l.centroid, area: l.area_mm2,
  }));
}

// ---------------------------------------------------------------- quote pieces
export function QuoteLines(props: { quote: Quote; group?: "materials" | "labour"; surface?: string; unitPrices?: boolean }) {
  const { lang } = useLang();
  const lines = props.quote.lines.filter((l) => (!props.group || l.group === props.group)
    && (!props.surface || l.surface === props.surface));
  return (
    <table className="lines">
      <tbody>
        {lines.map((l, i) => (
          <tr key={i}>
            <td>
              <div>{l.qty > 1 ? `${l.qty} × ` : ""}{l.description}</div>
              <div className="line-detail">{l.detail}</div>
            </td>
            {props.unitPrices && <td className="num muted">{l.qty > 1 ? money(l.unit_price, lang, true) : ""}</td>}
            <td className="num">{money(l.total, lang, true)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function QuoteTotals(props: { quote: Quote; full?: boolean }) {
  const { t, lang } = useLang();
  const q = props.quote;
  return (
    <table className="lines totals">
      <tbody>
        {props.full && <tr><td>{t.materials}</td><td className="num">{money(q.materials, lang, true)}</td></tr>}
        {props.full && <tr><td>{t.labour}</td><td className="num">{money(q.labour, lang, true)}</td></tr>}
        {props.full && <tr><td>{t.subtotal}</td><td className="num">{money(q.subtotal, lang, true)}</td></tr>}
        <tr><td>{t.tax} {q.tax_rate_bp / 100}%</td><td className="num">{money(q.tax, lang, true)}</td></tr>
        {props.full && <tr className="total-row"><td>{q.estimate_only ? t.totalAsMeasured : t.total}</td>
          <td className="num">{money(q.total, lang, true)}</td></tr>}
        <tr><td>{t.bookingToday}</td><td className="num">{money(q.booking_fee, lang, true)}</td></tr>
        <tr><td>{t.balanceLater}</td><td className="num">{q.estimate_only
          ? moneyRange(q.balance.low, q.balance.high, lang, t.approx) : money(q.balance.low, lang, true)}</td></tr>
      </tbody>
    </table>
  );
}
