import React, { useEffect, useMemo, useState } from "react";
import { api, followJob, type BoardItem, type Catalogue, type Design, type Finish, type MoneyJ, type Photo, type Point,
  type Project, type Question, type StyleId, type Suggestion, type SurfaceItem } from "./api";
import { CompareCanvas, EdgeDrawing, ItemRows, QuadEditor, QuoteLines, QuoteTotals, SinkGlyph, WorkingView, designLayers,
  designPins, itemPrice, type CanvasLayer } from "./components";
import { cmToMm, mmToCm, money, moneyRange, signedMoney, splitCurrency } from "./format";
import { useLang } from "./lang";
import { ShareDialog } from "./share";
import { ErrorLine, Icon, Modal, Sheet, Skeleton, StepHeader, Stepper, go } from "./ui";

const STYLE_IDS: StyleId[] = ["minimalista", "calido", "contraste", "creativo"];

function useProject(pid: string) {
  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.project(pid).then(setProject).catch((e) => setError(e.message)); }, [pid]);
  return { project, error, setProject };
}

let catalogueCache: Promise<Catalogue> | null = null;
export function useCatalogue() {
  const [cat, setCat] = useState<Catalogue | null>(null);
  useEffect(() => { (catalogueCache ||= api.catalogue()).then(setCat); }, []);
  return cat;
}

// The style picked on the landing page travels to the style step (this browser only).
const rememberStyle = (s: StyleId | null) => { try { s ? sessionStorage.setItem("renovai.style", s) : sessionStorage.removeItem("renovai.style"); } catch { /* ok */ } };
const recallStyle = (): StyleId | null => { try { return sessionStorage.getItem("renovai.style") as StyleId | null; } catch { return null; } };

type DemoStyle = { id: StyleId; name: { es: string; en: string }; image: string; profile: string;
  countertop: { name: string; line: string; code: string | null; swatch_url: string };
  backsplash: { name: string; line: string; code: string | null; swatch_url: string } | null;
  layers: { surface_class: string; polygon: Point[]; centroid: Point }[] };
type Demo = { width: number; height: number; before: string; styles: DemoStyle[] };

function useDemo() {
  const [demo, setDemo] = useState<Demo | null>(null);
  useEffect(() => { fetch("/demo/demo.json").then((r) => r.json()).then(setDemo).catch(() => setDemo(null)); }, []);
  return demo;
}


