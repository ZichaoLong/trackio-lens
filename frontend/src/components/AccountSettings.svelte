<script>
  import { onMount } from "svelte";
  import { acceptSession, connection } from "../lib/lens.js";
  let username = $state("");
  let currentPassword = $state("");
  let password = $state("");
  let repeat = $state("");
  let busy = $state(false);
  let error = $state("");
  let message = $state("");
  onMount(() => { username = $connection.username; });
  async function save(event) {
    event.preventDefault(); error = ""; message = "";
    if (password !== repeat) { error = "Passwords differ"; return; }
    busy = true;
    try {
      const response = await fetch("/__lens/account", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username, current_password: currentPassword, password }) });
      const data = await response.json();
      if (!response.ok) throw Error(data.error);
      acceptSession(data); currentPassword = ""; password = ""; repeat = "";
      message = "Account saved. Other devices have been signed out. Your program token is unchanged.";
    } catch (e) { error = e.message; }
    finally { busy = false; }
  }
  async function revoke() {
    error = "";
    if (!currentPassword) { error = "Enter your current password"; return; }
    busy = true;
    try {
      const response = await fetch("/__lens/account/revoke", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ current_password: currentPassword }) });
      const data = await response.json();
      if (!response.ok) throw Error(data.error);
      location.assign("/__lens/login");
    } catch (e) { error = e.message; busy = false; }
  }
</script>

<section class="account" aria-label="Account">
  <h3>Account</h3>
  <p>Use a personal password or passphrase to sign in on your other devices.</p>
  <form onsubmit={save}>
    <label>Username<input bind:value={username} autocomplete="username" required maxlength="80" /></label>
    <label>Current password<input type="password" bind:value={currentPassword} autocomplete="current-password" required /></label>
    <label>New password or passphrase<input type="password" bind:value={password} autocomplete="new-password" minlength="14" maxlength="256" required /></label>
    <label>Repeat new password<input type="password" bind:value={repeat} autocomplete="new-password" minlength="14" maxlength="256" required /></label>
    <p class="hint">Use 14–256 characters. You can use a memorable phrase or a password manager.</p>
    <div class="actions"><button type="submit" disabled={busy}>Save account</button><button type="button" disabled={busy} onclick={revoke}>Sign out all devices</button></div>
    {#if error}<p class="error" role="alert">{error}</p>{/if}
    {#if message}<p role="status">{message}</p>{/if}
  </form>
</section>
<style>
  .account{border:1px solid var(--border-color-primary,#ddd);border-radius:10px;padding:20px;margin-bottom:24px;max-width:760px}
  h3{margin:0 0 10px}p{font-size:14px;line-height:1.6;color:var(--body-text-color-subdued,#666)}
  form{display:grid;grid-template-columns:1fr 1fr;gap:14px}label{display:flex;flex-direction:column;gap:7px;font-size:14px;min-width:0}
  input{padding:10px;font:inherit;border:1px solid var(--border-color-primary,#bbb);border-radius:6px;background:var(--background-fill-primary,#fff);color:var(--body-text-color,#222);min-width:0}
  .hint,.actions,form>p{grid-column:1 / -1;margin:0}.actions{display:flex;gap:10px;flex-wrap:wrap}
  button{font:inherit;padding:9px 14px;border:1px solid var(--border-color-primary,#aaa);border-radius:6px;cursor:pointer;background:var(--background-fill-secondary,#eee);color:var(--body-text-color,#222)}
  button:disabled{opacity:.5}.error{color:#b42318}@media(max-width:600px){form{grid-template-columns:1fr}.account{padding:14px}}
</style>
