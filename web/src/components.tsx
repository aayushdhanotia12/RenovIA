import React, { useEffect, useMemo, useRef, useState } from "react";
import { followJob, type Design, type Finish, type JobEvent, type Point, type Pointer, type Profile, type Quote,
  type SurfaceItem } from "./api";
import { money, moneyCompact } from "./format";
import type { Lang, Strings } from "./i18n";
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
// A labelled pointer on the image. `target` is the layer it outlines; `value` is its price, already
// formatted from the quote (the canvas never works a figure out).
export type CanvasPin = { id: string; item: string; target: string | null; at: Point; label: string; value?: string };

// --- tag placement: every pin gets a tag next to its dot that covers no other tag or dot.
const TAG_H = 30, TAG_H_COMPACT = 26, TAG_GAP = 6, EDGE = 6;
let measureCtx: CanvasRenderingContext2D | null | undefined;
function textWidth(text: string, weight: number, size: number): number {
  if (measureCtx === undefined) measureCtx = document.createElement("canvas").getContext("2d");
  if (!measureCtx) return text.length * size * 0.62;
  measureCtx.font = `${weight} ${size}px Poppins, ui-sans-serif, system-ui, sans-serif`;
  return measureCtx.measureText(text).width;
}
type Rect = { x: number; y: number; w: number; h: number };
const overlaps = (a: Rect, b: Rect, pad: number) =>
  a.x < b.x + b.w + pad && b.x < a.x + a.w + pad && a.y < b.y + b.h + pad && b.y < a.y + a.h + pad;
type PlacedTag = Rect & { pin: CanvasPin; dot: Point; text: { label?: string; value?: string } };

function placeTags(pins: CanvasPin[], scale: number, W: number, H: number, compact: boolean): PlacedTag[] {
  const h = compact ? TAG_H_COMPACT : TAG_H;
  const size = compact ? 11.5 : 12.5;
  const dots: Rect[] = pins.map((p) => ({ x: p.at[0] * scale - 9, y: p.at[1] * scale - 9, w: 18, h: 18 }));
  const placed: PlacedTag[] = [];
  pins.forEach((pin) => {
    // On a phone a priced tag shows only its price; the dot already sits on the surface it names.
    const text = compact && pin.value ? { value: pin.value } : { label: pin.label, value: pin.value };
    const w = Math.ceil((text.label ? textWidth(text.label, 400, size) : 0) + (text.value ? textWidth(text.value, 600, size) : 0)
      + (text.label && text.value ? 7 : 0) + (compact ? 18 : 24));
    const x = pin.at[0] * scale, y = pin.at[1] * scale;
    let best: Rect | null = null;
    search: for (const k of [0, -1, 1, -2, 2, -3, 3, -4, 4]) {
      for (const side of [1, -1]) {
        const r = { x: side > 0 ? x + 13 : x - 13 - w, y: y - h / 2 + k * (h + TAG_GAP), w, h };
        if (r.x < EDGE || r.y < EDGE || r.x + r.w > W - EDGE || r.y + r.h > H - EDGE) continue;
        if (placed.some((o) => overlaps(o, r, 4)) || dots.some((d) => overlaps(d, r, 2))) continue;
        best = r;
        break search;
      }
    }
    if (!best) best = { x: Math.min(Math.max(EDGE, x + 13), W - EDGE - w), y: Math.min(Math.max(EDGE, y - h / 2), H - EDGE - h), w, h };
    placed.push({ ...best, pin, dot: [x, y], text });
  });
  return placed;
}

