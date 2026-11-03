<script>
  import { t } from "../lib/i18n.js";
  import { readoutAt, readoutSteps } from "../lib/chartReadout.js";
  let { data, x, y, target = null } = $props();
  let steps = $derived(readoutSteps(data, x));
  let index = $state(0);
  $effect(() => {
    if (target != null && steps.length) {
      index = steps.reduce((nearest, value, i) => Math.abs(value - target) < Math.abs(steps[nearest] - target) ? i : nearest, 0);
    }
  });
  let step = $derived(steps[Math.min(index, steps.length - 1)]);
  let readings = $derived(readoutAt(data, x, y, step));
</script>

{#if steps.length}
  <div class="chart-readout" aria-label={$t("Original observations")}>
    <label><strong>{x}: {step}</strong><span>{$t("Original values")}</span>
      <input type="range" min="0" max={steps.length - 1} step="1" bind:value={index} aria-label={$t("Read {y} by {x}", {y, x})} />
    </label>
    <dl>
      {#each readings as reading (reading.key)}
        <div><dt>{reading.name}</dt><dd>{reading.value == null ? "Missing" : Number(reading.value.toPrecision(6))}</dd></div>
      {/each}
    </dl>
  </div>
{/if}

<style>
  .chart-readout {padding:12px;margin:8px;border:1px solid var(--border-color-primary,#e5e7eb);border-radius:6px;font-size:12px;background:var(--background-fill-secondary,#f8fafc);}
  label {display:flex;flex-wrap:wrap;align-items:center;gap:8px;}
  label span {margin-left:auto;color:var(--body-text-color-subdued,#596579);}
  input {width:100%;min-height:36px;}
  dl {margin:0;}
  dl div {display:flex;align-items:baseline;gap:12px;padding:4px 0;}
  dt {flex:1;overflow-wrap:anywhere;min-width:0;}
  dd {font-variant-numeric:tabular-nums;margin:0;flex-shrink:0;}
</style>