// ----------------------------------------------------------------------- home
export function Home() {
  const { t, lang } = useLang();
  const demo = useDemo();
  const [style, setStyle] = useState<StyleId | null>(null);
  const [busy, setBusy] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [demoStyle, setDemoStyle] = useState<StyleId>("calido");
  const [demoSel, setDemoSel] = useState<string | null>(null);
  const cat = useCatalogue();

  const start = async (file?: File) => {
    if (busy) return;
    setBusy(true); setError(null);
    try {
      const p = await api.createProject();
      if (file) await api.uploadPhoto(p.id, file);
      rememberStyle(style);
      go(`#/p/${p.id}`);
    } catch (e: any) { setError(e.message); setBusy(false); }
  };
  const ds = demo?.styles.find((s) => s.id === demoStyle);
  const demoLayers: CanvasLayer[] = (ds?.layers || []).map((l, i) => ({
    id: `${l.surface_class}-${i}`, label: l.surface_class === "countertop" ? t.countertop : t.backsplash,
    sub: l.surface_class === "countertop" ? `${ds!.countertop.name} · ${ds!.profile}` : ds!.backsplash?.name || "",
    polygon: l.polygon, centroid: l.centroid, area: l.surface_class === "countertop" ? 2 : 1,
  }));
  const selFinish = demoSel && ds ? (demoSel.startsWith("countertop") ? ds.countertop : ds.backsplash) : null;
  const scrollTo = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  const styleName = (id: StyleId) => cat?.styles.find((s) => s.id === id)?.name[lang] || demo?.styles.find((s) => s.id === id)?.name[lang] || id;

  return (
    <div className="home">
      <section className="hero">
        <div className="hero-glow" aria-hidden="true" />
        <div className="hero-inner">
          <button className="eyebrow" onClick={() => scrollTo("demo")}><span className="eyebrow-dot" />{t.heroEyebrow}<Icon.arrowRight size={14} /></button>
          <h1 className="display">{t.homeTitle}</h1>
          <p className="lead lead-center">{t.homeSub}</p>

          <div className={`prompt${dragOver ? " prompt-drag" : ""}${busy ? " prompt-busy" : ""}`}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }} onDragLeave={() => setDragOver(false)}
            onDrop={(e) => { e.preventDefault(); setDragOver(false); const f = e.dataTransfer.files?.[0]; if (f) start(f); }}>
            <label className="prompt-drop">
              <input type="file" accept="image/jpeg,image/png,image/webp" className="sr-only" disabled={busy}
                onChange={(e) => { const f = e.target.files?.[0]; if (f) start(f); }} />
              <span className="prompt-text">{busy ? t.promptWorking : t.promptPlaceholder}</span>
              <span className="prompt-sub">{t.promptSub}</span>
            </label>
            <div className="prompt-bar">
              <div className="prompt-chips" role="radiogroup" aria-label={t.finishesTitle}>
                {STYLE_IDS.map((id) => (
                  <button key={id} role="radio" aria-checked={style === id} className={`chip${style === id ? " chip-on" : ""}`}
                    onClick={() => setStyle(style === id ? null : id)}>{styleName(id)}</button>
                ))}
              </div>
              <button className="send" onClick={() => start()} aria-label={t.promptGo} disabled={busy}>
                <Icon.arrowUp size={20} />
              </button>
            </div>
          </div>
          <p className="muted small hero-note">{t.homeFree}</p>
          <ErrorLine error={error} />
        </div>
      </section>

      <section className="section" id="demo">
        <div className="section-head">
          <h2 className="h2">{t.demoTitle}</h2>
          <p className="lead">{t.demoSub}</p>
        </div>
        {demo && ds ? (
          <div className="demo">
            <div className="pill-tabs" role="tablist">
              {demo.styles.map((s) => (
                <button key={s.id} role="tab" aria-selected={s.id === demoStyle} className={s.id === demoStyle ? "on" : ""}
                  onClick={() => { setDemoStyle(s.id); setDemoSel(null); }}>{s.name[lang]}</button>
              ))}
            </div>
            <div className="demo-grid">
              <div className="demo-frame">
                <CompareCanvas key={demoStyle} before={demo.before} after={ds.image} width={demo.width} height={demo.height}
                  layers={demoLayers} selected={demoSel} onSelect={setDemoSel} alt={ds.name[lang]} compare={!demoSel} startAt={42} />
              </div>
              <div className="demo-info card">
                {selFinish ? (
                  <div className="demo-head" key={demoSel}>
                    <img className="swatch swatch-lg" src={selFinish.swatch_url} alt="" />
                    <div className="caption">{demoSel!.startsWith("countertop") ? t.countertop : t.backsplash} · Kober {t.lines[selFinish.line]}</div>
                    <h3 className="h3">{selFinish.name}</h3>
                    {selFinish.code && <div className="small muted">{t.code} <span className="mono">{selFinish.code}</span></div>}
                  </div>
                ) : (
                  <div className="demo-head" key={demoStyle}>
                    <div className="caption">{ds.name[lang]}</div>
                    <h3 className="h3">{ds.countertop.name}{ds.backsplash ? ` + ${ds.backsplash.name}` : ""}</h3>
                    <p className="small muted">{t.tapHint}</p>
                  </div>
                )}
                <ul className="design-rows demo-rows">
                  {demoLayers.map((l) => {
                    const top = l.id.startsWith("countertop");
                    const f = top ? ds.countertop : ds.backsplash;
                    if (!f) return null;
                    return (
                      <li key={l.id}>
                        <button className={demoSel === l.id ? "on" : ""} aria-pressed={demoSel === l.id} onClick={() => setDemoSel(l.id)}>
                          <img className="swatch" src={f.swatch_url} alt="" width={44} height={44} />
                          <span className="grow">
                            <span className="tiny muted">{l.label}</span>
                            <strong>{f.name}</strong>
                            <span className="tiny muted">Kober {t.lines[f.line]}{top ? ` · ${ds.profile}` : ""}</span>
                          </span>
                          <Icon.arrowRight size={16} />
                        </button>
                      </li>
                    );
                  })}
                </ul>
                {demoSel
                  ? <button className="btn btn-light btn-sm" onClick={() => setDemoSel(null)}><Icon.compare size={16} />{t.compare}</button>
                  : <p className="tiny muted demo-hint"><Icon.compare size={14} />{t.demoDrag}</p>}
              </div>
            </div>
          </div>
        ) : <Skeleton height={420} radius={28} />}
      </section>

      <section className="section" id="how">
        <div className="section-head"><h2 className="h2">{t.howTitle}</h2></div>
        <ol className="how">
          {t.howSteps.map((s, i) => {
            const I = [Icon.image, Icon.ruler, Icon.palette, Icon.receipt][i];
            return (
              <li key={s.t} className="how-card">
                <span className="how-icon"><I size={22} /></span>
                <span className="how-n">0{i + 1}</span>
                <h3 className="h4">{s.t}</h3>
                <p className="small muted">{s.d}</p>
              </li>
            );
          })}
        </ol>
      </section>

      <section className="section" id="styles">
        <div className="section-head">
          <h2 className="h2">{t.stylesTitle}</h2>
          <p className="lead">{t.stylesSub}</p>
        </div>
        <div className="style-showcase">
          {(demo?.styles || []).map((s) => (
            <figure key={s.id} className="showcase-card">
              <img src={s.image} alt={s.name[lang]} loading="lazy" />
              <figcaption>
                <strong>{s.name[lang]}</strong>
                <span>{s.countertop.name}{s.backsplash ? ` · ${s.backsplash.name}` : ""}</span>
              </figcaption>
            </figure>
          ))}
        </div>
      </section>

      <section className="section" id="pricing">
        <div className="section-head"><h2 className="h2">{t.pricingTitle}</h2></div>
        <div className="pricing">
          {t.pricing.map((p, i) => (
            <div key={p.t} className={`price-card${i === 0 ? " price-card-hi" : ""}`}>
              <div className="caption">{p.t}</div>
              <div className="price-v">{p.v}</div>
              <p className="small muted">{p.d}{i === 1 && cat?.visit_fee ? ` ${t.visitFeeOther(money(cat.visit_fee, lang))}` : ""}</p>
            </div>
          ))}
        </div>
        <div className="cta-final">
          <h2 className="h2">{t.homeTitle}</h2>
          <button className="btn btn-dark btn-lg" onClick={() => start()}>{t.start}<Icon.arrowRight size={18} /></button>
        </div>
      </section>
    </div>
  );
}

// ------------------------------------------------------ step 1: photo + measurements
type RunRow = { run_id: string; length: string; depth: string };
type SplashRow = { run_id: string; length: string; height: string };

export function CmInput(props: { label: string; value: string; onChange: (v: string) => void; placeholder?: string }) {
  return (
    <label className="field">
      <span>{props.label}</span>
      <span className="input-suffix">
        <input inputMode="decimal" value={props.value} placeholder={props.placeholder} onChange={(e) => props.onChange(e.target.value)} />
        <em>cm</em>
      </span>
    </label>
  );
}