// One image with clickable surfaces and a draggable before/after divider. Used for the
// landing demo, the design review and the shared view; the overlay shares the image's pixel
// space, so polygons from the render manifest are used as they are. With `pins` each priced
// item gets a labelled tag; without them each surface gets a numbered pin and a chip on hover.
export function CompareCanvas(props: { before: string; after: string; width: number; height: number;
  layers: CanvasLayer[]; selected: string | null; onSelect: (id: string) => void; alt: string;
  compare: boolean; startAt?: number; pins?: CanvasPin[]; busy?: string | null }) {
  const { t } = useLang();
  const [pos, setPos] = useState(props.startAt ?? 50);
  const [hover, setHover] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [pulse, setPulse] = useState(true);
  const [shown, setShown] = useState(0); // displayed width in CSS pixels
  const boxRef = useRef<HTMLDivElement>(null);
  const hitOrder = useMemo(() => [...props.layers].sort((a, b) => b.area - a.area), [props.layers]);
  const pins = props.pins;
  const selTarget = pins ? (pins.find((p) => p.id === props.selected)?.target ?? null) : props.selected;
  const pinFor = (layerId: string) => pins?.find((p) => p.target === layerId)?.id ?? layerId;
  const active = pins ? undefined : props.layers.find((l) => l.id === (hover || props.selected));
  const outlined = props.layers.filter((l) => l.id === hover || l.id === selTarget);
  // Pins keep a constant on-screen size: 13px radius drawn, 22px radius to tap (UI-SPEC 9.2).
  const px = shown ? props.width / shown : props.width / 900;
  const pinR = 13 * px;
  const scale = shown ? shown / props.width : 0;
  const compact = shown > 0 && shown < 560;
  const tags = useMemo(() => (pins && scale ? placeTags(pins, scale, shown, props.height * scale, compact) : []),
    [pins, scale, shown, props.height, compact]);
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
    <div className={`canvas${props.busy ? " canvas-busy" : ""}`} ref={boxRef} style={{ aspectRatio: `${props.width} / ${props.height}` }}
      onPointerMove={(e) => { if (dragging) setFromPointer(e.clientX); }}
      onPointerUp={() => setDragging(false)} onPointerLeave={() => setDragging(false)}>
      <img src={props.before} alt="" className="canvas-img" draggable={false} />
      <img src={props.after} alt={props.alt} className="canvas-img canvas-after" style={{ clipPath: clip }} draggable={false} />
      <svg viewBox={`0 0 ${props.width} ${props.height}`} className="canvas-overlay"
        style={{ pointerEvents: props.compare ? "none" : "auto" }} aria-hidden={props.compare || !!pins}>
        {hitOrder.map((layer) => {
          const on = layer.id === selTarget || layer.id === hover;
          return (
            <polygon key={layer.id} points={points(layer)}
              className={`hotspot${on ? " hotspot-on" : ""}${layer.id === selTarget ? " hotspot-selected" : ""}`}
              tabIndex={props.compare || pins ? -1 : 0} role="button"
              aria-label={`${layer.label}: ${layer.sub}`}
              onClick={() => props.onSelect(pinFor(layer.id))}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); props.onSelect(pinFor(layer.id)); } }}
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
        {!props.compare && !pins && props.layers.map((layer, i) => (
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
      {!props.compare && tags.length > 0 && (
        <div className={`ptags${compact ? " ptags-compact" : ""}`}>
          <svg className="ptag-leaders" width={shown} height={props.height * scale} aria-hidden="true">
            {tags.filter((g) => g.dot[1] < g.y || g.dot[1] > g.y + g.h).map((g) => {
              const ex = g.x > g.dot[0] ? g.x : g.x + g.w;
              const ey = Math.min(Math.max(g.dot[1], g.y + 6), g.y + g.h - 6);
              return <line key={g.pin.id} x1={g.dot[0]} y1={g.dot[1]} x2={ex} y2={ey} />;
            })}
          </svg>
          {tags.map((g, i) => {
            const on = g.pin.id === props.selected;
            return (
              <React.Fragment key={g.pin.id}>
                <span className={`pdot${on ? " pdot-on" : ""}${pulse ? " pdot-pulse" : ""}`} aria-hidden="true"
                  style={{ left: g.dot[0], top: g.dot[1] }} onClick={() => props.onSelect(g.pin.id)}
                  onPointerEnter={() => setHover(g.pin.target)} onPointerLeave={() => setHover(null)} />
                <button type="button" className={`ptag${on ? " ptag-on" : ""}`} data-item={g.pin.item}
                  style={{ left: g.x, top: g.y, height: g.h, animationDelay: `${160 + i * 70}ms` }}
                  aria-label={[g.pin.label, g.pin.value].filter(Boolean).join(": ")} aria-pressed={on}
                  onClick={() => props.onSelect(g.pin.id)}
                  onPointerEnter={() => setHover(g.pin.target)} onPointerLeave={() => setHover(null)}
                  onFocus={() => setHover(g.pin.target)} onBlur={() => setHover(null)}>
                  {g.text.label && <span className="ptag-label">{g.text.label}</span>}
                  {g.text.value && <span className="ptag-value">{g.text.value}</span>}
                </button>
              </React.Fragment>
            );
          })}
        </div>
      )}
      {!props.compare && active && (
        <div className={`hot-chip${chipBelow ? " hot-chip-below" : ""}`} key={active.id}
          style={{ left: `${Math.min(88, Math.max(12, (100 * active.centroid[0]) / props.width))}%`,
            top: `${(100 * active.centroid[1]) / props.height}%` }}>
          <strong>{active.label}</strong><span>{active.sub}</span>
        </div>
      )}
      {props.busy && <div className="canvas-busy-note" role="status"><span className="dot-live" />{props.busy}</div>}
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

type Viewable = { manifest: Design["manifest"]; quote: Quote; profile: Profile;
  finishes: { countertop: Finish; backsplash: Finish | null } };

// The surfaces to outline and tap: each countertop and backsplash, and each countertop's edge
// (smallest area, so it sits on top and a tap on the edge opens the edge options).
export function designLayers(design: Viewable, t: Strings): CanvasLayer[] {
  const out: CanvasLayer[] = design.manifest.layers.map((l) => ({
    id: l.surface_id, label: `${l.surface_class === "countertop" ? t.countertop : t.backsplash} ${l.run_id}`,
    sub: l.finish_name, polygon: l.polygon, centroid: l.centroid, area: l.area_mm2,
  }));
  design.manifest.layers.forEach((l) => {
    if (l.edge_polygon && l.edge_polygon.length > 2)
      out.push({ id: `${l.surface_id}_edge`, label: t.items.profile, sub: `${design.profile.name} (${design.profile.display})`,
        polygon: l.edge_polygon, centroid: l.edge_point || l.centroid, area: 0 });
  });
  return out;
}

const itemOf = (q: Quote, item: string) => q.items?.find((it) => it.item === item);

export function itemPrice(q: Quote, item: string, lang: Lang): string | undefined {
  const it = itemOf(q, item);
  return it ? moneyCompact(it.low, it.high, lang) : undefined;
}

// The labelled pointers: from the render manifest when it has them, else one per surface.
export function designPins(design: Viewable, t: Strings, lang: Lang): CanvasPin[] {
  const q = design.quote;
  const pointers: Pointer[] = design.manifest.pointers || design.manifest.layers.map((l, i, all) => ({
    id: l.surface_id, item: l.surface_class === "countertop" ? "countertop" : "backsplash", surface_id: l.surface_id,
    at: l.centroid, primary: all.findIndex((o) => o.surface_class === l.surface_class) === i,
  }));
  return pointers.map((p) => ({
    id: p.id, item: p.item, at: p.at,
    target: p.item === "profile" ? `${p.surface_id}_edge` : p.surface_id,
    label: p.item === "profile" ? `${t.items.profile} ${design.profile.name}` : t.items[p.item],
    value: p.primary && p.item !== "profile" ? itemPrice(q, p.item, lang) : undefined,
  }));
}

// The side panel's list: one row per priced item, with its price; a tap selects its pointer.
export function ItemRows(props: { design: Viewable; pins: CanvasPin[]; selected: string | null; onSelect: (id: string) => void }) {
  const { t, lang } = useLang();
  const d = props.design;
  const sel = props.pins.find((p) => p.id === props.selected);
  const runs = d.manifest.layers.filter((l) => l.surface_class === "countertop").length;
  const items = d.quote.items?.map((it) => it.item)
    || Array.from(new Set(d.manifest.layers.map((l) => (l.surface_class === "countertop" ? "countertop" : "backsplash"))));
  return (
    <ul className="design-rows">
      {items.map((item) => {
        const pin = props.pins.find((p) => p.item === item);
        const f = item === "countertop" ? d.finishes.countertop : item === "backsplash" ? d.finishes.backsplash : null;
        const on = sel?.item === item || (item === "countertop" && sel?.item === "profile");
        return (
          <li key={item}>
            <button className={on ? "on" : ""} data-item={item} onClick={() => pin && props.onSelect(pin.id)} disabled={!pin}>
              {f ? <img className="swatch" src={f.swatch_url} alt="" width={44} height={44} />
                : <span className="swatch swatch-icon" aria-hidden="true"><SinkGlyph /></span>}
              <span className="grow">
                <span className="tiny muted">{t.items[item]}{item === "countertop" && runs > 1 ? ` · ${t.runs(runs)}` : ""}</span>
                <strong>{f ? f.name : t.sinkRow}</strong>
                {item === "countertop" && <span className="tiny muted">{t.items.profile} {d.profile.name} · {d.profile.display}</span>}
              </span>
              <span className="row-price">{itemPrice(d.quote, item, lang)}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

export function SinkGlyph() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 11h18" /><path d="M5 11v3a5 5 0 0 0 5 5h4a5 5 0 0 0 5-5v-3" /><path d="M12 11V6a2 2 0 0 1 4 0" />
    </svg>
  );
}

// A countertop edge seen end-on, at its real thickness: square, or with rounded front corners.
export function EdgeDrawing(props: { profile: Pick<Profile, "thickness_mm" | "edge_shape">; label?: string }) {
  const th = Math.max(12, Math.min(60, props.profile.thickness_mm || 40));
  const h = th * 0.9, y = 34 - h / 2, r = props.profile.edge_shape === "rounded" ? Math.min(h / 2, 9) : 1.5;
  return (
    <svg className="edge-drawing" viewBox="0 0 120 68" role="img" aria-label={props.label}>
      <path d={`M8 ${y} H${112 - r} Q112 ${y} 112 ${y + r} V${y + h - r} Q112 ${y + h} ${112 - r} ${y + h} H8 Z`} />
      <line x1="8" y1={y + h + 7} x2="112" y2={y + h + 7} className="edge-ground" />
    </svg>
  );
}

// ---------------------------------------------------------------- quote pieces
export function QuoteLines(props: { quote: Quote; group?: "materials" | "labour"; surface?: string; item?: string; unitPrices?: boolean }) {
  const { lang } = useLang();
  const lines = props.quote.lines.filter((l) => (!props.group || l.group === props.group)
    && (!props.surface || l.surface === props.surface) && (!props.item || l.item === props.item));
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
        <tr className="total-row"><td>{q.estimate_only ? t.totalAsMeasured : t.total}</td>
          <td className="num">{money(q.total, lang, true)}</td></tr>
        {q.visit_fee && (
          <tr className="visit-row"><td>{t.visitFee}<div className="line-detail">{t.visitFeeRule(money(q.visit_fee, lang))}</div></td>
            <td className="num">{t.visitFree}</td></tr>
        )}
      </tbody>
    </table>
  );
}
