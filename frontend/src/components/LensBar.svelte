<script>
  import { connection, frontendCommit, logout } from "../lib/lens.js";
  let logoutError = $state("");
  async function signOut() {
    try { await logout(); } catch (error) { logoutError = error.message; }
  }
</script>

<header class="lens-bar">
  <a href="/" class="lens-brand">Trackio <strong>Lens</strong></a>
  <span class="sync-status" role="status" title="Time of the last successful data response">
    {#if $connection.lastUpdated}Synced {$connection.lastUpdated.toLocaleTimeString()}{:else}Connecting…{/if}
  </span>
  <button class="sign-out" onclick={signOut}>Sign out</button>
  <span class="build" title={`Frontend source ${frontendCommit}`}>{frontendCommit.slice(0, 7)}</span>
</header>
{#if $connection.updateAvailable}
  <div class="notice" role="status">An update is ready. <button onclick={() => location.reload()}>Refresh</button></div>
{/if}
{#if $connection.errors.length || logoutError}
  <div class="notice error" role="alert">{logoutError || $connection.errors[0]} <button onclick={() => location.reload()}>Retry</button></div>
{/if}

<style>
  .lens-bar {display:flex;align-items:center;gap:12px;min-height:44px;padding:6px 16px;border-bottom:1px solid var(--border-color-primary,#e5e7eb);background:var(--background-fill-primary,#fff);flex-shrink:0;}
  .lens-brand {font-size:14px;font-weight:500;text-decoration:none;color:var(--body-text-color,#182338);white-space:nowrap;}
  .lens-brand strong {color:var(--color-accent,#244fc2);}
  .sync-status {font-size:12px;color:var(--body-text-color-subdued,#596579);margin-left:auto;}
  button {font:inherit;font-size:12px;border:1px solid var(--border-color-primary,#ddd);padding:6px 10px;border-radius:6px;background:var(--background-fill-primary,#fff);color:var(--body-text-color,#182338);cursor:pointer;}
  .build {font:10px ui-monospace,monospace;color:var(--body-text-color-subdued,#596579);}
  .notice {padding:8px 16px;background:var(--background-fill-secondary,#eef2ff);font-size:13px;}
  .error {color:#b42318;}
  @media(max-width:768px) {.lens-bar{gap:8px;padding:4px 10px}.build{display:none}button{min-height:36px}.sync-status{font-size:11px}}
</style>
