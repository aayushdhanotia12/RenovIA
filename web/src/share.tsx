// Sharing a design on WhatsApp, the read-only shared view, and the printable quote.
import React, { useEffect, useState } from "react";
import { api, type Design, type Finish, type Profile, type Quote, type SharedDesign } from "./api";
import { CompareCanvas, ItemRows, QuoteLines, QuoteTotals, designLayers, designPins } from "./components";
import { money, moneyRange, splitCurrency, whatsappLink } from "./format";
import { useLang } from "./lang";
import { BrandMark, ErrorLine, Icon, Modal, Skeleton, go } from "./ui";

type Printable = { id: string; manifest: Design["manifest"]; quote: Quote; profile: Profile;
  finishes: { countertop: Finish; backsplash: Finish | null }; created_at?: number };

// ----------------------------------------------------------------- share dialog
export function ShareDialog(props: { design: Design; range: string; onClose: () => void }) {
  const { t } = useLang();
  const [url, setUrl] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.shareDesign(props.design.id).then((r) => setUrl(r.url)).catch((e) => setError(e.message)); }, [props.design.id]);
  const message = url ? t.shareMessage(props.design.finishes.countertop.name, props.range, url) : "";
  const copy = async () => {
    if (!url) return;
    try { await navigator.clipboard.writeText(url); setCopied(true); window.setTimeout(() => setCopied(false), 2500); }
    catch { (document.getElementById("share-url") as HTMLInputElement | null)?.select(); }
  };
  const native = typeof navigator !== "undefined" && "share" in navigator;
  return (
    <Modal label={t.shareTitle} onClose={props.onClose}>
      <div className="modal-head">
        <div>
          <h2 className="h2" tabIndex={-1}>{t.shareTitle}</h2>
          <p className="small muted">{t.shareSub}</p>
        </div>
        <button type="button" className="icon-btn" aria-label={t.close} onClick={props.onClose}><Icon.close /></button>
      </div>
      <div className="share-preview">
        <img src={props.design.manifest.image.url} alt="" />
        <div>
          <strong>{props.design.finishes.countertop.name}{props.design.finishes.backsplash ? ` · ${props.design.finishes.backsplash.name}` : ""}</strong>
          <div className="small muted">{props.range}</div>
        </div>
      </div>
      <ErrorLine error={error} />
      <div className="share-actions">
        <a className={`btn btn-whatsapp btn-lg${url ? "" : " disabled"}`} href={url ? whatsappLink(message) : undefined}
          target="_blank" rel="noopener noreferrer" aria-disabled={!url} data-share="whatsapp">
          <Icon.chat size={18} />{url ? t.sendWhatsapp : t.making}
        </a>
        <div className="share-link">
          <input id="share-url" readOnly value={url || ""} aria-label={t.copyLink} onFocus={(e) => e.target.select()} />
          <button className="btn btn-light" onClick={copy} disabled={!url}><Icon.copy size={16} />{copied ? t.copied : t.copyLink}</button>
        </div>
        {native && url && (
          <button className="btn btn-ghost" onClick={() => navigator.share({ title: t.shareTitle, text: message, url }).catch(() => {})}>
            <Icon.share size={16} />{t.share}…
          </button>
        )}
        <button className="btn btn-ghost" onClick={() => go(`#/d/${props.design.id}/print`)}><Icon.printer size={16} />{t.print}</button>
      </div>
    </Modal>
  );
}

