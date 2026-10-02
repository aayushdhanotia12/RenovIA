import type { MoneyJ } from "./api";
import type { Lang } from "./i18n";

// Display only. Amounts arrive as integer minor units from the server and are
// never added up or multiplied here.
export function money(m: MoneyJ, lang: Lang, decimals = false): string {
  return new Intl.NumberFormat(lang === "es" ? "es-MX" : "en-US", {
    style: "currency", currency: m.currency, currencyDisplay: "narrowSymbol",
    minimumFractionDigits: decimals ? 2 : 0, maximumFractionDigits: decimals ? 2 : 0,
  }).format(m.minor / 100);
}

export function moneyRange(low: MoneyJ, high: MoneyJ, lang: Lang, approx: string): string {
  const a = money(low, lang), b = money(high, lang);
  return a === b ? `${approx} ${a}` : `${a} – ${b} ${low.currency}`;
}

// Centimetres typed by the customer -> integer millimetres, or null if not a number.
export function cmToMm(text: string): number | null {
  const v = Number(String(text).replace(",", ".").trim());
  if (!Number.isFinite(v) || v <= 0) return null;
  return Math.round(v * 10);
}

export function mmToCm(mm: number): string {
  return (mm / 10).toFixed(mm % 10 === 0 ? 0 : 1);
}

export function signedMm(mm: number): string {
  const cm = mm / 10;
  return `${cm > 0 ? "+" : cm < 0 ? "−" : "±"}${Math.abs(cm).toFixed(Math.abs(mm) % 10 === 0 ? 0 : 1)} cm`;
}

export function dateTime(epochS: number | null | undefined, lang: Lang): string {
  if (!epochS) return "";
  return new Intl.DateTimeFormat(lang === "es" ? "es-MX" : "en-US", { dateStyle: "medium", timeStyle: "short" })
    .format(new Date(epochS * 1000));
}

export function localDateTime(value: string | null | undefined, lang: Lang): string {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return new Intl.DateTimeFormat(lang === "es" ? "es-MX" : "en-US", { weekday: "short", day: "numeric", month: "short",
    hour: "numeric", minute: "2-digit" }).format(d);
}

// wa.me opens WhatsApp on the phone, or WhatsApp Web, with the message typed in.
export function whatsappLink(text: string, number?: string | null): string {
  return `https://wa.me/${number || ""}?text=${encodeURIComponent(text)}`;
}

// "$17,800 – $29,200 MXN" -> ["$17,800 – $29,200", "MXN"], so the currency code can be set smaller.
export const splitCurrency = (s: string): [string, string] => {
  const m = s.match(/^(.*\S)\s([A-Z]{3})$/);
  return m ? [m[1], m[2]] : [s, ""];
};