export function Measure(props: { pid: string }) {
  const { t, lang } = useLang();
  const { project, error: loadError, setProject } = useProject(props.pid);
  const [runs, setRuns] = useState<RunRow[]>([{ run_id: "A", length: "", depth: "64.5" }]);
  const [splash, setSplash] = useState<SplashRow[]>([{ run_id: "S1", length: "", height: "60" }]);
  const [sinks, setSinks] = useState(0);
  const [questions, setQuestions] = useState<Question[]>([]);
  const [confirmed, setConfirmed] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const photo: Photo | undefined = project?.photos[project.photos.length - 1];

  useEffect(() => {
    const m = project?.measurements;
    if (!m) return;
    setRuns(m.countertop_runs.map((r) => ({ run_id: r.run_id, length: mmToCm(r.length_mm), depth: mmToCm(r.depth_mm) })));
    setSplash(m.splash_runs.map((r) => ({ run_id: r.run_id, length: mmToCm(r.length_mm), height: mmToCm(r.height_mm) })));
    setSinks(m.sinks);
  }, [project?.id]);

  const upload = async (file: File) => {
    setBusy(true); setError(null);
    try {
      await api.uploadPhoto(props.pid, file);
      setProject(await api.project(props.pid));
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };

  const submit = async (extraConfirmed: string[] = confirmed) => {
    setError(null);
    if (!photo) return setError(t.needPhoto);
    const countertop_runs = runs.filter((r) => r.length.trim()).map((r) => ({
      run_id: r.run_id, length_mm: cmToMm(r.length) ?? 0, depth_mm: cmToMm(r.depth) ?? 645 }));
    if (!countertop_runs.length || countertop_runs.some((r) => !r.length_mm)) return setError(t.needRun);
    const splash_runs = splash.filter((r) => r.length.trim()).map((r) => ({
      run_id: r.run_id, length_mm: cmToMm(r.length) ?? 0, height_mm: cmToMm(r.height) ?? 600 }));
    try {
      const res = await api.putMeasurements(props.pid, { countertop_runs, splash_runs, sinks, confirmed_questions: extraConfirmed });
      if (res.questions.length) { setQuestions(res.questions); return; }
      setQuestions([]);
      const { job_id } = await api.analyse(props.pid, photo.id, lang);
      setJobId(job_id);
    } catch (e: any) { setError(e.message); }
  };

  if (loadError) return <div className="flow"><ErrorLine error={loadError} /></div>;
  if (!project) return <div className="flow"><Skeleton /></div>;
  const photoUrl = photo ? `/media/${props.pid}/${photo.path}` : undefined;
  if (jobId && photo) {
    return (
      <section className="flow">
        <StepHeader step={1} title={t.working.analyse} />
        <WorkingView jobId={jobId} kind="analyse" stages={["GEOMETRY", "DESCRIBE"]} photoUrl={photoUrl}
          onDone={() => go(`#/p/${props.pid}/surfaces/${photo.id}`)} onFail={(m) => { setError(m); setJobId(null); }} />
      </section>
    );
  }
  const check = (ok: boolean, good: string, bad: string) =>
    <span className={`badge ${ok ? "badge-ok" : "badge-warn"}`}>{ok ? <Icon.check size={14} /> : <Icon.info size={14} />}{ok ? good : bad}</span>;

  return (
    <section className="flow">
      <StepHeader step={1} title={t.measureTitle} sub={t.measureSub} onBack={() => go("#/")} />
      <div className="split">
        <div className="card">
          <h2 className="h3">{t.photos}</h2>
          <p className="muted small">{t.photosHelp}</p>
          <label className={`dropzone${photo ? " has-photo" : ""}${dragOver ? " drag" : ""}`}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }} onDragLeave={() => setDragOver(false)}
            onDrop={(e) => { e.preventDefault(); setDragOver(false); const f = e.dataTransfer.files?.[0]; if (f) upload(f); }}>
            <input type="file" accept="image/jpeg,image/png,image/webp" className="sr-only"
              onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
            {photoUrl ? (
              <>
                <img src={photoUrl} alt="" className="dropzone-img" />
                <span className="btn btn-light btn-sm dropzone-change"><Icon.upload size={16} />{busy ? t.uploading : t.changePhoto}</span>
              </>
            ) : (
              <span className="dropzone-empty">
                <span className="dropzone-icon"><Icon.image size={28} /></span>
                <strong>{busy ? t.uploading : t.dropHere}</strong>
                <span className="btn btn-dark btn-sm">{t.choosePhoto}</span>
              </span>
            )}
          </label>
          {photo?.checks && (
            <div className="badges">
              {check(photo.checks.light === "pass", t.checkLight[0], t.checkLight[1])}
              {check(photo.checks.sharp === "pass", t.checkSharp[0], t.checkSharp[1])}
              {photo.checks.camera_info === "warn" && <span className="badge"><Icon.info size={14} />{t.checkCamera}</span>}
            </div>
          )}
        </div>

        <div className="card">
          <h2 className="h3">{t.measurements}</h2>
          <p className="muted small">{t.measurementsHelp}</p>
          {runs.map((r, i) => (
            <div key={r.run_id} className="run-row">
              <div className="run-name"><span className="dot dot-top" />{t.countertop} {r.run_id}</div>
              <CmInput label={t.length} value={r.length} placeholder="240"
                onChange={(v) => setRuns(runs.map((x, j) => j === i ? { ...x, length: v } : x))} />
              <CmInput label={t.depth} value={r.depth}
                onChange={(v) => setRuns(runs.map((x, j) => j === i ? { ...x, depth: v } : x))} />
              {runs.length > 1 && <button className="icon-btn" aria-label={t.remove} onClick={() => setRuns(runs.filter((_, j) => j !== i))}><Icon.close size={16} /></button>}
            </div>
          ))}
          {runs.length < 4 && <button className="btn btn-ghost btn-sm" onClick={() =>
            setRuns([...runs, { run_id: "ABCD"[runs.length], length: "", depth: "64.5" }])}><Icon.plus size={16} />{t.addRun}</button>}

          {splash.map((r, i) => (
            <div key={r.run_id} className="run-row">
              <div className="run-name"><span className="dot dot-splash" />{t.backsplash} {r.run_id}</div>
              <CmInput label={t.length} value={r.length} placeholder="240"
                onChange={(v) => setSplash(splash.map((x, j) => j === i ? { ...x, length: v } : x))} />
              <CmInput label={t.height} value={r.height}
                onChange={(v) => setSplash(splash.map((x, j) => j === i ? { ...x, height: v } : x))} />
              <button className="icon-btn" aria-label={t.remove} onClick={() => setSplash(splash.filter((_, j) => j !== i))}><Icon.close size={16} /></button>
            </div>
          ))}
          {splash.length < 4 && <button className="btn btn-ghost btn-sm" onClick={() =>
            setSplash([...splash, { run_id: `S${splash.length + 1}`, length: "", height: "60" }])}><Icon.plus size={16} />{t.addSplash}</button>}

          <div className="sinks-row">
            <span>{t.sinks}</span>
            <Stepper value={sinks} min={0} max={2} onChange={setSinks} label={t.sinks} />
          </div>
          <p className="alert alert-info"><Icon.info size={16} />{t.rangeNote}</p>
        </div>
      </div>

      {questions.map((q) => (
        <div key={q.id} className="alert alert-warn question" role="alert">
          <p>{q.message}</p>
          <div className="row">
            <button className="btn btn-dark btn-sm" onClick={() => { const c = [...confirmed, q.id]; setConfirmed(c); submit(c); }}>{t.yesRight}</button>
            <button className="btn btn-ghost btn-sm" onClick={() => setQuestions([])}>{t.fix}</button>
          </div>
        </div>
      ))}
      <ErrorLine error={error} />
      <div className="action-bar">
        <button className="btn btn-dark btn-lg" onClick={() => submit()}>{t.findSurfaces}<Icon.arrowRight size={18} /></button>
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ step 2: surfaces
export function Surfaces(props: { pid: string; photoId: string }) {
  const { t } = useLang();
  const { project, error: loadError } = useProject(props.pid);
  const [items, setItems] = useState<SurfaceItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const photo = project?.photos.find((p) => p.id === props.photoId);

  useEffect(() => {
    if (project && items === null) setItems(project.surfaces?.[props.photoId]?.items ?? []);
  }, [project]);

  if (loadError) return <div className="flow"><ErrorLine error={loadError} /></div>;
  if (!project || !photo || items === null) return <div className="flow"><Skeleton /></div>;
  const w = photo.width, h = photo.height;
  const runs = project.measurements?.countertop_runs.map((r) => r.run_id) ?? ["A"];
  const splashRuns = project.measurements?.splash_runs.map((r) => r.run_id) ?? [];
  const add = (cls: "countertop" | "backsplash") => {
    const n = items.filter((i) => i.surface_class === cls).length + 1;
    const quad: Point[] = cls === "countertop"
      ? [[0.2 * w, 0.55 * h], [0.8 * w, 0.55 * h], [0.9 * w, 0.75 * h], [0.1 * w, 0.75 * h]]
      : [[0.2 * w, 0.3 * h], [0.8 * w, 0.3 * h], [0.8 * w, 0.52 * h], [0.2 * w, 0.52 * h]];
    const run = cls === "countertop" ? runs[Math.min(n - 1, runs.length - 1)] : splashRuns[Math.min(n - 1, splashRuns.length - 1)];
    setItems([...items, { surface_id: `${cls}_${n}`, surface_class: cls, run_id: run,
      quad: quad.map(([x, y]) => [Math.round(x), Math.round(y)]) as Point[], polygon: null, mask_file: null }]);
  };
  const label = (it: SurfaceItem) => `${it.surface_class === "countertop" ? t.countertop : t.backsplash} ${it.run_id}`;
  const confirm = async () => {
    setError(null);
    try {
      await api.putSurfaces(props.pid, props.photoId, items);
      go(`#/p/${props.pid}/finishes/${props.photoId}`);
    } catch (e: any) { setError(e.message); }
  };
  return (
    <section className="flow flow-wide">
      <StepHeader step={2} title={t.surfacesTitle} sub={t.surfacesSub} onBack={() => go(`#/p/${props.pid}`)} />
      {!items.some((i) => i.surface_class === "countertop") && <p className="alert alert-info"><Icon.info size={16} />{t.notFound}</p>}
      <div className="editor-layout">
        <div className="card card-flush">
          <QuadEditor imageUrl={`/media/${props.pid}/${photo.path}`} width={w} height={h} items={items} onChange={setItems} labels={label} />
        </div>
        <aside className="card">
          <h2 className="h3">{t.surfaceList}</h2>
          <ul className="surface-rows">
            {items.map((it, i) => (
              <li key={it.surface_id}>
                <span className={`dot ${it.surface_class === "countertop" ? "dot-top" : "dot-splash"}`} />
                <div className="grow">
                  <div className="row-title">{label(it)}</div>
                  <span className="badge badge-soft">{it.mask_file ? t.detected : t.manual}</span>
                </div>
                <select aria-label={t.assignRun} value={it.run_id}
                  onChange={(e) => setItems(items.map((x, j) => j === i ? { ...x, run_id: e.target.value } : x))}>
                  {(it.surface_class === "countertop" ? runs : splashRuns).map((r) => <option key={r} value={r}>{t.assignRun} {r}</option>)}
                </select>
                <button className="icon-btn" aria-label={t.remove} onClick={() => setItems(items.filter((_, j) => j !== i))}><Icon.close size={16} /></button>
              </li>
            ))}
          </ul>
          <div className="row wrap">
            <button className="btn btn-ghost btn-sm" onClick={() => add("countertop")}><Icon.plus size={16} />{t.placeCountertop}</button>
            {splashRuns.length > 0 && <button className="btn btn-ghost btn-sm" onClick={() => add("backsplash")}><Icon.plus size={16} />{t.placeSplash}</button>}
          </div>
        </aside>
      </div>
      <ErrorLine error={error} />
      <div className="action-bar">
        <button className="btn btn-dark btn-lg" disabled={!items.some((i) => i.surface_class === "countertop")} onClick={confirm}>
          {t.surfacesOk}<Icon.arrowRight size={18} />
        </button>
      </div>
    </section>
  );
}

// -------------------------------------------------------------------- step 3: style
export function Swatch(props: { finish: Finish | undefined | null; size?: number }) {
  if (!props.finish) return <span className="swatch swatch-none" style={{ width: props.size || 56, height: props.size || 56 }} />;
  return <img className="swatch" src={props.finish.swatch_url} alt="" width={props.size || 56} height={props.size || 56} />;
}

function profilesFor(cat: Catalogue, finish: Finish | undefined) {
  if (!finish) return [];
  return cat.profiles.filter((p) => p.finish_lines.includes(finish.line) && !(finish.id === "estilo-porfido-nero" && p.id === "slim"));
}

export function Finishes(props: { pid: string; photoId: string }) {
  const { t, lang } = useLang();
  const cat = useCatalogue();
  const demo = useDemo();
  const { project } = useProject(props.pid);
  const [tab, setTab] = useState<"styles" | "catalogue">("styles");
  const [styleId, setStyleId] = useState<StyleId | null>(recallStyle());
  const [text, setText] = useState("");
  const [budget, setBudget] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [suggestJob, setSuggestJob] = useState<string | null>(null);
  const [job, setJob] = useState<{ id: string; kind: "design" | "styles" } | null>(null);
  const [lineFilter, setLineFilter] = useState<string>("all");
  const [top, setTop] = useState<string | null>(null);
  const [splashMode, setSplashMode] = useState<"same" | "other" | "none">("same");
  const [splashId, setSplashId] = useState<string | null>(null);
  const [profile, setProfile] = useState<string>("original_q");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { if (project?.suggestions?.items) setSuggestions(project.suggestions.items); }, [project?.id]);
  const byId = useMemo(() => new Map((cat?.finishes || []).map((f) => [f.id, f])), [cat]);
  const hasSplash = (project?.measurements?.splash_runs.length || 0) > 0;
  const photo = project?.photos.find((p) => p.id === props.photoId);
  const photoUrl = photo ? `/media/${props.pid}/${photo.path}` : undefined;

  const startDesign = async (choice: { countertop_finish_id: string; profile_id: string; splash_finish_id: string | null }) => {
    setError(null);
    try {
      const { job_id } = await api.design(props.pid, { photo_id: props.photoId, fulfilment_type: "MANAGED", language: lang, ...choice,
        splash_finish_id: hasSplash ? choice.splash_finish_id : null });
      setJob({ id: job_id, kind: "design" });
    } catch (e: any) { setError(e.message); }
  };
  const ask = async () => {
    setError(null);
    try { setSuggestJob((await api.suggest(props.pid, text, styleId, budget, lang)).job_id); } catch (e: any) { setError(e.message); }
  };
  const board = async () => {
    setError(null);
    try { setJob({ id: (await api.styleBoard(props.pid, props.photoId, budget, lang)).job_id, kind: "styles" }); }
    catch (e: any) { setError(e.message); }
  };

  if (!cat || !project) return <div className="flow"><Skeleton /></div>;
  if (job) {
    return (
      <section className="flow">
        <StepHeader step={job.kind === "styles" ? 3 : 4} title={t.working[job.kind]} />
        <WorkingView jobId={job.id} kind={job.kind} photoUrl={photoUrl}
          stages={job.kind === "styles" ? ["DESIGN", "RENDER", "QUOTE"] : ["RENDER", "QUOTE"]}
          onDone={(r) => go(job.kind === "styles" ? `#/p/${props.pid}/styles/${props.photoId}` : `#/d/${r.design_id}`)}
          onFail={(m) => { setError(m); setJob(null); }} />
      </section>
    );
  }
  const topFinish = top ? byId.get(top) : undefined;
  const profiles = profilesFor(cat, topFinish);
  const chosenProfile = profiles.some((p) => p.id === profile) ? profile : profiles[0]?.id;
  const styleName = (id: StyleId) => cat.styles.find((s) => s.id === id)?.name[lang] || id;
  const available = (f: Finish) => f.available !== false;

  return (
    <section className="flow flow-wide">
      <StepHeader step={3} title={t.finishesTitle} sub={t.finishesSub} onBack={() => go(`#/p/${props.pid}/surfaces/${props.photoId}`)} />
      <div className="pill-tabs" role="tablist">
        <button role="tab" aria-selected={tab === "styles"} className={tab === "styles" ? "on" : ""} onClick={() => setTab("styles")}>{t.tabSuggest}</button>
        <button role="tab" aria-selected={tab === "catalogue"} className={tab === "catalogue" ? "on" : ""} onClick={() => setTab("catalogue")}>{t.tabCatalogue}</button>
      </div>

      {tab === "styles" && (
        <>
          <div className="style-grid" role="radiogroup" aria-label={t.finishesTitle}>
            {cat.styles.map((s) => (
              <button key={s.id} role="radio" aria-checked={styleId === s.id} className={`style-card${styleId === s.id ? " on" : ""}`}
                onClick={() => setStyleId(styleId === s.id ? null : s.id)}>
                <span className="style-img">{demo && <img src={`/demo/${s.id}.jpg`} alt="" loading="lazy" />}</span>
                <span className="style-body">
                  <strong>{s.name[lang]}</strong>
                  <span className="small muted">{s.blurb[lang]}</span>
                </span>
                <span className="style-check" aria-hidden="true"><Icon.check size={14} /></span>
              </button>
            ))}
          </div>

          <div className="refine card">
            <span className="caption">{t.refine}</span>
            <div className="refine-row">
              <input className="grow" value={text} placeholder={t.stylePlaceholder} onChange={(e) => setText(e.target.value)} maxLength={200} />
              <div className="chips" role="radiogroup" aria-label={t.budget}>
                {Object.entries(t.budgets).map(([k, v]) => (
                  <button key={k} role="radio" aria-checked={budget === k} className={`chip${budget === k ? " chip-on" : ""}`}
                    onClick={() => setBudget(budget === k ? null : k)}>{v}</button>
                ))}
              </div>
            </div>
          </div>

          <div className="cta-row">
            <button className="btn btn-dark btn-lg" onClick={board}><Icon.grid size={18} />{t.seeAllStyles}</button>
            <button className="btn btn-light btn-lg" onClick={ask} disabled={!!suggestJob || (!styleId && !text.trim())}>
              <Icon.sparkle size={18} />{styleId ? t.suggestFor(styleName(styleId)) : t.suggestAny}
            </button>
          </div>

          {suggestJob && (
            <div className="card inline-working"><span className="spinner" />{t.working.suggest}…
              <HiddenJob jobId={suggestJob} onDone={(r) => { setSuggestions(r.suggestions); setSuggestJob(null); }}
                onFail={(m) => { setError(m); setSuggestJob(null); }} />
            </div>
          )}
          {suggestions.length > 0 && (
            <div className="suggest-grid">
              {suggestions.map((s, i) => {
                const a = byId.get(s.countertop_finish_id), b = s.backsplash_finish_id ? byId.get(s.backsplash_finish_id) : undefined;
                return (
                  <article key={i} className="card suggestion">
                    <div className="swatch-pair">
                      <Swatch finish={a} size={112} />
                      {hasSplash && <Swatch finish={b} size={112} />}
                    </div>
                    <h3 className="h4">{s.title}</h3>
                    <p className="small">{a?.name} · {cat.profiles.find((p) => p.id === s.profile_id)?.name}
                      {hasSplash && b ? ` · ${t.forSplash}: ${b.name}` : ""}</p>
                    <p className="small muted">{s.reason}</p>
                    <button className="btn btn-dark" onClick={() => startDesign({ countertop_finish_id: s.countertop_finish_id,
                      profile_id: s.profile_id, splash_finish_id: s.backsplash_finish_id })}>{t.pickThis}<Icon.arrowRight size={16} /></button>
                  </article>
                );
              })}
            </div>
          )}
        </>
      )}

      {tab === "catalogue" && (
        <div className="catalogue">
          <div className="chips">
            {["all", "estilo", "diseno", "basik"].map((l) => (
              <button key={l} className={`chip${lineFilter === l ? " chip-on" : ""}`} onClick={() => setLineFilter(l)}>
                {l === "all" ? t.all : t.lines[l]}
              </button>
            ))}
          </div>
          {cat.placeholder_swatches && <p className="tiny muted sample-note"><Icon.info size={14} />{t.sampleSwatches}</p>}
          <div className="swatch-grid">
            {cat.finishes.filter((f) => lineFilter === "all" || f.line === lineFilter).map((f) => (
              <button key={f.id} className={`swatch-card${top === f.id ? " on" : ""}`} onClick={() => setTop(f.id)} aria-pressed={top === f.id}
                disabled={!available(f)}>
                <Swatch finish={f} size={120} /><span className="swatch-name">{f.name}</span>
                <span className="tiny muted">{available(f) ? t.lines[f.line] : t.unavailable}</span>
              </button>
            ))}
          </div>
          {topFinish && (
            <div className="choice-bar">
              <div className="choice-main">
                <Swatch finish={topFinish} size={48} />
                <div><strong>{topFinish.name}</strong><div className="tiny muted">{t.lines[topFinish.line]}</div></div>
              </div>
              <label className="field field-inline"><span>{t.profile}</span>
                <select value={chosenProfile} onChange={(e) => setProfile(e.target.value)}>
                  {profiles.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.display})</option>)}
                </select>
              </label>
              {hasSplash && (
                <div className="chips" role="radiogroup" aria-label={t.forSplash}>
                  {(["same", "other", "none"] as const).map((m) => (
                    <button key={m} role="radio" aria-checked={splashMode === m} className={`chip${splashMode === m ? " chip-on" : ""}`}
                      onClick={() => setSplashMode(m)}>{m === "same" ? t.sameAsTop : m === "other" ? t.otherFinish : t.noSplash}</button>
                  ))}
                </div>
              )}
              {hasSplash && splashMode === "other" && (
                <div className="swatch-grid small-grid">
                  {cat.finishes.filter(available).map((f) => (
                    <button key={f.id} className={`swatch-card${splashId === f.id ? " on" : ""}`} onClick={() => setSplashId(f.id)}>
                      <Swatch finish={f} size={56} /><span className="tiny">{f.name}</span>
                    </button>
                  ))}
                </div>
              )}
              <button className="btn btn-dark btn-lg" disabled={!chosenProfile || (splashMode === "other" && !splashId)}
                onClick={() => startDesign({ countertop_finish_id: topFinish.id, profile_id: chosenProfile!,
                  splash_finish_id: splashMode === "same" ? topFinish.id : splashMode === "other" ? splashId : null })}>
                {t.seeKitchen}<Icon.arrowRight size={18} />
              </button>
            </div>
          )}
        </div>
      )}
      <ErrorLine error={error} />
    </section>
  );
}

