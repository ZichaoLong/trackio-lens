<script>
  import { t } from "../lib/i18n.js";
  import Logo from "./Logo.svelte";
  import ProjectSelector from "./ProjectSelector.svelte";

  let {
    open = $bindable(true),
    onToggle,
    projects = [],
    selectedProject = $bindable(null),
    projectLocked = false,
    logoUrls = undefined,
    darkMode = false,
    header = undefined,
    footer = undefined,
    children = undefined,
  } = $props();
</script>

<svelte:window onkeydown={(event) => { if (event.key === "Escape" && open) { open = false; onToggle?.(false); } }} />

{#if open}
  <button class="sidebar-backdrop" aria-label={$t("Close experiment controls")} onclick={() => { open = false; onToggle?.(false); }}></button>
{/if}
<aside class="sidebar-shell" class:collapsed={!open}>
  <button
    class="toggle-btn"
    title={open ? $t("Collapse sidebar") : $t("Expand sidebar")}
    aria-expanded={open}
    onclick={() => {
      open = !open;
      onToggle?.(open);
    }}
  >
    {#if open}
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
        <path
          d="M10 12L6 8L10 4"
          stroke="currentColor"
          stroke-width="1.5"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
      </svg>
    {:else}
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
        <path
          d="M6 4L10 8L6 12"
          stroke="currentColor"
          stroke-width="1.5"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
      </svg>
    {/if}
  </button>

  {#if open}
    <div class="shell-header">
      <Logo {logoUrls} {darkMode} />
      <ProjectSelector {projects} bind:selectedProject {projectLocked} />
      {#if header}{@render header()}{/if}
    </div>
    <div class="shell-body">
      {@render children?.()}
    </div>
    {#if footer}{@render footer()}{/if}
  {/if}
</aside>

<style>
  .sidebar-backdrop { display: none; }
  .sidebar-shell {
    width: 290px;
    min-width: 290px;
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    position: relative;
    border-right: 1px solid var(--border-color-primary, #e5e7eb);
    background: var(--background-fill-primary, #fff);
    overflow: hidden;
    transition:
      width 0.2s,
      min-width 0.2s;
  }
  .sidebar-shell.collapsed {
    width: 40px;
    min-width: 40px;
  }
  .toggle-btn {
    position: absolute;
    top: 12px;
    right: 8px;
    z-index: 10;
    border: none;
    background: none;
    color: var(--body-text-color-subdued, #9ca3af);
    cursor: pointer;
    padding: 4px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: var(--radius-sm, 4px);
    transition:
      color 0.15s,
      background-color 0.15s;
  }
  .toggle-btn:hover {
    color: var(--body-text-color, #1f2937);
    background-color: var(--background-fill-secondary, #f9fafb);
  }
  .shell-header {
    padding: 16px 16px 10px;
    flex-shrink: 0;
  }
  .shell-body {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
  }
  @media (max-width: 768px) {
    .sidebar-shell {position:fixed;inset:0 auto 0 0;width:min(320px, calc(100vw - 44px));min-width:0;z-index:60;box-shadow:8px 0 30px #0002;transition:none;}
    .sidebar-shell.collapsed {width:0;min-width:0;border:0;overflow:visible;box-shadow:none;}
    .sidebar-backdrop {display:block;position:fixed;inset:0;background:#10182866;border:0;z-index:59;}
    .toggle-btn {min-width:36px;min-height:36px;top:4px;right:4px;}
    .collapsed .toggle-btn {position:fixed;left:4px;right:auto;top:4px;background:var(--background-fill-primary,#fff);}
    .shell-header {padding-top:48px;}
  }
</style>
