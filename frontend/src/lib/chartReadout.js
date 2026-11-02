// Inspect original observations; smoothing is presentation only.
export function readoutSteps(data, x) {
  return [...new Set(data.filter(row => row.data_type !== "smoothed" && Number.isFinite(row[x])).map(row => row[x]))].sort((a, b) => a - b);
}

export function readoutAt(data, x, y, step) {
  const runs = new Map();
  for (const row of data) {
    if (row.data_type === "smoothed") continue;
    const key = row.series_key || row.run_id || row.run || "value";
    if (!runs.has(key)) runs.set(key, { key, name: row.run || key, value: null });
    if (row[x] === step && Number.isFinite(row[y])) runs.get(key).value = row[y];
  }
  return [...runs.values()];
}
