// The field team's view: visit requests with the customer's photo, render and quote; scheduling,
// notes, and the visit record that re-prices the design as a final quote.
import React, { useEffect, useMemo, useState } from "react";
import { api, type BookingStatus, type PriceInfo, type StaffBooking, type StaffDetail } from "./api";
import { QuoteLines, QuoteTotals } from "./components";
import { cmToMm, dateTime, localDateTime, mmToCm, money, moneyRange, signedMm, whatsappLink } from "./format";
import { useLang } from "./lang";
import { CmInput, Swatch } from "./screens";
import { PrintSheet } from "./share";
import { ErrorLine, Icon, Skeleton, Stepper, go } from "./ui";

const KEY = "renovai.staff";
const loadKey = () => { try { return sessionStorage.getItem(KEY) || ""; } catch { return ""; } };
const saveKey = (k: string) => { try { k ? sessionStorage.setItem(KEY, k) : sessionStorage.removeItem(KEY); } catch { /* ok */ } };
const STATUSES: BookingStatus[] = ["new", "scheduled", "visited", "cancelled"];

function StatusPill(props: { status: string }) {
  const { t } = useLang();
  return <span className={`status-pill status-${props.status}`}>{t.statusNames[props.status] || props.status}</span>;
}

function PriceStrip(props: { token: string; prices: PriceInfo; onImported: (p: PriceInfo) => void }) {
  const { t, lang } = useLang();
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "bad"; lines: string[] } | null>(null);
  useEffect(() => { api.staffPrices(props.token).then((r) => setUrl(r.sheet_url || "")).catch(() => {}); }, [props.token]);
  const p = props.prices;
  const run = async () => {
    setBusy(true); setMsg(null);
    try {
      const r = await api.staffImportPrices(props.token, url);
      props.onImported(r.prices);
      setMsg({ kind: "ok", lines: [t.imported, ...r.warnings] });
    } catch (e: any) { setMsg({ kind: "bad", lines: [e.lines ? t.sheetErrors : e.message, ...(e.lines || [])] }); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="price-strip">
        <span className="caption">{t.pricesLabel}</span>
        <span className={`status-pill status-${p.status === "LIVE" ? "live" : "draft"}`}>{t.priceStatus[p.status] || p.status}</span>
        <span className="tiny muted grow">{p.status === "PLACEHOLDER" ? "" : p.version}{p.imported_at ? ` · ${localDateTime(p.imported_at, lang)}` : ""}{p.owner ? ` · ${p.owner}` : ""}</span>
        <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder={t.sheetUrl} aria-label={t.sheetUrl} />
        <button className="btn btn-light btn-sm" onClick={run} disabled={busy || !url.trim()}>
          <Icon.refresh size={14} />{busy ? t.importing : t.importSheet}
        </button>
      </div>
      {msg && (
        <div className={`alert ${msg.kind === "ok" ? "alert-ok" : "alert-bad"} small`} role="status" style={{ marginTop: -8, marginBottom: 16 }}>
          <div>{msg.lines.slice(0, 1)}{msg.lines.length > 1 && <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
            {msg.lines.slice(1, 12).map((l, i) => <li key={i}>{l}</li>)}</ul>}</div>
        </div>
      )}
    </>
  );
}

