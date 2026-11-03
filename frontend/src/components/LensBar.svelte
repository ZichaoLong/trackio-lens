<script>
  import { t } from "../lib/i18n.js";
  import { connection, frontendCommit, logout } from "../lib/lens.js";
  let logoutError = $state("");
  async function signOut() {
    try { await logout(); } catch (error) { logoutError = error.message; }
  }
</script>

<header class="lens-bar">
  <a href="/" class="lens-brand">Trackio <strong>Lens</strong></a>
  <span class="sync-status" role="status" title={$t("Time of the last successful data response")}>
    {#if $connection.lastUpdated}{$t("Synced")} {$connection.lastUpdated.toLocaleTimeString()}{:else}{$t("Connecting…")}{/if}
  </span>
  <button class="sign-out" onclick={signOut}>{$t("Sign out")}</button>
  <a href="/settings" class="account-link" aria-label={$t("Settings")} title={$t("Settings")}>⚙</a>
  <span class="build" title={$t("Frontend source {commit}", {commit: frontendCommit})}>{frontendCommit.slice(0, 7)}</span>
</header>
{#if $connection.needsSetup}
  <div class="notice" role="status">{$t("Choose your own account name and password in")} <a href="/settings">{$t("Settings")}</a>.</div>
{/if}
{#if $connection.updateAvailable}
  <div class="notice" role="status">{$t("An update is ready.")} <button onclick={() => location.reload()}>{$t("Refresh")}</button></div>
{/if}
{#if $connection.errors.length || logoutError}
  <div class="notice error" role="alert">{$t(logoutError || $connection.errors[0])} <button onclick={() => location.reload()}>{$t("Retry")}</button></div>
{/if}

<style>
  .lens-bar {display:flex;align-items:center;gap:12px;min-height:44px;padding:6px 16px;border-bottom:1px solid var(--border-color-primary,#e5e7eb);background:var(--background-fill-primary,#fff);flex-shrink:0;}
  .lens-brand {font-size:14px;font-weight:500;text-decoration:none;color:var(--body-text-color,#182338);white-space:nowrap;}
  .lens-brand strong {color:var(--color-accent,#244fc2);}
  .sync-status {font-size:12px;color:var(--body-text-color-subdued,#596579);margin-left:auto;}
  button {font:inherit;font-size:12px;border:1px solid var(--border-color-primary,#ddd);padding:6px 10px;border-radius:6px;background:var(--background-fill-primary,#fff);color:var(--body-text-color,#182338);cursor:pointer;}
  .build {font:10px ui-monospace,monospace;color:var(--body-text-color-subdued,#596579);}
  .account-link {font-size:22px;line-height:1;text-decoration:none;color:inherit;padding:6px;}
  .notice {padding:8px 16px;background:var(--background-fill-secondary,#eef2ff);font-size:13px;}
  .error {color:#b42318;}
  @media(max-width:768px) {.lens-bar{gap:8px;padding:4px 10px 4px 44px}.build{display:none}button{min-height:36px}.sync-status{font-size:11px}}
</style>
