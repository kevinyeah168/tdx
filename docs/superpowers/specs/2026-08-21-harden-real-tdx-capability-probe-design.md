# Hardened Real TDX Capability Probe Design

## Scope

This repair is limited to the Task 3 capability probe, its probe-local client
contracts, CLI, tests, generated fixture, and fixture documentation. It does not
change `ProviderCapabilities`, runtime services, ports, persistence, catalog
synchronization, or any Task 4 behavior.

## Architecture

The probe keeps the runtime `ProviderCapabilities` contract intact and wraps it in
a strict probe-local `TdxCapabilityReport`. The report has a manifest containing
schema/probe revisions, a timezone-aware capture timestamp, installed easy-tdx
version, fixed sample symbol, discovered board identity, and structured source
outcomes for every capability. The second report member is the unchanged strict
nine-capability `ProviderCapabilities` value.

Responsibilities are split into three focused modules:

- `probe.py` owns endpoint calls, the capability registry, fallback aggregation,
  deadlines, and dynamic enhanced-handicap selection.
- `probe_models.py` owns strict report, manifest, board, and source-outcome models.
- `probe_validation.py` owns semantic endpoint validators, response normalization,
  safe top-level field sampling, and diagnostic sanitization.

The CLI owns target selection, socket timeout configuration, independent pool
cleanup, metadata-safe atomic output, and user-facing option defaults.

## Evidence semantics

Every attempted source produces one `SourceOutcome` with a stable source label,
success/failure status, bounded top-level protocol field evidence, and a sanitized
error on failure. Aggregate quotes, bars, and order-book availability may remain
true if one source succeeds, while failed fallback attempts remain visible in the
manifest.

Catalog evidence comes directly from `get_security_list_all()` and is accepted
only when distinct valid SH, SZ, and BJ market/code/name records demonstrate a
genuinely aggregated catalog. Quote, fund, minute, bar, and order-book responses
are validated for requested context and value semantics rather than field presence.
The installed capital-flow parser's blank date is an acknowledged protocol-client
limitation, so fund validation does not require a date.

Normal quote responses can prove all five order-book levels. Enhanced full-handicap
support is detected at runtime by constructing both the installed bitmap and the
real `SymbolQuotesCmd`. Ambiguous enum aliases are normalized according to the
requested semantic field, including `limit_up_count` as `bid2_volume`. If only
levels 1-2 are constructible, their evidence is retained but five-level capability
is not claimed.

## Timing and cleanup

The CLI limits each pool to an explicit maximum target count independent of circuit
breaker thresholds. Socket timeouts bound each node attempt. Overall and
per-capability monotonic deadlines are checked before capability/source attempts;
once exhausted, untouched work becomes controlled unavailable instead of starting
new network operations. The README documents the resulting upper bound and the
cooperative nature of deadline checks around synchronous protocol calls.

Normal and enhanced pools are always closed independently. If probing raises, that
primary exception remains the raised exception and any cleanup failures are chained
as a probe-local aggregate error. Without a primary failure, one or two cleanup
failures are reported together. This remains compatible with the project's Python
3.10 runtime without adding an exception-group dependency.

## Safety and reproducibility

The CLI generates all capture metadata. The committed README does not duplicate a
capture date or board identity that could drift from JSON. Reports exclude node
addresses, hosts, IPs, local paths, credentials, raw response rows, arbitrary
response values, and stack traces; the explicitly required discovered board
identity is the sole response-value metadata exception.

Safe field evidence is limited to bounded top-level identifiers matching a strict
protocol identifier pattern. Nested mappings are never traversed. Atomic output
closes the raw descriptor if `os.fdopen` fails and removes temporary files on every
failure path.

## Verification

Tests first establish RED evidence for semantic rejection cases, the full-list
package contract, source-outcome retention, deadlines and cleanup, real installed
command construction, alias normalization, strict fixture metadata, and descriptor
cleanup. GREEN verification includes focused probe tests, the authorized live
capture command, all backend tests, scoped strict mypy, compileall, diff checks,
and privacy/scope scans.