export function Staff() {
  const { t, lang } = useLang();
  const [token, setToken] = useState(loadKey());
  const [typed, setTyped] = useState("");
  const [rows, setRows] = useState<StaffBooking[] | null>(null);
  const [prices, setPrices] = useState<PriceInfo | null>(null);
  const [filter, setFilter] = useState<BookingStatus | "all">("all");
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async (key = token) => {
    if (!key) return;
    try {
      const r = await api.staffBookings(key);
      setRows(r.bookings); setPrices(r.prices); setError(null); setToken(key); saveKey(key);
    } catch (e: any) {
      setError(e.message);
      if (e.status === 403) { setToken(""); saveKey(""); setRows(null); }
    }
  };
  useEffect(() => { if (token) load(token); }, []);
  const counts = useMemo(() => Object.fromEntries(STATUSES.map((s) => [s, (rows || []).filter((r) => r.status === s).length])), [rows]);

  if (!token || !rows) {
    return (
      <section className="flow">
        <h1 className="h1">{t.staffTitle}</h1>
        <p className="lead">{t.staffSub}</p>
        <form className="staff-key" onSubmit={(e) => { e.preventDefault(); load(typed.trim()); }}>
          <input type="password" placeholder={t.staffToken} aria-label={t.staffToken} value={typed} onChange={(e) => setTyped(e.target.value)}
            autoComplete="current-password" />
          <button className="btn btn-dark" type="submit">{t.load}</button>
        </form>
        <ErrorLine error={error} />
      </section>
    );
  }
  const shown = rows.filter((r) => filter === "all" || r.status === filter);
  const onChanged = (b: StaffBooking) => setRows((rs) => (rs || []).map((r) => (r.id === b.id ? b : r)));

  return (
    <section className="flow flow-wide">
      <div className="staff-head">
        <div>
          <h1 className="h1">{t.staffTitle}</h1>
          <p className="small muted">{t.staffSub}</p>
        </div>
        <div className="row">
          <button className="btn btn-ghost btn-sm" onClick={() => load()}><Icon.refresh size={14} />{t.refresh}</button>
          <button className="btn btn-ghost btn-sm" onClick={() => { saveKey(""); setToken(""); setRows(null); }}>{t.logout}</button>
        </div>
      </div>
      {prices && <PriceStrip token={token} prices={prices} onImported={setPrices} />}
      <div className="pill-tabs" role="tablist" style={{ marginBottom: 16 }}>
        <button role="tab" aria-selected={filter === "all"} className={filter === "all" ? "on" : ""} onClick={() => setFilter("all")}>
          {t.all} · {rows.length}</button>
        {STATUSES.map((s) => (
          <button key={s} role="tab" aria-selected={filter === s} className={filter === s ? "on" : ""} onClick={() => setFilter(s)}>
            {t.statusNames[s]} · {counts[s]}</button>
        ))}
      </div>
      <ErrorLine error={error} />
      <div className="staff-layout">
        <div>
          {shown.length === 0 ? <div className="visit-empty">{t.noRequests}</div> : (
            <ul className="visit-list">
              {shown.map((r) => (
                <li key={r.id}>
                  <button className={selected === r.id ? "on" : ""} onClick={() => {
                    setSelected(r.id);
                    window.setTimeout(() => document.getElementById("visit-detail")?.scrollIntoView({ behavior: "smooth", block: "start" }), 60);
                  }}>
                    {r.thumb_url ? <img className="visit-thumb" src={r.thumb_url} alt="" /> : <span className="visit-thumb" />}
                    <span className="visit-main">
                      <span className="row"><strong>{r.name}</strong><StatusPill status={r.status} /></span>
                      <span className="tiny muted">{r.countertop?.name || t.noDesign}{r.backsplash ? ` · ${r.backsplash.name}` : ""}</span>
                      <span className="tiny muted">{r.scheduled_at ? `${t.statusNames.scheduled}: ${localDateTime(r.scheduled_at, lang)}`
                        : `${t.requested} ${dateTime(r.created_at, lang)}`}</span>
                      <span className="tiny">{r.final_total ? `${t.finalQuote}: ${money(r.final_total, lang, true)}`
                        : r.estimate ? moneyRange(r.estimate.low, r.estimate.high, lang, t.approx) : ""}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div id="visit-detail">
          {selected ? <VisitDetail key={selected} token={token} bid={selected} onChanged={onChanged} />
            : <div className="visit-empty">{t.pickRequest}</div>}
        </div>
      </div>
    </section>
  );
}

type RunText = { run_id: string; length: string; size: string };

function VisitDetail(props: { token: string; bid: string; onChanged: (b: StaffBooking) => void }) {
  const { t, lang } = useLang();
  const [d, setD] = useState<StaffDetail | null>(null);
  const [plan, setPlan] = useState({ scheduled_at: "", assigned_to: "", staff_notes: "" });
  const [savedAt, setSavedAt] = useState(0);
  const [tops, setTops] = useState<RunText[]>([]);
  const [splashes, setSplashes] = useState<RunText[]>([]);
  const [sinks, setSinks] = useState(0);
  const [tool, setTool] = useState("laser");
  const [measuredBy, setMeasuredBy] = useState("");
  const [visitNotes, setVisitNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [showLines, setShowLines] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const apply = (x: StaffDetail) => {
    setD(x);
    props.onChanged(x.booking);
    setPlan({ scheduled_at: x.booking.scheduled_at || "", assigned_to: x.booking.assigned_to || "", staff_notes: x.booking.staff_notes || "" });
    const src = x.verified || x.measurements;
    if (src) {
      setTops(src.countertop_runs.map((r) => ({ run_id: r.run_id, length: mmToCm(r.length_mm), size: mmToCm(r.depth_mm) })));
      setSplashes(x.design?.choice.splash_finish_id ? src.splash_runs.map((r) => ({ run_id: r.run_id, length: mmToCm(r.length_mm), size: mmToCm(r.height_mm) })) : []);
      setSinks(src.sinks);
    }
    if (x.verified) { setTool(x.verified.tool || "laser"); setMeasuredBy(x.verified.measured_by || ""); setVisitNotes(x.verified.notes || ""); }
  };
  useEffect(() => { api.staffBooking(props.token, props.bid).then(apply).catch((e) => setError(e.message)); }, [props.bid]);
  if (error && !d) return <ErrorLine error={error} />;
  if (!d) return <Skeleton height={480} />;
  const b = d.booking;

  const save = async (extra: Partial<{ status: BookingStatus }> = {}) => {
    setError(null);
    try {
      apply(await api.staffUpdate(props.token, b.id, { ...plan, scheduled_at: plan.scheduled_at || null,
        assigned_to: plan.assigned_to || null, staff_notes: plan.staff_notes || null, ...extra }));
      setSavedAt(Date.now());
    } catch (e: any) { setError(e.message); }
  };
  const recordVisit = async (e: React.FormEvent) => {
    e.preventDefault(); setError(null);
    const toRuns = (rows: RunText[], key: "depth_mm" | "height_mm", fallback: number) => rows.map((r) => ({
      run_id: r.run_id, length_mm: cmToMm(r.length) ?? 0, [key]: cmToMm(r.size) ?? fallback }));
    const countertop_runs = toRuns(tops, "depth_mm", 645) as any;
    const splash_runs = toRuns(splashes.filter((s) => s.length.trim()), "height_mm", 600) as any;
    if (countertop_runs.some((r: any) => !r.length_mm)) { setError(t.needRun); return; }
    setBusy(true);
    try {
      apply(await api.staffVisit(props.token, b.id, { countertop_runs, splash_runs, sinks, tool,
        measured_by: measuredBy || null, notes: visitNotes || null, language: lang }));
      setShowLines(true);
    } catch (err: any) { setError(err.message); } finally { setBusy(false); }
  };

  const whenText = plan.scheduled_at ? localDateTime(plan.scheduled_at, lang) : "";
  const firstName = b.name.split(" ")[0];
  const fq = d.final_quote;
  const v = d.verified;
  return (
    <div className="visit-detail">
      <div className="card">
        <div className="detail-head">
          <div>
            <h2 className="h2">{b.name}</h2>
            <div className="small muted">{b.address}</div>
          </div>
          <StatusPill status={b.status} />
        </div>
        <div className="contact-actions">
          <a className="btn btn-light btn-sm" href={`tel:${b.phone.replace(/[^\d+]/g, "")}`}><Icon.phone size={14} />{t.call} · {b.phone}</a>
          {b.whatsapp && <a className="btn btn-whatsapp btn-sm" target="_blank" rel="noopener noreferrer"
            href={whatsappLink(t.waVisit(firstName, whenText), b.whatsapp)}><Icon.chat size={14} />{t.whatsapp}</a>}
          <a className="btn btn-light btn-sm" target="_blank" rel="noopener noreferrer"
            href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(b.address)}`}><Icon.pin size={14} />{t.map}</a>
        </div>
        <dl className="kv">
          <dt>{t.requested}</dt><dd>{dateTime(b.created_at, lang)}</dd>
          {b.preferred_window && <><dt>{t.preferred}</dt><dd>{b.preferred_window}</dd></>}
          <dt>{t.service}</dt><dd>{b.fulfilment_type === "SELF" ? t.self : t.managed}</dd>
          {b.estimate && <><dt>{t.estimateShown}</dt><dd>{moneyRange(b.estimate.low, b.estimate.high, lang, t.approx)}</dd></>}
          {b.notes && <><dt>{t.notes}</dt><dd>{b.notes}</dd></>}
        </dl>
        {d.design ? (
          <>
            <div className="photo-pair">
              <figure><img src={d.design.manifest.before_url} alt="" /><figcaption className="tiny muted">{t.photo}</figcaption></figure>
              <figure><img src={d.design.manifest.image.url} alt="" /><figcaption className="tiny muted">{t.design}</figcaption></figure>
            </div>
            <ul className="design-rows">
              {[{ l: t.countertop, f: d.design.finishes.countertop, x: `${t.profile}: ${d.design.profile.name}` },
                ...(d.design.finishes.backsplash ? [{ l: t.backsplash, f: d.design.finishes.backsplash, x: "Spläsh" }] : [])].map((r) => (
                <li key={r.l}><button type="button" tabIndex={-1}>
                  <Swatch finish={r.f} size={44} />
                  <span className="grow"><span className="tiny muted">{r.l}</span><strong>{r.f.name}</strong>
                    <span className="tiny muted">{r.f.code ? `${t.code} ${r.f.code} · ` : ""}{r.x}</span></span>
                </button></li>
              ))}
            </ul>
          </>
        ) : <p className="small muted">{t.noDesign}</p>}
      </div>

      <div className="card">
        <h3 className="h3">{t.plan}</h3>
        <div className="form-grid">
          <label className="field"><span>{t.scheduledAt}</span>
            <input type="datetime-local" value={plan.scheduled_at} onChange={(e) => setPlan({ ...plan, scheduled_at: e.target.value })} /></label>
          <label className="field"><span>{t.assignedTo}</span>
            <input value={plan.assigned_to} onChange={(e) => setPlan({ ...plan, assigned_to: e.target.value })} /></label>
          <label className="field field-full"><span>{t.staffNotes}</span>
            <textarea rows={2} value={plan.staff_notes} onChange={(e) => setPlan({ ...plan, staff_notes: e.target.value })} /></label>
        </div>
        <div className="row wrap">
          <button className="btn btn-dark btn-sm" onClick={() => save(b.status === "new" && plan.scheduled_at ? { status: "scheduled" } : {})}>
            {Date.now() - savedAt < 2500 ? <><Icon.check size={14} />{t.saved}</> : t.save}</button>
          <span className="tiny muted">{t.markAs}</span>
          <div className="status-buttons">
            {STATUSES.filter((s) => s !== b.status).map((s) => (
              <button key={s} className="chip" onClick={() => save({ status: s })}>{t.statusNames[s]}</button>
            ))}
          </div>
        </div>
      </div>

      {d.design && (
        <form className="card" onSubmit={recordVisit}>
          <h3 className="h3">{t.visitTitle}</h3>
          <p className="small muted">{t.visitSub}</p>
          <div className="visit-runs">
            {tops.map((r, i) => {
              const typed = d.measurements?.countertop_runs.find((x) => x.run_id === r.run_id);
              return (
                <div key={r.run_id} className="visit-run">
                  <div className="run-name"><span className="dot dot-top" />{t.countertop} {r.run_id}</div>
                  <CmInput label={t.length} value={r.length} onChange={(val) => setTops(tops.map((x, j) => j === i ? { ...x, length: val } : x))} />
                  <CmInput label={t.depth} value={r.size} onChange={(val) => setTops(tops.map((x, j) => j === i ? { ...x, size: val } : x))} />
                  {typed && <span className="tiny muted">{t.customerTyped}: {mmToCm(typed.length_mm)} × {mmToCm(typed.depth_mm)} cm</span>}
                </div>
              );
            })}
            {splashes.map((r, i) => {
              const typed = d.measurements?.splash_runs.find((x) => x.run_id === r.run_id);
              return (
                <div key={r.run_id} className="visit-run">
                  <div className="run-name"><span className="dot dot-splash" />{t.backsplash} {r.run_id}</div>
                  <CmInput label={t.length} value={r.length} onChange={(val) => setSplashes(splashes.map((x, j) => j === i ? { ...x, length: val } : x))} />
                  <CmInput label={t.height} value={r.size} onChange={(val) => setSplashes(splashes.map((x, j) => j === i ? { ...x, size: val } : x))} />
                  {typed && <span className="tiny muted">{t.customerTyped}: {mmToCm(typed.length_mm)} × {mmToCm(typed.height_mm)} cm</span>}
                </div>
              );
            })}
          </div>
          <div className="form-grid">
            <div className="sinks-row field-full" style={{ marginTop: 0 }}><span>{t.sinks}</span>
              <Stepper value={sinks} min={0} max={4} onChange={setSinks} label={t.sinks} /></div>
            <label className="field"><span>{t.tool}</span>
              <select value={tool} onChange={(e) => setTool(e.target.value)}>
                {Object.entries(t.tools).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
              </select></label>
            <label className="field"><span>{t.measuredBy}</span><input value={measuredBy} onChange={(e) => setMeasuredBy(e.target.value)} /></label>
            <label className="field field-full"><span>{t.notes}</span><textarea rows={2} value={visitNotes} onChange={(e) => setVisitNotes(e.target.value)} /></label>
          </div>
          <ErrorLine error={error} />
          <button className="btn btn-dark" type="submit" disabled={busy}>{t.saveVisit}</button>
        </form>
      )}

      {fq && v && (
        <div className="card">
          <h3 className="h3">{t.finalQuote}</h3>
          <div className="final-figure">
            <span className="small muted">{t.printFinal}</span>
            <span className="numeral">{money(fq.total, lang, true)}</span>
          </div>
          <p className={`alert ${v.within_range ? "alert-ok" : "alert-warn"} small`}>
            {v.within_range ? t.withinRange : t.outsideRange(money({ minor: Math.abs(v.vs_estimate_minor), currency: fq.currency }, lang))}</p>
          <h4 className="caption">{t.differences}</h4>
          <table className="lines delta-table">
            <thead><tr><th></th><th className="num">{t.customerTyped}</th><th className="num">{t.teamMeasured}</th><th className="num">{t.diff}</th></tr></thead>
            <tbody>
              {[...v.differences.countertop.map((x) => ({ ...x, label: `${t.countertop} ${x.run_id}` })),
                ...v.differences.backsplash.map((x) => ({ ...x, label: `${t.backsplash} ${x.run_id}` }))].map((x) => (
                <tr key={x.label}>
                  <td>{x.label}</td>
                  <td className="num">{x.customer_mm != null ? `${mmToCm(x.customer_mm)} cm` : "—"}</td>
                  <td className="num">{mmToCm(x.team_mm)} cm</td>
                  <td className={`num ${x.diff_mm && Math.abs(x.diff_bp || 0) > 300 ? "delta-up" : "delta-ok"}`}>
                    {x.diff_mm != null ? `${signedMm(x.diff_mm)} (${((x.diff_bp || 0) / 100).toFixed(1)}%)` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="row wrap">
            <button className="btn btn-light btn-sm" onClick={() => setShowLines(!showLines)}><Icon.receipt size={14} />{t.pieces}</button>
            <button className="btn btn-light btn-sm" onClick={() => go(`#/staff/print/${b.id}`)}><Icon.printer size={14} />{t.printFinalQuote}</button>
            {b.whatsapp && <a className="btn btn-whatsapp btn-sm" target="_blank" rel="noopener noreferrer"
              href={whatsappLink(t.waFinal(firstName, money(fq.total, lang, true)), b.whatsapp)}><Icon.chat size={14} />{t.sendFinal}</a>}
          </div>
          {showLines && (
            <div className="quote-full">
              <QuoteLines quote={fq} group="materials" />
              <QuoteLines quote={fq} group="labour" />
              <QuoteTotals quote={fq} full />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function StaffPrint(props: { bid: string }) {
  const { t } = useLang();
  const [d, setD] = useState<StaffDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const key = loadKey();
    if (!key) { go("#/staff"); return; }
    api.staffBooking(key, props.bid).then(setD).catch((e) => setError(e.message));
  }, [props.bid]);
  if (error) return <div className="flow"><ErrorLine error={error} /></div>;
  return (
    <section className="print-page">
      <div className="print-toolbar">
        <button className="link-back" onClick={() => go("#/staff")}><Icon.back size={18} />{t.staffTitle}</button>
        <button className="btn btn-dark" onClick={() => window.print()} disabled={!d}><Icon.printer size={16} />{t.printNow}</button>
      </div>
      <h1 className="sr-only">{t.printTitle}</h1>
      {d?.design ? <PrintSheet design={d.design} quote={d.final_quote || d.design.quote} reference={d.booking.id}
        customer={{ name: d.booking.name, address: d.booking.address }} /> : <Skeleton height={900} />}
    </section>
  );
}
