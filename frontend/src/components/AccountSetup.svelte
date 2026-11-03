<script>
  import AccountSettings from "./AccountSettings.svelte";
  import { locale, setLocale, t } from "../lib/i18n.js";
  import { logout } from "../lib/lens.js";
  let error = $state("");
  async function signOut() {
    try { await logout(); } catch (e) { error = e.message; }
  }
</script>

<main class="setup">
  <h1>Trackio Lens</h1>
  <h2>{$t("Complete your account setup")}</h2>
  <p>{$t("Set your personal credentials before opening experiments.")}</p>
  <label>{$t("Language")}
    <select value={$locale} onchange={event => setLocale(event.target.value)}>
      <option value="zh-CN">简体中文</option><option value="en">English</option>
    </select>
  </label>
  <AccountSettings />
  <button onclick={signOut}>{$t("Sign out")}</button>
  {#if error}<p role="alert">{$t(error)}</p>{/if}
</main>

<style>
  .setup{box-sizing:border-box;max-width:820px;margin:32px auto;padding:20px;font-family:system-ui,sans-serif}
  h1{font-size:26px}h2{font-size:20px}p{line-height:1.6}
  label{display:flex;align-items:center;gap:12px;margin-bottom:20px}
  select,button{font:inherit;padding:9px;border-radius:6px;border:1px solid #aaa;background:var(--background-fill-primary,#fff);color:var(--body-text-color,#222)}
  @media(max-width:600px){.setup{margin:0 auto;padding:16px}}
</style>