// --------------------------------------------------------------- printable sheet
export function PrintSheet(props: { design: Printable; quote?: Quote; customer?: { name: string; address: string };
  reference?: string }) {
  const { t, lang } = useLang();
  const d = props.design;
  const q = props.quote || d.quote;
  const final = !q.estimate_only;
  const today = new Intl.DateTimeFormat(lang === "es" ? "es-MX" : "en-US", { dateStyle: "long" }).format(new Date());
  const finishes = [
    { label: t.countertop, f: d.finishes.countertop, extra: `${t.profile}: ${d.profile.name} (${d.profile.display})` },
    ...(d.finishes.backsplash ? [{ label: t.backsplash, f: d.finishes.backsplash, extra: "Spläsh" }] : []),
  ];
  return (
    <article className="print-sheet">
      <header className="print-brand">
        <span className="brand"><BrandMark size={28} /><span>RenovAI</span></span>
        <div className="print-meta">
          <div><strong>{final ? t.finalQuote : t.printFor}</strong></div>
          <div>{t.printDate}: {today}</div>
          <div>{t.printRef}: <span className="mono">{(props.reference || d.id).slice(-10).toUpperCase()}</span></div>
          {props.customer && <div>{props.customer.name}<br />{props.customer.address}</div>}
        </div>
      </header>
      <h1 className="print-title">{t.resultTitle(d.finishes.countertop.name)}</h1>
      <div className="print-images">
        <figure><img src={d.manifest.image.url} alt="" /><figcaption>{t.rendered}</figcaption></figure>
        <figure><img src={d.manifest.before_url} alt="" /><figcaption>{t.photo}</figcaption></figure>
      </div>
      <div className="print-finishes">
        {finishes.map(({ label, f, extra }) => (
          <div key={label} className="print-finish">
            <img src={f.swatch_url} alt="" />
            <div>
              <div className="caption">{label} · Kober {t.lines[f.line]}</div>
              <strong>{f.name}</strong>
              <div className="tiny muted">{f.code ? `${t.code} ${f.code} · ` : ""}{extra}</div>
            </div>
          </div>
        ))}
      </div>
      <div className="print-range">
        <span className="small muted">{final ? t.printFinal : t.printRange}</span>
        <span className="numeral">{final ? money(q.total, lang, true) : moneyRange(q.estimate.low, q.estimate.high, lang, t.approx)}</span>
      </div>
      <section>
        <h2 className="caption">{t.materials}</h2>
        <QuoteLines quote={q} group="materials" unitPrices />
        <h2 className="caption" style={{ marginTop: 14 }}>{t.labour}</h2>
        <QuoteLines quote={q} group="labour" unitPrices />
        <QuoteTotals quote={q} full />
      </section>
      <footer className="print-foot">
        <div>{final ? t.printFinalNote : t.printValidity}</div>
        {q.assumptions.length > 0 && <ul>{q.assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul>}
      </footer>
    </article>
  );
}

export function PrintQuote(props: { did?: string; sid?: string }) {
  const { t } = useLang();
  const [design, setDesign] = useState<Printable | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    (props.sid ? api.shared(props.sid) : api.getDesign(props.did!)).then(setDesign).catch((e) => setError(e.message));
  }, [props.did, props.sid]);
  const back = () => go(props.sid ? `#/s/${props.sid}` : `#/d/${props.did}`);
  if (error) return <div className="flow"><ErrorLine error={error} /></div>;
  return (
    <section className="print-page">
      <div className="print-toolbar">
        <button className="link-back" onClick={back}><Icon.back size={18} />{t.backToDesign}</button>
        <button className="btn btn-dark" onClick={() => window.print()} disabled={!design}><Icon.printer size={16} />{t.printNow}</button>
      </div>
      <h1 className="sr-only">{t.printTitle}</h1>
      {design ? <PrintSheet design={design} /> : <Skeleton height={900} />}
    </section>
  );
}

// ----------------------------------------------------------------- shared view
export function SharedView(props: { sid: string }) {
  const { t, lang } = useLang();
  const [design, setDesign] = useState<SharedDesign | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [compare, setCompare] = useState(true);
  const [showQuote, setShowQuote] = useState(false);
  useEffect(() => { api.shared(props.sid).then(setDesign).catch((e) => setError(e.status === 404 ? t.sharedNotFound : e.message)); }, [props.sid]);
  if (error) return <div className="flow"><h1 className="h1">{t.sharedTitle}</h1><ErrorLine error={error} />
    <button className="btn btn-dark" style={{ marginTop: 16 }} onClick={() => go("#/")}>{t.designYours}</button></div>;
  if (!design) return <div className="review"><Skeleton height={520} radius={24} /></div>;
  const q = design.quote;
  const layers = designLayers(design, t);
  const pins = designPins(design, t, lang);
  const [rangeMain, rangeCur] = splitCurrency(moneyRange(q.estimate.low, q.estimate.high, lang, t.approx));
  return (
    <section className="review" data-route="shared-design">
      <div className="review-head">
        <div>
          <span className="caption">{t.sharedTitle}</span>
          <h1 className="h1">{t.resultTitle(design.finishes.countertop.name)}</h1>
          <p className="small muted">{t.sharedSub}</p>
        </div>
      </div>
      <div className="review-grid">
        <div className="review-canvas">
          <CompareCanvas before={design.manifest.before_url} after={design.manifest.image.url}
            width={design.manifest.image.width} height={design.manifest.image.height} layers={layers} pins={pins}
            selected={selected} onSelect={setSelected} alt={t.resultTitle(design.finishes.countertop.name)} compare={compare} startAt={50} />
          <div className="canvas-toolbar">
            <button className={`btn btn-glass btn-sm${compare ? " on" : ""}`} onClick={() => setCompare(!compare)} aria-pressed={compare}>
              <Icon.compare size={16} />{t.compare}
            </button>
            <span className="muted small">{compare ? t.demoDrag : t.tapHint}</span>
          </div>
        </div>
        <aside className="review-side">
          <div className="card quote-card">
            <div className="badges"><span className="badge">{t.estimate}</span></div>
            <div className="numeral">{rangeMain}{rangeCur && <span className="numeral-cur">{rangeCur}</span>}</div>
            <ItemRows design={design} pins={pins} selected={selected} onSelect={(id) => { setCompare(false); setSelected(id); }} />
            <button className="btn btn-accent btn-lg btn-block" onClick={() => go("#/")}><Icon.sparkle size={18} />{t.designYours}</button>
            <div className="quote-actions">
              <button className="btn btn-glass" onClick={() => setShowQuote(!showQuote)} aria-expanded={showQuote}><Icon.receipt size={16} />{t.pieces}</button>
              <button className="btn btn-glass" onClick={() => go(`#/s/${props.sid}/print`)}><Icon.printer size={16} />{t.print}</button>
            </div>
            {showQuote && (
              <div className="quote-full">
                <QuoteLines quote={q} group="materials" />
                <QuoteLines quote={q} group="labour" />
                <QuoteTotals quote={q} />
              </div>
            )}
          </div>
        </aside>
      </div>
    </section>
  );
}
