<script>
  import { onMount } from "svelte";
  import { t } from "../lib/i18n.js";
  import { frontendCommit } from "../lib/lens.js";
  let state = $state(null);
  let repository = $state("");
  let password = $state("");
  let busy = $state(false);
  let loading = false;
  let error = $state("");
  const terminal = new Set(["complete", "failed", "interrupted", "recovered"]);
  let running = $derived(state?.operation && !terminal.has(state.operation.phase));
  const phases = { starting: "Starting update", fetching: "Fetching selected commit", building: "Building and testing", validating: "Validating data compatibility", backing_up: "Backing up data", switching: "Restarting and verifying", complete: "Update verified", failed: "Update failed", interrupted: "Update needs recovery", recovering: "Verifying recovery", recovered: "Recovery verified" };
  async function poll() {
    if (loading || busy || document.hidden) return;
    loading = true;
    try {
      const response = await fetch("/__lens/updates", {cache: "no-store"});
      if (!response.ok) throw Error();
      state = await response.json();
      if (!repository) repository = state.repository || "";
      if (error === "Cannot read update status. Retrying…") error = "";
    } catch { error = "Cannot read update status. Retrying…"; }
    finally { loading = false; }
  }
  onMount(() => { poll(); const timer = setInterval(poll, 3000); return () => clearInterval(timer); });
  async function action(name, values = {}) {
    busy = true; error = "";
    try {
      const response = await fetch(`/__lens/updates/${name}`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(values)});
      const data = await response.json();
      if (!response.ok) throw Error(data.error);
      state = data;
      if (name === "repository") password = "";
    } catch (e) { error = e.message || "Update service is unavailable. Retry or inspect local status."; }
    finally { busy = false; }
  }
</script>

<section class="updates" aria-label={$t("Application updates")}>
  <h3>{$t("Application updates")}</h3>
  {#if state?.available}
    <p>{$t("Updates run independently of this page and preserve normal login sessions.")}</p>
    <p class="identity">{$t("Running frontend")}: <code>{frontendCommit.slice(0, 12)}</code> · {$t("Backend")}: <code>{state.installed_build?.backend_version || "—"}</code></p>
    <p class="identity">{state.repository} · <code>main</code></p>
    <div class="actions">
      <button disabled={busy || running || state.operation?.phase === "interrupted"} onclick={() => action("check")}>{$t(busy ? "Working…" : "Check main for updates")}</button>
      {#if state.checked}
        {#if state.checked.commit === frontendCommit}
          <span>{$t("This page is on the checked commit.")}</span>
        {:else}
          <button disabled={busy || running || state.operation?.phase === "interrupted"} onclick={() => action("apply", {commit: state.checked.commit})}>{$t("Install selected commit")} <code>{state.checked.commit.slice(0, 12)}</code></button>
        {/if}
      {/if}
    </div>
    {#if state.checked}<p class="identity">{$t("Checked commit")}: <code>{state.checked.commit}</code></p>{/if}
    {#if state.operation}
      <div role="status" class="progress">
        <strong>{$t(phases[state.operation.phase] || state.operation.phase)}</strong>
        <span> · <code>{state.operation.commit.slice(0,12)}</code></span>
        {#if state.operation.message}<p>{$t(state.operation.message)}</p>{/if}
        {#if state.operation.phase === "interrupted"}
          <button disabled={busy} onclick={() => action("recover")}>{$t("Recover and verify")}</button>
        {/if}
        {#if state.operation.result?.source_commit && state.operation.result.source_commit !== frontendCommit}
          <button onclick={() => location.reload()}>{$t("Refresh to load the verified build")}</button>
        {/if}
      </div>
    {/if}
    <details>
      <summary>{$t("Update repository")}</summary>
      <p>{$t("Updates execute code from this repository. Change it only to a source you trust.")}</p>
      <form onsubmit={event => {event.preventDefault(); action("repository", {repository, current_password: password});}}>
        <label>{$t("Git repository")}<input type="text" bind:value={repository} required spellcheck="false" /></label>
        <label>{$t("Current password")}<input type="password" bind:value={password} autocomplete="current-password" required /></label>
        <button disabled={busy || running || state.operation?.phase === "interrupted"}>{$t("Save repository")}</button>
      </form>
    </details>
  {:else if state}
    <p>{$t("Managed installation is required")}</p>
  {:else}<p>{$t("Loading…")}</p>{/if}
  {#if error}<p role="alert">{$t(error)}</p>{/if}
</section>

<style>
  .updates{border:1px solid var(--border-color-primary,#ddd);border-radius:10px;padding:20px;margin-bottom:24px;max-width:760px;overflow-wrap:anywhere}
  h3{margin:0 0 10px}p{font-size:14px;line-height:1.6;color:var(--body-text-color-subdued,#666)}
  .identity{font-size:12px}code{font-family:ui-monospace,monospace}.actions{display:flex;align-items:center;flex-wrap:wrap;gap:12px}
  button,input{font:inherit;border:1px solid var(--border-color-primary,#bbb);border-radius:6px;background:var(--background-fill-primary,#fff);color:var(--body-text-color,#222);padding:9px 12px;min-width:0}
  button{cursor:pointer}button:disabled{opacity:.5}.progress{padding:14px 0;font-size:14px}details{margin-top:18px}summary{cursor:pointer}
  form{display:grid;gap:12px}label{display:grid;gap:6px;font-size:14px}[role="alert"]{color:#b42318}@media(max-width:600px){.updates{padding:14px}}
</style>
