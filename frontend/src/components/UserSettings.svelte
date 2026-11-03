<script>
  import { onMount } from "svelte";
  import { t } from "../lib/i18n.js";
  let users = $state([]);
  let username = $state("");
  let password = $state("");
  let resetPassword = $state("");
  let selected = $state("");
  let current = $state("");
  let busy = $state(false);
  let error = $state("");
  let message = $state("");
  async function load() {
    const response = await fetch("/__lens/users");
    const data = await response.json();
    if (!response.ok) throw Error(data.error);
    users = data.users;
  }
  onMount(() => { load().catch(e => { error = e.message; }); });
  async function change(values) {
    if (busy) return;
    error = ""; message = "";
    if (!current) { error = "Enter your current password"; return; }
    busy = true;
    try {
      const response = await fetch("/__lens/users", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({...values, current_password: current})});
      const data = await response.json();
      if (!response.ok) throw Error(data.error);
      await load();
      username = ""; password = ""; resetPassword = ""; selected = "";
      message = values.action === "delete" ? "Viewer deleted. Their sessions have been revoked." : values.action === "create" || values.action === "reset-password" ? "Account saved. Share the temporary password privately; the viewer must change it at first sign-in." : "Account access updated. Previous sessions have been revoked.";
    } catch (e) { error = e.message; }
    finally { busy = false; current = ""; }
  }
  function resetViewer(user) {
    selected = user.user_id; resetPassword = ""; error = ""; message = "";
  }
  function deleteViewer(user) {
    error = ""; message = "";
    if (!current) { error = "Enter your current password"; return; }
    if (window.confirm($t("Delete viewer {username}? Their sessions will end. Experiment data will be kept.", {username: user.username}))) {
      change({action: "delete", user_id: user.user_id});
    }
  }
</script>

<section class="users" aria-label={$t("User management")}>
  <h3>{$t("User management")}</h3>
  <p>{$t("Viewers can read all experiments and change their own password. Only the administrator manages accounts and updates.")}</p>
  <label>{$t("Administrator current password")}<input type="password" bind:value={current} autocomplete="current-password" /></label>
  {#if error}<p class="error" role="alert">{$t(error)}</p>{/if}
  {#if message}<p role="status">{$t(message)}</p>{/if}
  <ul>
    {#each users as user (user.user_id)}
      <li>
        <div class="user-row">
          <span><strong>{user.username}</strong> · {$t(user.role === "admin" ? "Administrator" : "Viewer")} · {$t(user.enabled ? "Enabled" : "Disabled")}</span>
          {#if user.role === "viewer"}
            <div class="user-actions">
              <button disabled={busy} onclick={() => resetViewer(user)}>{$t("Reset password")}</button>
              <button disabled={busy} onclick={() => change({action: "set-enabled", user_id: user.user_id, enabled: !user.enabled})}>{$t(user.enabled ? "Disable account" : "Enable account")}</button>
              <button class="delete" disabled={busy} onclick={() => deleteViewer(user)}>{$t("Delete account")}</button>
            </div>
          {/if}
        </div>
        {#if user.role === "viewer" && selected === user.user_id}
          <form onsubmit={event => {event.preventDefault(); change({action: "reset-password", user_id: user.user_id, password: resetPassword});}}>
            <h4>{$t("Reset password for {username}", {username: user.username})}</h4>
            <label>{$t("New temporary password")}<input type="password" bind:value={resetPassword} autocomplete="new-password" required minlength="14" maxlength="256" /></label>
            <div class="user-actions">
              <button disabled={busy}>{$t("Reset viewer password")}</button>
              <button type="button" disabled={busy} onclick={() => {selected = ""; resetPassword = "";}}>{$t("Cancel")}</button>
            </div>
          </form>
        {/if}
      </li>
    {/each}
  </ul>
  <form onsubmit={event => {event.preventDefault(); change({action: "create", username, password});}}>
    <h4>{$t("Create viewer")}</h4>
    <label>{$t("New username")}<input bind:value={username} autocomplete="off" required maxlength="80" /></label>
    <label>{$t("Temporary password")}<input type="password" bind:value={password} autocomplete="new-password" required minlength="14" maxlength="256" /></label>
    <button disabled={busy}>{$t("Create viewer")}</button>
  </form>
</section>

<style>
  .users{border:1px solid var(--border-color-primary,#ddd);border-radius:10px;padding:20px;margin-bottom:24px;max-width:760px}
  h3{margin:0 0 10px}h4{margin:0;grid-column:1/-1}p{font-size:14px;line-height:1.6;color:var(--body-text-color-subdued,#666)}
  label{display:flex;flex-direction:column;gap:7px;font-size:14px;min-width:0}ul{padding:0;list-style:none}li{padding:10px 0;overflow-wrap:anywhere}
  .user-row{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px}.user-actions{display:flex;align-items:center;flex-wrap:wrap;gap:8px}.user-row>span{min-width:0}
  form{display:grid;grid-template-columns:1fr 1fr;gap:14px;border-top:1px solid var(--border-color-primary,#ddd);padding-top:16px;margin-top:16px}
  input{padding:10px;font:inherit;border:1px solid var(--border-color-primary,#bbb);border-radius:6px;background:var(--background-fill-primary,#fff);color:var(--body-text-color,#222);min-width:0}
  button{font:inherit;padding:9px 14px;border:1px solid var(--border-color-primary,#aaa);border-radius:6px;cursor:pointer;background:var(--background-fill-secondary,#eee);color:var(--body-text-color,#222)}
  form>button{justify-self:start}form>.user-actions{grid-column:1/-1}button:disabled{opacity:.5}.error,.delete{color:#b42318}
  @media(max-width:600px){form{grid-template-columns:1fr}.users{padding:14px}}
</style>