// Follows a short job without taking over the screen.
function HiddenJob(props: { jobId: string; onDone: (r: any) => void; onFail: (m: string) => void }) {
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      while (alive) {
        try {
          const j = await api.job(props.jobId);
          if (j.status === "done") { props.onDone(j.result); return; }
          if (j.status === "failed") { props.onFail(j.error || "failed"); return; }
        } catch { /* keep trying */ }
        await new Promise((r) => setTimeout(r, 700));
      }
    };
    tick();
    return () => { alive = false; };
  }, [props.jobId]);
  return null;
}

// ------------------------------------------------------------- step 3b: style board
export function StyleBoard(props: { pid: string; photoId: string }) {
  const { t, lang } = useLang();
  const cat = useCatalogue();
  const { project, error } = useProject(props.pid);
  if (error) return <div className="flow"><ErrorLine error={error} /></div>;
  if (!project || !cat) return <div className="flow"><Skeleton /></div>;
  const items: BoardItem[] = project.style_board?.items || [];
  const name = (id?: string | null) => (id ? cat.finishes.find((f) => f.id === id)?.name : undefined);
  return (
    <section className="flow flow-wide">
      <StepHeader step={3} title={t.boardTitle} sub={t.boardSub} onBack={() => go(`#/p/${props.pid}/finishes/${props.photoId}`)} />
      <div className="board-grid">
        {items.map((b) => {
          const style = cat.styles.find((s) => s.id === b.style_id);
          if (!b.design_id) {
            return <div key={b.style_id} className="board-card board-failed"><strong>{style?.name[lang]}</strong><span>{t.boardFailed}</span></div>;
          }
          return (
            <button key={b.style_id} className="board-card" onClick={() => go(`#/d/${b.design_id}`)}>
              <img src={b.image_url} alt={style?.name[lang]} />
              <span className="board-meta">
                <span className="board-pill">{style?.name[lang]}</span>
                <strong>{name(b.countertop_finish_id)}{b.splash_finish_id ? ` · ${name(b.splash_finish_id)}` : ""}</strong>
                {b.estimate && <span className="board-price">{moneyRange(b.estimate.low, b.estimate.high, lang, t.approx)}</span>}
              </span>
              <span className="board-go"><Icon.arrowRight size={18} /></span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

// -------------------------------------------------------------- step 4: design review
export function PriceNotice(props: { status: string }) {
  const { t } = useLang();
  if (props.status === "LIVE") return null;
  return <p className="alert alert-warn small">{props.status === "DRAFT" ? t.draftPrices : t.placeholderPrices}</p>;
}

export function Result(props: { did: string }) {
  const { t, lang } = useLang();
  const cat = useCatalogue();
  const [design, setDesign] = useState<Design | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [compare, setCompare] = useState(false);
  const [showQuote, setShowQuote] = useState(false);
  const [booking, setBooking] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [edge, setEdge] = useState<string | null>(null);        // the edge picked in the edge sheet
  const [edgeJob, setEdgeJob] = useState<string | null>(null);  // re-rendering with that edge
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setDesign(null); setSelected(null); setCompare(false); setEdge(null); setEdgeJob(null);
    api.getDesign(props.did).then((d) => { setDesign(d); return api.project(d.project_id); }).then(setProject)
      .catch((e) => setError(e.message));
  }, [props.did]);
  useEffect(() => {
    document.querySelector(".review-head .pill-tabs .on")?.scrollIntoView({ block: "nearest", inline: "center" });
  }, [design?.id, project?.id]);
  useEffect(() => {
    if (!edgeJob) return;
    return followJob(edgeJob, (e) => {
      if (e.stage !== "JOB") return;
      if (e.status === "done") go(`#/d/${e.result.design_id}`);
      else { setError(e.detail || "failed"); setEdgeJob(null); }
    });
  }, [edgeJob]);
  if (error && !design) return <div className="flow"><ErrorLine error={error} /></div>;
  if (!design) return <div className="review"><Skeleton height={520} radius={24} /></div>;

  const q = design.quote;
  const layers = designLayers(design, t);
  const pins = designPins(design, t, lang);
  const pin = pins.find((p) => p.id === selected);
  const board = project?.style_board?.items.filter((b) => b.design_id) || [];
  const onBoard = board.some((b) => b.design_id === design.id);
  const back = () => go(onBoard ? `#/p/${design.project_id}/styles/${design.photo_id}` : `#/p/${design.project_id}/finishes/${design.photo_id}`);
  const range = moneyRange(q.estimate.low, q.estimate.high, lang, t.approx);
  const [rangeMain, rangeCur] = splitCurrency(range);
  const select = (id: string | null) => { setSelected(id); setEdge(null); };
  const changeEdge = async (profileId: string) => {
    setError(null);
    try {
      const { job_id } = await api.design(design.project_id, { photo_id: design.photo_id, countertop_finish_id: design.choice.countertop_finish_id,
        profile_id: profileId, splash_finish_id: design.choice.splash_finish_id, fulfilment_type: design.choice.fulfilment_type, language: lang });
      setEdgeJob(job_id);
    } catch (e: any) { setError(e.message); }
  };

  return (
    <section className="review" data-route="design-review">
      <div className="review-head">
        <div>
          <button className="link-back" onClick={back}><Icon.back size={18} />{onBoard ? t.otherStyles : t.back}</button>
          <h1 className="h1">{t.resultTitle(design.finishes.countertop.name)}</h1>
        </div>
        {onBoard && cat && (
          <nav className="pill-tabs pill-tabs-dark" aria-label={t.otherStyles}>
            {board.map((b) => (
              <button key={b.style_id} className={b.design_id === design.id ? "on" : ""} onClick={() => go(`#/d/${b.design_id}`)}>
                {cat.styles.find((s) => s.id === b.style_id)?.name[lang]}
              </button>
            ))}
          </nav>
        )}
      </div>

      <div className="review-grid">
        <div className="review-canvas">
          <CompareCanvas before={design.manifest.before_url} after={design.manifest.image.url}
            width={design.manifest.image.width} height={design.manifest.image.height} layers={layers} pins={pins}
            selected={selected} onSelect={select} alt={t.resultTitle(design.finishes.countertop.name)}
            compare={compare} startAt={50} busy={edgeJob ? t.changingEdge : null} />
          <div className="canvas-toolbar">
            <button className={`btn btn-glass btn-sm${compare ? " on" : ""}`} onClick={() => setCompare(!compare)} aria-pressed={compare}>
              <Icon.compare size={16} />{t.compare}
            </button>
            <span className="muted small">{compare ? t.demoDrag : t.tapHint}</span>
          </div>
        </div>

        <aside className="review-side">
          <div className="card quote-card">
            <PriceNotice status={q.price_list_status} />
            <div className="badges">
              {q.estimate_only && <span className="badge">{t.estimate}</span>}
              {q.scale_confidence === "low" && <span className="badge">{t.ownMeasurements}</span>}
            </div>
            <div className="numeral">{rangeMain}{rangeCur && <span className="numeral-cur">{rangeCur}</span>}</div>
            {q.estimate_only && <p className="small muted">{t.rangeWhy}</p>}

            <h3 className="caption list-title">{t.inYourDesign}</h3>
            <ItemRows design={design} pins={pins} selected={selected} onSelect={(id) => { setCompare(false); select(id); }} />
            <ErrorLine error={error} />

            <button className="btn btn-accent btn-lg btn-block" onClick={() => setBooking(true)}><Icon.calendar size={18} />{t.book}</button>
            <div className="quote-actions">
              <button className="btn btn-glass" onClick={() => setSharing(true)}><Icon.share size={16} />{t.share}</button>
              <button className="btn btn-glass" onClick={() => go(`#/d/${design.id}/print`)}><Icon.printer size={16} />{t.print}</button>
            </div>
            <button className="btn btn-glass btn-block" onClick={() => setShowQuote(!showQuote)} aria-expanded={showQuote}>
              <Icon.receipt size={16} />{showQuote ? t.hideQuote : t.fullQuote}
            </button>
            {showQuote && (
              <div className="quote-full">
                <h4 className="caption">{t.materials}</h4>
                <QuoteLines quote={q} group="materials" />
                <h4 className="caption">{t.labour}</h4>
                <QuoteLines quote={q} group="labour" />
                <QuoteTotals quote={q} />
                {q.assumptions.length > 0 && <ul className="assumptions tiny muted">{q.assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul>}
              </div>
            )}
            <button className="btn-link" onClick={() => go(`#/p/${design.project_id}/finishes/${design.photo_id}`)}>{t.tryAnother}</button>
          </div>
        </aside>
      </div>

      <div className="mobile-bar">
        <div><div className="tiny muted">{t.estimate}{rangeCur ? ` · ${rangeCur}` : ""}</div><strong>{rangeMain}</strong></div>
        <div className="row">
          <button className="icon-btn" aria-label={t.share} onClick={() => setSharing(true)}><Icon.share size={18} /></button>
          <button className="btn btn-accent" onClick={() => setBooking(true)}><Icon.calendar size={16} />{t.submitBooking}</button>
        </div>
      </div>

      {pin && (
        <ItemSheet design={design} item={pin.item} surfaceId={pin.target} cat={cat} edge={edge} onEdge={setEdge}
          busy={!!edgeJob} onClose={() => select(null)} onChangeEdge={changeEdge}
          onShowEdge={() => { const e = pins.find((p) => p.item === "profile"); if (e) setSelected(e.id); }} />
      )}
      {booking && <BookingForm pid={design.project_id} did={design.id} range={range} visitFee={q.visit_fee} onClose={() => setBooking(false)} />}
      {sharing && <ShareDialog design={design} range={range} onClose={() => setSharing(false)} />}
    </section>
  );
}

// What a pointer opens: the product, its price with IVA and the pieces behind it; for the edge,
// the other edges this finish is made in, what each changes, and a button to see it rendered.
function ItemSheet(props: { design: Design; item: string; surfaceId: string | null; cat: Catalogue | null;
  edge: string | null; onEdge: (id: string) => void; busy: boolean; onClose: () => void;
  onChangeEdge: (profileId: string) => void; onShowEdge: () => void }) {
  const { t, lang } = useLang();
  const d = props.design, q = d.quote;
  const price = itemPrice(q, props.item, lang);
  const priceBlock = price && (
    <div className="item-price">
      <strong>{price}</strong>
      <span className="tiny muted">{t.ivaIncluded} · {t.itemNote[props.item]}</span>
    </div>
  );
  if (props.item === "profile") {
    const full = (id: string) => props.cat?.profiles.find((p) => p.id === id);
    const now = { ...d.profile, ...full(d.profile.id) };
    const options = q.profile_options || [];
    const picked = options.find((o) => o.profile_id === props.edge);
    return (
      <Sheet label={t.edgeTitle} onClose={props.onClose}>
        <div className="sheet-art"><EdgeDrawing profile={now} label={`${now.name} ${now.display}`} /></div>
        <div className="caption">{t.edgeTitle} · {d.finishes.countertop.name}</div>
        <h2 className="h2">{now.name}</h2>
        <div className="small muted">{t.thickness} {now.display}{now.edge_shape ? ` · ${now.edge_shape === "rounded" ? t.rounded : t.square}` : ""}</div>
        <h3 className="caption list-title">{options.length ? t.edgeOthers : ""}</h3>
        {options.length === 0 ? <p className="small muted">{t.edgeOnly}</p> : (
          <ul className="edge-options" role="radiogroup" aria-label={t.edgeOthers}>
            {options.map((o) => {
              const p = { ...o, ...full(o.profile_id) };
              return (
                <li key={o.profile_id}>
                  <button role="radio" aria-checked={props.edge === o.profile_id} className={props.edge === o.profile_id ? "on" : ""}
                    onClick={() => props.onEdge(o.profile_id)} disabled={props.busy}>
                    <EdgeDrawing profile={p} />
                    <span className="grow"><strong>{o.name}</strong><span className="tiny muted">{o.display}</span></span>
                    <span className={`diff${o.difference.minor < 0 ? " diff-down" : ""}`}>
                      {o.difference.minor === 0 ? t.edgeSame : signedMoney(o.difference, lang)}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
        {options.length > 0 && (
          <button className="btn btn-accent btn-block" disabled={!picked || props.busy} onClick={() => picked && props.onChangeEdge(picked.profile_id)}>
            {props.busy ? t.changingEdge : picked ? t.seeWithEdge(picked.name) : t.changeEdge}
          </button>
        )}
      </Sheet>
    );
  }
  if (props.item === "sink") {
    return (
      <Sheet label={t.sinkTitle} onClose={props.onClose}>
        <div className="sheet-art sheet-art-icon"><SinkGlyph /></div>
        <div className="caption">{t.items.sink}</div>
        <h2 className="h2">{t.sinkTitle}</h2>
        {priceBlock}
        <h3 className="caption list-title">{t.pieces}</h3>
        <QuoteLines quote={q} item="sink" />
      </Sheet>
    );
  }
  const layer = d.manifest.layers.find((l) => l.surface_id === props.surfaceId);
  const finish = props.item === "backsplash" ? d.finishes.backsplash : d.finishes.countertop;
  if (!finish) return null;
  return (
    <Sheet label={finish.name} onClose={props.onClose}>
      <img className="sheet-hero" src={finish.swatch_url} alt="" />
      <div className="caption">{t.items[props.item]}{layer ? ` ${layer.run_id}` : ""} · Kober {t.lines[finish.line]}</div>
      <h2 className="h2">{finish.name}</h2>
      {finish.code && <div className="small muted">{t.code} <span className="mono">{finish.code}</span></div>}
      {priceBlock}
      {props.item === "countertop" && (
        <button className="edge-link" onClick={props.onShowEdge}>
          <span><span className="tiny muted">{t.profile}</span><strong>{d.profile.name} ({d.profile.display})</strong></span>
          {(q.profile_options?.length || 0) > 0 && <span className="small">{t.changeEdge}<Icon.arrowRight size={14} /></span>}
        </button>
      )}
      <h3 className="caption list-title">{t.pieces}</h3>
      <QuoteLines quote={q} item={props.item} />
      <button className="btn btn-glass btn-block" onClick={() => go(`#/p/${d.project_id}/finishes/${d.photo_id}`)}>{t.changeFinish}</button>
    </Sheet>
  );
}

function BookingForm(props: { pid: string; did: string; range: string; visitFee?: MoneyJ; onClose: () => void }) {
  const { t, lang } = useLang();
  const [form, setForm] = useState({ name: "", phone: "", address: "", preferred_window: "", fulfilment_type: "MANAGED", notes: "" });
  const [done, setDone] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
    setForm({ ...form, [k]: e.target.value });
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setError(null); setSending(true);
    try { await api.book(props.pid, { ...form, design_id: props.did }); setDone(true); }
    catch (err: any) { setError(err.message); } finally { setSending(false); }
  };
  return (
    <Modal label={t.bookTitle} onClose={props.onClose} wide>
      {done ? (
        <div className="booked">
          <span className="booked-icon"><Icon.check size={28} /></span>
          <h2 className="h2" tabIndex={-1}>{t.booked}</h2>
          <p className="muted">{t.bookedSub}</p>
          <button type="button" className="btn btn-dark" onClick={props.onClose}>{t.close}</button>
        </div>
      ) : (
        <form onSubmit={submit}>
          <div className="modal-head">
            <div>
              <h2 className="h2" tabIndex={-1}>{t.bookTitle}</h2>
              <p className="small muted">{t.bookSub}</p>
            </div>
            <button type="button" className="icon-btn" aria-label={t.close} onClick={props.onClose}><Icon.close /></button>
          </div>
          <div className="form-grid">
            <label className="field"><span>{t.name}</span><input required value={form.name} onChange={set("name")} /></label>
            <label className="field"><span>{t.phone}</span><input required value={form.phone} onChange={set("phone")} inputMode="tel" /></label>
            <label className="field field-full"><span>{t.address}</span><textarea required value={form.address} onChange={set("address")} rows={2} /></label>
            <label className="field"><span>{t.when}</span><input value={form.preferred_window} onChange={set("preferred_window")} /></label>
            <label className="field"><span>{t.service}</span><select value={form.fulfilment_type} onChange={set("fulfilment_type")}>
              <option value="MANAGED">{t.managed}</option><option value="SELF">{t.self}</option></select></label>
            <label className="field field-full"><span>{t.notes}</span><textarea value={form.notes} onChange={set("notes")} rows={2} /></label>
          </div>
          <div className="booking-sum"><span className="small muted">{t.estimate}</span><strong>{props.range}</strong></div>
          <p className="small visit-note" data-service={form.fulfilment_type}>
            {form.fulfilment_type === "MANAGED" || !props.visitFee ? t.visitWithJob : t.visitMaterialsOnly(money(props.visitFee, lang))}
          </p>
          <p className="tiny muted">{t.noPayment}</p>
          <ErrorLine error={error} />
          <div className="row end">
            <button type="button" className="btn btn-ghost" onClick={props.onClose}>{t.close}</button>
            <button className="btn btn-dark" type="submit" disabled={sending}>{t.submitBooking}</button>
          </div>
        </form>
      )}
    </Modal>
  );
}
