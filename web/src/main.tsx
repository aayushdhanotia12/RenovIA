import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { api } from "./api";
import { LangProvider, useLang } from "./lang";
import { Finishes, Home, Measure, Result, StyleBoard, Surfaces } from "./screens";
import { PrintQuote, SharedView } from "./share";
import { Staff, StaffPrint } from "./staff";
import { BrandMark, Icon, go } from "./ui";

type Route =
  | { screen: "home" } | { screen: "staff" }
  | { screen: "measure"; pid: string }
  | { screen: "surfaces" | "finishes" | "styles"; pid: string; photoId: string }
  | { screen: "result" | "print"; did: string }
  | { screen: "shared" | "shared-print"; sid: string }
  | { screen: "staff-print"; bid: string };

// Hash routes keep the server simple: every screen is served by the same index.html.
function parse(hash: string): Route {
  const [a, b, c, d] = hash.replace(/^#\/?/, "").split("?")[0].split("/").filter(Boolean);
  if (a === "p" && b) {
    if ((c === "surfaces" || c === "finishes" || c === "styles") && d) return { screen: c, pid: b, photoId: d };
    return { screen: "measure", pid: b };
  }
  if (a === "d" && b) return { screen: c === "print" ? "print" : "result", did: b };
  if (a === "s" && b) return { screen: c === "print" ? "shared-print" : "shared", sid: b };
  if (a === "staff" && b === "print" && c) return { screen: "staff-print", bid: c };
  if (a === "staff") return { screen: "staff" };
  return { screen: "home" };
}

const routeKey = (r: Route) => [r.screen, ...Object.entries(r).filter(([k]) => k !== "screen").map(([, v]) => v)].join("/");

// After a route change, move focus to the new screen's heading and name the tab after it
// (UI-SPEC 9.5). Screens load their data first, so wait briefly for the heading to appear.
// A language switch only renames the tab.
function useRouteFocus(key: string, lang: string) {
  const last = useRef(key);
  useEffect(() => {
    const moved = last.current !== key;
    last.current = key;
    let tries = 0;
    const id = window.setInterval(() => {
      const h1 = document.querySelector<HTMLElement>("main h1");
      if (!h1 && ++tries <= 30) return;
      window.clearInterval(id);
      if (!h1) return;
      document.title = `${h1.textContent} · RenovAI`;
      if (!moved) return;
      if (!h1.hasAttribute("tabindex")) h1.setAttribute("tabindex", "-1");
      h1.focus({ preventScroll: true });
    }, 100);
    return () => window.clearInterval(id);
  }, [key, lang]);
}

function Shell() {
  const { t, lang, setLang } = useLang();
  const [route, setRoute] = useState<Route>(parse(window.location.hash));
  const [scrolled, setScrolled] = useState(false);
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    const onHash = () => { setRoute(parse(window.location.hash)); window.scrollTo(0, 0); };
    const onScroll = () => setScrolled(window.scrollY > 8);
    window.addEventListener("hashchange", onHash);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => { window.removeEventListener("hashchange", onHash); window.removeEventListener("scroll", onScroll); };
  }, []);

  // The design review is always dark (UI-SPEC 2.4); every other screen is light.
  const dark = route.screen === "result" || route.screen === "shared";
  useEffect(() => {
    if (dark) document.documentElement.dataset.theme = "dark";
    else delete document.documentElement.dataset.theme;
  }, [dark]);
  useEffect(() => { document.documentElement.lang = lang; }, [lang]);
  const key = routeKey(route);
  useRouteFocus(key, lang);

  const home = route.screen === "home";
  const scrollTo = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  const start = async () => {
    if (starting) return;
    setStarting(true);
    try { go(`#/p/${(await api.createProject()).id}`); } catch { window.scrollTo({ top: 0, behavior: "smooth" }); }
    finally { setStarting(false); }
  };

  return (
    <>
      <a className="skip-link" href="#main" onClick={(e) => { e.preventDefault(); document.querySelector<HTMLElement>("main h1")?.focus(); }}>
        {lang === "es" ? "Ir al contenido" : "Skip to content"}
      </a>
      <header className={`topbar${scrolled ? " topbar-scrolled" : ""}`}>
        <div className="topbar-inner">
          <a href="#/" className="brand" aria-label="RenovAI">
            <BrandMark size={28} /><span>{t.app}</span>
          </a>
          {home && (
            <nav className="nav-links" aria-label={lang === "es" ? "Secciones" : "Sections"}>
              <button onClick={() => scrollTo("how")}>{t.nav.how}</button>
              <button onClick={() => scrollTo("styles")}>{t.nav.styles}</button>
              <button onClick={() => scrollTo("pricing")}>{t.nav.pricing}</button>
            </nav>
          )}
          <div className="topbar-actions">
            <button className="btn btn-ghost btn-sm lang-btn" onClick={() => setLang(lang === "es" ? "en" : "es")}
              aria-label={t.langName}>
              <Icon.globe size={16} />{t.langSwitch}
            </button>
            {home && <button className="btn btn-dark btn-sm" onClick={start} disabled={starting}>{t.start}</button>}
          </div>
        </div>
      </header>
      <main id="main">
        <div key={key} className="route">
          {route.screen === "home" && <Home />}
          {route.screen === "measure" && <Measure pid={route.pid} />}
          {route.screen === "surfaces" && <Surfaces pid={route.pid} photoId={route.photoId} />}
          {route.screen === "finishes" && <Finishes pid={route.pid} photoId={route.photoId} />}
          {route.screen === "styles" && <StyleBoard pid={route.pid} photoId={route.photoId} />}
          {route.screen === "result" && <Result did={route.did} />}
          {route.screen === "print" && <PrintQuote did={route.did} />}
          {route.screen === "shared" && <SharedView sid={route.sid} />}
          {route.screen === "shared-print" && <PrintQuote sid={route.sid} />}
          {route.screen === "staff" && <Staff />}
          {route.screen === "staff-print" && <StaffPrint bid={route.bid} />}
        </div>
      </main>
      <footer className="footer">
        <span className="footer-brand"><BrandMark size={18} />{t.app}</span>
        <span>{t.footer}</span>
      </footer>
    </>
  );
}

createRoot(document.getElementById("root")!).render(<LangProvider><Shell /></LangProvider>);
