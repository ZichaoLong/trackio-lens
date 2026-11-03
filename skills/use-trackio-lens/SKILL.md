---
name: use-trackio-lens
description: Connect existing experiment logging to an installed Trackio Lens instance when the user selects Lens as the recording or viewing destination. Covers SDK admission and destination discovery; does not develop or deploy Lens.
---

# Use Trackio Lens

Use the installed `trackio-lens` command from PATH or the operator's supplied
location. Selecting Trackio alone does not select Lens. Preserve existing
recording and destinations unless this task explicitly connects them to Lens;
existing authorization need not be requested again for each run.

1. Run `trackio-lens recording-info --json` for the selected instance. Resolve
   conflicting destinations before writing. Its `environment` supplies the
   local data root and storage mode, even while the viewer is stopped.
2. For a project's own SDK, run `trackio-lens check-writer --python /path/to/python`.
   The checker uses synthetic storage and caches compatible combinations.
   Use `--register` for an interpreter that should participate in future Lens
   upgrades; remove its registration before retiring the environment. A failed
   check does not authorize package upgrades or work on real data.
3. Apply the destination environment in the launcher, before importing Trackio.
   Training code uses standard Trackio SDK calls, without Lens imports, fixed
   machine paths, or imports from this skill. Do not install Lens into the
   training environment. Same-account local writes need neither HTTP tokens
   nor an online viewer.
4. Reuse project records and identifiers. Check the intended project/run and
   a small recorded result; do not replace the project's logging framework or
   repeat a full dashboard regression for each experiment. Treat optional
   recording failures separately from workload success.

For C++/JSONL, use the separate `trackio-lens record` process. For unusual SDK
features, use `check-writer --sample`. Read only the relevant section of the
installed guide or example located by `recording-info`'s `resources`; use the
installed command's `--help` for options. This skill does not require a checkout
or a personal experiment-management skill.

Reuse the authenticated service. Do not start an anonymous backend, migrate
existing data, or change service/network configuration merely to record a run.
Keep credentials and resolved private instance details outside public records.
