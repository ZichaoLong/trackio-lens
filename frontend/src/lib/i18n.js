import { derived, writable } from "svelte/store";
import zh from "./zh.json";

export const languageKey = "trackio-lens-language";
function initialLanguage() {
  try {
    const saved = localStorage.getItem(languageKey);
    if (["zh-CN", "en"].includes(saved)) return saved;
  } catch { /* Browser storage is optional. */ }
  return typeof navigator !== "undefined" && navigator.language?.startsWith("zh") ? "zh-CN" : "en";
}
export const locale = writable(initialLanguage());
export function translate(language, message, params = {}) {
  const text = language === "zh-CN" ? (zh[message] ?? message) : message;
  return String(text ?? "").replace(/\{(\w+)\}/g, (match, key) => params[key] ?? match);
}
export const t = derived(locale, language => (message, params) => translate(language, message, params));
export function setLocale(language) {
  if (!["zh-CN", "en"].includes(language)) return;
  locale.set(language);
  try { localStorage.setItem(languageKey, language); } catch { /* Optional. */ }
}
locale.subscribe(language => {
  if (typeof document !== "undefined") document.documentElement.lang = language;
});
