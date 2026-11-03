import "./lib/gradio-theme.css";
import App from "./App.svelte";
import AccountSetup from "./components/AccountSetup.svelte";
import { get } from "svelte/store";
import RegistryApp from "./RegistryApp.svelte";
import { mount } from "svelte";
import { initializeLens, connection } from "./lib/lens.js";

const base = window.__trackio_base || "";
const relativePath = window.location.pathname.startsWith(base)
  ? window.location.pathname.slice(base.length)
  : window.location.pathname;
const pathname = relativePath.replace(/\/+$/, "");
const Root = pathname === "/registry" ? RegistryApp : App;
const app = initializeLens().then(ready => {
  if (ready) return mount(get(connection).needsSetup ? AccountSetup : Root, { target: document.getElementById("app") });
}).catch(error => {
  const target = document.getElementById("app");
  target.textContent = error.message;
  target.style.padding = "24px";
});

export default app;
