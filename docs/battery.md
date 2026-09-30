# Battery diagnostics

One Bite includes an optional battery diagnostic that is independent of installation, repair, and verification. It reads macOS battery data without changing power settings, applications, or personal configuration. Its result never changes the outcome of `./1bite`, `--verify`, inventory, or update checks.

## Run it

The repository copy is always available:

```bash
./1bite --battery
./1bite --battery --summary
./1bite --battery --json
./1bite --battery --tsv
./1bite --battery --shell
./1bite --battery --field battery.charge_percent
```

The first command prints a human dashboard. `--summary` prints one line containing current charge, power and charging state, maximum capacity, and equivalent full cycles. It never reads `pmset -g log` or reads or writes the cache. JSON uses the stable [version 1 schema](battery.schema.json). TSV begins with `schema_version`, `section`, `index`, `key`, `value`, and `unit` columns. Shell output is a source-safe initialization fragment containing quoted `ONE_BITE_BATTERY_*` assignments and indexed interval fields; it clears interval variables left by a previously sourced report. The single-field interface accepts only documented scalar names; an unknown name exits 2, and an unavailable value exits 3 without printing a placeholder.

During a normal installation, the first target step prints the same summary after validating Apple Silicon, the macOS version, and the invoking user. The probe tree does not inherit the installation lock. Missing battery hardware, partial fields, probe failure, or empty output cannot fail that step or stop the following network and installation work. This display does not create a separate progress step, cache history, install the standalone command, or change `result.json`.

Allowed single fields are:

- `schema_version`, `collected_at`, `status`, and `complete`
- `battery.present`, `battery.charge_percent`, `battery.power_source`, `battery.state`, `battery.cycle_count`, `battery.maximum_capacity_percent`, `battery.maximum_capacity_mah`, `battery.design_capacity_mah`, `battery.health`, `battery.voltage_mv`, and `battery.current_ma`
- `history.retained_event_count` and `history.interval_count`

Use `--no-cache` with any report format to avoid reading or writing retained history. Current macOS log data can still produce intervals for that invocation.

## Optional command installation

Install the same script as a short standalone command only when wanted:

```bash
./1bite --install-battery
1bite-battery
```

This operation is separate from the main installer. It creates `~/.local/bin/1bite-battery` only when the path is absent. A byte-identical, executable managed copy is skipped without changing its timestamp. A healthy older managed copy is preserved until an explicit update:

```bash
./1bite --install-battery --update
```

An update proceeds only when a private receipt still matches the installed bytes. It backs up those managed bytes in the private battery state directory and then atomically replaces the command. A private kernel lock serializes command installation, and an atomic pending record safely completes ownership after interruption between publication and receipt creation. Unknown files, user-modified copies, non-regular paths, damaged ownership records, and symbolic links are preserved and reported instead of overwritten.

## Data sources and meaning

The diagnostic uses only tools included with macOS:

- `pmset -g batt` supplies current charge, power source, and charging state.
- `system_profiler SPPowerDataType` supplies the cycle count, Apple maximum-capacity percentage, and normalized health condition.
- `ioreg -r -c AppleSmartBattery` supplies allowlisted capacity, voltage, and current values, plus fallbacks when a preferred field is absent.
- `pmset -g log` supplies recent `AC` and `Batt`/`BATT` observations. Consecutive observations on the same source collapse into one boundary; source changes close the preceding interval. Short and zero-second plug/unplug intervals are retained.

All percentages are validated, converted to decimal integers, and range checked before comparison. A cycle count represents **equivalent full cycles**, not the number of times a charger was connected. Interval durations are **wall-clock time** and can include sleep. The displayed interval count covers the retained log/cache window and is **not** a lifetime count of charge or discharge sessions.

`status=no_battery` is a successful report with no invented history. `status=partial` means current data was usable but one or more allowlisted metrics or history sources were unavailable. `status=unavailable` means the primary `pmset -g batt` probe could not provide a trustworthy battery-presence result, and the command exits 1. Battery wear or a service recommendation is report data, not a command failure.

## Private history and privacy boundary

When caching is enabled, sanitized history lives at:

```text
${XDG_STATE_HOME:-$HOME/.local/state}/1bite/battery/history-v1.tsv
```

The battery directory is mode `0700`; cache and receipt files are mode `0600`. Cache replacement uses a private temporary file in the same directory followed by an atomic rename. A recognized but truncated version 1 cache is rebuilt from sanitized observations. A file with an unknown header is treated as user-owned and preserved. Symbolic links in the state path or cache path disable caching rather than being followed.

The cache contains only normalized timestamps, power source, numeric percentages, and derived interval fields. Raw `pmset`, `system_profiler`, and `ioreg` output is never stored. The allowlist excludes serial numbers, hardware identifiers, hostnames, account names, environment variables, credentials, application data, and personal configuration. Machine-readable warning codes contain no raw source text.

The repository quality tests use fixed command output and log fixtures. They verify parsers, formats, permissions, atomic replacement, privacy filtering, and ownership behavior. A release still needs a read-only check on disposable Apple Silicon hardware for actual field availability; command-line tests do not assess physical battery quality.
