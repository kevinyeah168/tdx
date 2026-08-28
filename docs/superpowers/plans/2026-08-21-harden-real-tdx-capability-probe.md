# Harden Real TDX Capability Probe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct every Task 3 quality finding while preserving the runtime capability model and stopping before Task 4.

**Architecture:** Add a strict probe-local report wrapper and split orchestration, models, and semantic validation. Composite probes retain structured outcomes per source, while the CLI bounds real-network work and generates reproducible metadata.

**Tech Stack:** Python 3.10+, Pydantic 2, pandas, easy-tdx 1.20.7, pytest, mypy.

---

### Task 1: Strict report and source outcomes

**Files:**
- Create: `backend/workbench/providers/tdx/probe_models.py`
- Modify: `backend/tests/test_tdx_probe.py`

- [ ] **Step 1: Write failing tests**

Add tests that construct a report with timezone-aware `captured_at`, installed
version, `SH600000`, an optional discovered board, exact nine-key source outcomes,
and exact `ProviderCapabilities`; reject naive timestamps, missing outcome keys,
extra fields, and inconsistent source outcome status/error combinations.

- [ ] **Step 2: Verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_tdx_probe.py -q`

Expected: collection/import failures because `probe_models` does not exist.

- [ ] **Step 3: Implement the models**

Create strict `DiscoveredBoard`, `SourceOutcome`, `CapabilitySourceOutcomes`,
`ProbeManifest`, and `TdxCapabilityReport` Pydantic models. Reuse, but do not edit,
`ProviderCapabilities`.

- [ ] **Step 4: Verify GREEN**

Run the focused report-model tests and expect all to pass.

### Task 2: Endpoint semantic validation and safe evidence

**Files:**
- Create: `backend/workbench/providers/tdx/probe_validation.py`
- Modify: `backend/tests/test_tdx_probe.py`

- [ ] **Step 1: Write failing validator tests**

Cover valid endpoint responses plus wrong market/symbol, NaN, infinity, impossible
OHLC, invalid datetime, negative volume/amount, inconsistent main/small fund nets,
missing SH/SZ/BJ catalog aggregation, and unusable order-book levels. Add a test
showing only strict top-level identifiers are sampled and nested keys are ignored.

- [ ] **Step 2: Verify RED**

Run the validator test selection and expect import or assertion failures caused by
the absent semantic validators.

- [ ] **Step 3: Implement minimal validators**

Implement response-row extraction, context checking, finite numeric helpers,
datetime parsing, OHLC relationships, fund arithmetic tolerance, catalog market
coverage, order-book alias normalization, strict top-level sampling, and bounded
diagnostic sanitization.

- [ ] **Step 4: Verify GREEN**

Run the validator test selection and expect all to pass.

### Task 3: Probe orchestration, full catalog, fallbacks, and deadlines

**Files:**
- Modify: `backend/workbench/providers/tdx/probe.py`
- Modify: `backend/workbench/providers/tdx/clients.py`
- Modify: `backend/tests/test_tdx_probe.py`

- [ ] **Step 1: Write failing orchestration tests**

Require `get_security_list_all()` with no count/page calls, exact normal/enhanced
request context, structured outcomes for every source, fallback availability with
retained failures, rounded latency, controlled remaining results after deadline
exhaustion, and dynamic order-book behavior.

- [ ] **Step 2: Verify RED**

Run the orchestration test selection and record representative failures for the
old field-only, bare-model implementation.

- [ ] **Step 3: Implement the registry and source runner**

Add narrow probe client protocols, a registry-driven probe context, source outcome
capture, aggregate capability construction, monotonic deadline checks, and report
manifest generation. Call `get_security_list_all()` directly.

- [ ] **Step 4: Implement dynamic handicap detection**

Build the level selection from installed `FieldBit.__members__`, call
`build_bitmap`, construct `SymbolQuotesCmd`, request all levels only when both
constructions work, and otherwise request/validate levels 1-2 while reporting a
local client limitation.

- [ ] **Step 5: Verify GREEN**

Run all focused orchestration tests and expect all to pass.

### Task 4: Installed easy-tdx package contract tests

**Files:**
- Modify: `backend/tests/test_tdx_probe.py`

- [ ] **Step 1: Write failing transport-free tests**

Patch transports/execution while invoking actual installed `TdxClient` and
`MacClient` methods. Prove the full-list signature/page mechanism and request bytes
for enhanced quotes, capital flow, kline, and order book. Assert semantic alias
normalization for duplicate enum values.

- [ ] **Step 2: Verify RED**

Run the package-contract tests and expect failures where the probe does not yet use
or normalize the installed contract.

- [ ] **Step 3: Complete the package integration**

Make only the changes required for the actual 1.20.7 client/command contracts while
keeping future bitmap support dynamic.

- [ ] **Step 4: Verify GREEN**

Run the package-contract tests and expect all to pass without network transport.

### Task 5: CLI bounds, cleanup, and atomic descriptor safety

**Files:**
- Modify: `backend/tools/probe_tdx_capabilities.py`
- Modify: `backend/tests/test_tdx_probe.py`

- [ ] **Step 1: Write failing CLI tests**

Cover option defaults/validation, maximum target slicing independent of failure
threshold, timeout/deadline forwarding, normal close failure still closing
enhanced, both close failures, primary exception preservation with cleanup chaining,
strict wrapper output, and raw descriptor closure when `os.fdopen` fails.

- [ ] **Step 2: Verify RED**

Run the CLI/cleanup selection and record the old sequential-close and bare-output
failures.

- [ ] **Step 3: Implement CLI limits and cleanup**

Add explicit command options, construct bounded target pools, forward deadlines,
close both pools through an error-collecting helper, preserve primary errors, and
serialize only `TdxCapabilityReport`.

- [ ] **Step 4: Harden atomic output**

Track raw descriptor ownership across `os.fdopen`; close it directly if wrapping
fails and always remove the temporary file.

- [ ] **Step 5: Verify GREEN**

Run all focused probe/CLI tests and expect all to pass.

### Task 6: Real fixture and documentation

**Files:**
- Modify: `backend/tests/fixtures/tdx/capability_probe.json`
- Modify: `backend/tests/fixtures/tdx/README.md`
- Modify: `backend/tests/test_tdx_probe.py`

- [ ] **Step 1: Write failing fixture audit tests**

Require the strict wrapper, timezone-aware generated metadata, installed version,
`SH600000`, discovered board, exact source-outcome coverage, rounded latency, and
absence of hosts, IPs, paths, credentials, raw response values, and stack traces.

- [ ] **Step 2: Verify RED**

Run the fixture test against the old bare JSON and expect strict schema failure.

- [ ] **Step 3: Run the authorized capture**

Run: `.\.venv\Scripts\python.exe tools\probe_tdx_capabilities.py --tdx-home C:\new_tdx64 --output tests\fixtures\tdx\capability_probe.json`

Expected: exit code 0 and a generated strict report.

- [ ] **Step 4: Update README without duplicated metadata**

Document the manifest as source of truth, capital-flow date limitation, timing
bound, evidence semantics, and the exact safe refresh command.

- [ ] **Step 5: Verify GREEN**

Run the strict fixture/audit tests and expect all to pass.

### Task 7: Full verification and single commit

**Files:**
- Verify all changed Task 3 files only.

- [ ] **Step 1: Run focused and full tests**

Run focused probe tests, then `.\.venv\Scripts\python.exe -m pytest -q`; expect the
full backend suite to pass.

- [ ] **Step 2: Run static/build checks**

Run scoped `mypy --strict` over probe/provider fixture files and
`.\.venv\Scripts\python.exe -m compileall workbench`; expect exit code 0.

- [ ] **Step 3: Run repository audits**

Run `git diff --check`, privacy regex scans, a forbidden-scope path scan, and inspect
the final diff/stat; expect no findings.

- [ ] **Step 4: Commit once**

Stage only Task 3 implementation/tests/fixture/docs and commit with:

`fix: harden real tdx capability evidence`

- [ ] **Step 5: Report evidence**

Report status, architecture, RED/GREEN counts, actual capability/source table,
exact verification commands, commit SHA, changed files, and residual concerns.
