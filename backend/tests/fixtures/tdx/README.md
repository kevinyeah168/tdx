# TDX capability probe fixture

Capture date: 2026-08-20 (Asia/Shanghai).

This fixture is a sanitized live capture. Stock-level checks used `SH600000`;
normal calls used `Market.SH` and enhanced calls used `int(Market.SH) == 1`.
The probe requested `BoardType.HY`, selected the first industry board returned by
that bounded live response, and used board `881234` (`生物制品`) for the board
membership check. No board identifier is hardcoded in the probe.

## Evidence status

None of the entries are hand-authored or controlled placeholder results. Endpoint
evidence and the local installed-client limitation are classified separately:

- Real endpoint responses with `available=true`: `security_catalog`, `board_list`,
  `board_members`, `official_funds`, `quotes`, `minute_data`, and `bars`.
- Real endpoint response with `available=false`: `transactions`, whose bounded
  request returned no rows.
- Local installed-client limitation with `available=false`: `order_book`. A live,
  constructible level-1/2 quote request succeeded and was verified, but the
  installed easy-tdx request builder serializes only a 128-bit field bitmap and
  cannot encode the level-3/4/5 fields. This is not classified as a remote endpoint
  failure and must not be upgraded to five-level availability from partial fields.

The JSON records source labels, per-capability latency, and at most twelve real
protocol field names. It never records response rows, node addresses, credentials,
usernames, local absolute paths, or exception stacks.

## Safe refresh

From `backend`, validate the chosen read-only TDX installation and stage a capture
under the gitignored run directory before replacing the committed fixture:

```powershell
.\.venv\Scripts\python.exe tools\probe_tdx_capabilities.py --tdx-home <TDX_HOME> --output ..\data\run\tdx-capability-probe.raw.json
.\.venv\Scripts\python.exe -c "from pathlib import Path; from workbench.domain import ProviderCapabilities; ProviderCapabilities.model_validate_json(Path('../data/run/tdx-capability-probe.raw.json').read_text(encoding='utf-8'))"
```

Review the staged file for credentials, node addresses, usernames, absolute paths,
and stack traces. Only then copy the sanitized JSON to `capability_probe.json`,
update the capture date/board/evidence list above, rerun `tests/test_tdx_probe.py`,
and commit the fixture. Never commit console logs or files from `data/run`.
