import React, { createContext, useContext, useState } from "react";
import { strings, type Lang, type Strings } from "./i18n";

type LangCtx = { lang: Lang; t: Strings; setLang: (l: Lang) => void };
const Ctx = createContext<LangCtx>({ lang: "es", t: strings.es, setLang: () => {} });

export function LangProvider(props: { children: React.ReactNode }) {
  const initial = ((): Lang => {
    try { return (localStorage.getItem("renovai.lang") as Lang) || "es"; } catch { return "es"; }
  })();
  const [lang, setLangState] = useState<Lang>(initial);
  const setLang = (l: Lang) => {
    setLangState(l);
    try { localStorage.setItem("renovai.lang", l); } catch { /* private mode: fine */ }
    document.documentElement.lang = l;
  };
  return <Ctx.Provider value={{ lang, t: strings[lang], setLang }}>{props.children}</Ctx.Provider>;
}

export const useLang = () => useContext(Ctx);
