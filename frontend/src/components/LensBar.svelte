<script>
  import { t } from "../lib/i18n.js";
  import { connection, frontendCommit, logout } from "../lib/lens.js";
  let logoutError = $state("");
  let accountLabel = $derived($t("Signed in as {username}. Open account settings.", {username: $connection.username}));
  async function signOut() {
    try { await logout(); } catch (error) { logoutError = error.message; }
  }
</script>

<header class="lens-bar">
  <a href="/" class="lens-brand" aria-label="Trackio Lens"><span class="desktop-label">Trackio&nbsp;</span><strong>Lens</strong></a>
  <a href="/settings" class="account-link" aria-label={accountLabel} title={accountLabel}>
    <bdi class="account-name">{$connection.username}</bdi>
  </a>
  <button class="sign-out" aria-label={$t("Sign out")} title={$t("Sign out")} onclick={signOut}>
    <span class="desktop-label">{$t("Sign out")}</span><span class="mobile-label">{$t("Logout")}</span>
  </button>
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
  .lens-bar {display:flex;align-items:center;gap:12px;min-height:44px;box-sizing:border-box;padding:6px 16px;border-bottom:1px solid var(--border-color-primary,#e5e7eb);background:var(--background-fill-primary,#fff);flex-shrink:0;}
  .lens-brand {font-size:14px;font-weight:500;text-decoration:none;color:var(--body-text-color,#182338);white-space:nowrap;flex-shrink:0;}
  .lens-brand strong {color:var(--color-accent,#244fc2);}
  .mobile-label {display:none;}
  button {font:inherit;font-size:12px;border:1px solid var(--border-color-primary,#ddd);padding:6px 10px;border-radius:6px;background:var(--background-fill-primary,#fff);color:var(--body-text-color,#182338);cursor:pointer;}
  .build {font:10px ui-monospace,monospace;color:var(--body-text-color-subdued,#596579);}
  .account-link {display:flex;align-items:center;margin-left:auto;min-width:0;max-width:min(30vw,22rem);padding:6px 0;font-size:12px;text-decoration:none;color:var(--body-text-color,#182338);}
  .account-link:hover .account-name {text-decoration:underline;}
  .account-name {min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
  .sign-out {flex-shrink:0;white-space:nowrap;}
  .notice {padding:8px 16px;background:var(--background-fill-secondary,#eef2ff);font-size:13px;}
  .error {color:#b42318;}
  @media(max-width:768px) {
    .lens-bar{gap:10px;padding:4px 10px 4px 44px}
    .account-link{max-width:none;min-height:36px;box-sizing:border-box}
    .sign-out{min-height:36px}
    .desktop-label,.build{display:none}
    .mobile-label{display:inline}
  }
</style>
