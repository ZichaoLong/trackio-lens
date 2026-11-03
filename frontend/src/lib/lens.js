import { writable } from "svelte/store";

export const connection = writable({ username: "", needsSetup: false, lastUpdated: null, errors: [], updateAvailable: false });
export const frontendCommit = import.meta.env.VITE_LENS_COMMIT || "development";
let csrf = "";
let originalFetch;
let redirecting = false;
const failures = new Map();

export function acceptSession(session) {
  csrf = session.csrf;
  connection.update(value => ({ ...value, username: session.username, needsSetup: session.needs_setup }));
}

function signIn() {
  if (redirecting) return;
  redirecting = true;
  location.replace(`/__lens/login?next=${encodeURIComponent(location.pathname + location.search)}`);
}

export async function initializeLens() {
  originalFetch = window.fetch.bind(window);
  const response = await originalFetch("/__lens/session", { cache: "no-store" });
  if (response.status === 401) { signIn(); return false; }
  if (!response.ok) throw Error("Unable to check your session. Please refresh to retry.");
  const session = await response.json();
  acceptSession(session);
  window.fetch = async (input, init = {}) => {
    const url = new URL(input instanceof Request ? input.url : input, location.href);
    if (url.origin !== location.origin) return originalFetch(input, init);
    const method = (init.method || (input instanceof Request ? input.method : "GET")).toUpperCase();
    const headers = new Headers(init.headers || (input instanceof Request ? input.headers : {}));
    if (!["GET", "HEAD", "OPTIONS"].includes(method)) headers.set("X-Trackio-Lens-CSRF", csrf);
    const tracksData = url.pathname.startsWith("/api/");
    try {
      const result = await originalFetch(input, { ...init, headers });
      if (result.status === 401) signIn();
      if (tracksData) {
        if (!result.ok) failures.set(url.pathname, `Data request failed (${result.status}).`);
        else failures.delete(url.pathname);
        connection.update(value => ({ ...value, errors: [...failures.values()], lastUpdated: result.ok ? new Date() : value.lastUpdated }));
      }
      return result;
    } catch (error) {
      if (tracksData && error.name !== "AbortError") {
        failures.set(url.pathname, "Connection lost. Displayed data may be out of date.");
        connection.update(value => ({ ...value, errors: [...failures.values()] }));
      }
      throw error;
    }
  };
  const check = async () => {
    if (document.hidden) return;
    try {
      const result = await fetch("/__lens/build", { cache: "no-store" });
      if (result.ok) {
        const build = await result.json();
        connection.update(value => ({ ...value, updateAvailable: frontendCommit !== "development" && build.source_commit !== frontendCommit }));
      }
    } catch { /* Data requests display connection failures. */ }
  };
  await check();
  setInterval(check, 60000);
  window.addEventListener("pageshow", check);
  document.addEventListener("visibilitychange", check);
  return true;
}

export async function logout() {
  const response = await fetch("/__lens/logout", { method: "POST" });
  if (response.ok || response.status === 401) location.replace("/__lens/login");
  else throw Error("Sign out failed. Please retry.");
}
