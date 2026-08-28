from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from importlib.metadata import version
import math
import time

from easy_tdx import Market
from easy_tdx.codec.bitmap import FieldBit, PresetField, build_bitmap
from easy_tdx.mac.commands.symbol_quotes import SymbolQuotesCmd

from workbench.domain import CapabilityResult, ProviderCapabilities
from workbench.providers.tdx.probe_models import (
    CAPABILITY_NAMES,
    PROBE_SCHEMA_VERSION,
    PROBE_VERSION,
    SAMPLE_SYMBOL,
    CapabilityName,
    CapabilitySourceOutcomes,
    DiscoveredBoard,
    ProbeManifest,
    SourceOutcome,
    TdxCapabilityReport,
)
from workbench.providers.tdx.probe_validation import (
    CapabilityUnavailable,
    ENHANCED_ORDER_BOOK_ALIASES,
    LocalClientCapabilityLimitation,
    NORMAL_ORDER_BOOK_ALIASES,
    ProbeDeadlineExceeded,
    ValidationEvidence,
    normalize_protocol_aliases,
    response_rows,
    sanitized_error,
    validate_bars,
    validate_minute_data,
    validate_official_funds,
    validate_order_book,
    validate_protocol_fields,
    validate_quotes,
    validate_security_catalog,
    validate_transactions,
)
from workbench.providers.tdx.probe_worker import SourceExecutor, SourceRequest


_STOCK_CODE = "600000"
_ENHANCED_MARKET = int(Market.SH)

ENHANCED_QUOTE_FIELDS = PresetField.COMMON

Clock = Callable[[], float]
Validator = Callable[[object], ValidationEvidence]


@dataclass(frozen=True, slots=True)
class EnhancedHandicapPlan:
    fields: tuple[FieldBit, ...]
    levels: int
    aliases: dict[str, str]
    limitation: str | None


@dataclass(slots=True)
class _ProbeContext:
    source_executor: SourceExecutor
    clock: Clock
    overall_deadline_at: float
    capability_deadline_at: float = math.inf
    discovered_board: DiscoveredBoard | None = None
    current_outcomes: list[SourceOutcome] = field(default_factory=list)

    def begin_capability(self) -> None:
        self.current_outcomes = []

    def record(self, outcome: SourceOutcome) -> SourceOutcome:
        self.current_outcomes.append(outcome)
        return outcome

    def replace_last(self, outcome: SourceOutcome) -> None:
        if not self.current_outcomes:
            raise RuntimeError("cannot replace an outcome before one is recorded")
        self.current_outcomes[-1] = outcome

    def attempt(
        self,
        source: str,
        request: SourceRequest,
        validator: Validator,
    ) -> SourceOutcome:
        remaining = min(
            self.overall_deadline_at,
            self.capability_deadline_at,
        ) - self.clock()
        if remaining <= 0:
            return self.record(_skipped_outcome(
                source,
                ProbeDeadlineExceeded("capability deadline exhausted before source attempt"),
            ))
        try:
            response = self.source_executor.execute(
                request,
                source=source,
                hard_timeout_seconds=remaining,
            )
            evidence = validator(response)
        except Exception as exc:
            return self.record(_failed_outcome(source, exc))
        return self.record(SourceOutcome(
            source=source,
            attempted=True,
            status="succeeded",
            evidence=evidence.sample_fields,
            error=None,
        ))


CapabilityCheck = Callable[[_ProbeContext], None]


def probe_tdx_capabilities(
    *,
    source_executor: SourceExecutor,
    clock: Clock = time.monotonic,
    captured_at: datetime | None = None,
    easy_tdx_version: str | None = None,
    overall_hard_deadline_seconds: float = 120.0,
    capability_hard_deadline_seconds: float = 20.0,
) -> TdxCapabilityReport:
    """Probe TDX capabilities independently and retain every source outcome."""

    _validate_deadline(
        "overall_hard_deadline_seconds", overall_hard_deadline_seconds
    )
    _validate_deadline(
        "capability_hard_deadline_seconds", capability_hard_deadline_seconds
    )
    overall_started = clock()
    context = _ProbeContext(
        source_executor=source_executor,
        clock=clock,
        overall_deadline_at=overall_started + overall_hard_deadline_seconds,
    )
    results: dict[str, CapabilityResult] = {}
    source_outcomes: dict[str, list[SourceOutcome]] = {}

    for capability, check in CAPABILITY_REGISTRY:
        context.begin_capability()
        if clock() >= context.overall_deadline_at:
            result, outcomes = _controlled_deadline_result()
        else:
            started = clock()
            context.capability_deadline_at = min(
                context.overall_deadline_at,
                started + capability_hard_deadline_seconds,
            )
            try:
                check(context)
            except Exception as exc:
                context.record(_failed_outcome("probe.capability-isolation", exc))
            outcomes = list(context.current_outcomes)
            if not outcomes:
                outcomes = [
                    _failed_outcome(
                        "probe.capability-isolation",
                        CapabilityUnavailable(
                            f"{capability} probe produced no source outcome"
                        ),
                    )
                ]
            finished = clock()
            result = _aggregate_result(outcomes, started=started, finished=finished)
        results[capability] = result
        source_outcomes[capability] = outcomes

    manifest = ProbeManifest(
        schema_version=PROBE_SCHEMA_VERSION,
        probe_version=PROBE_VERSION,
        captured_at=captured_at or datetime.now().astimezone(),
        easy_tdx_version=easy_tdx_version or version("easy-tdx"),
        sample_symbol=SAMPLE_SYMBOL,
        discovered_board=context.discovered_board,
        source_outcomes=CapabilitySourceOutcomes.model_validate(source_outcomes),
    )
    return TdxCapabilityReport(
        manifest=manifest,
        capabilities=ProviderCapabilities.model_validate(results),
    )


def enhanced_handicap_plan() -> EnhancedHandicapPlan:
    """Detect installed full-handicap request support through real construction."""

    partial_names = (
        "BID_PRICE",
        "ASK_PRICE",
        "BID_VOLUME",
        "ASK_VOLUME",
        "BID2_PRICE",
        "ASK2_PRICE",
        "BID2_VOLUME",
        "ASK2_VOLUME",
    )
    full_names = partial_names + (
        "BID3_PRICE",
        "ASK3_PRICE",
        "BID3_VOLUME",
        "ASK3_VOLUME",
        "BID4_PRICE",
        "ASK4_PRICE",
        "BID4_VOLUME",
        "ASK4_VOLUME",
        "BID5_PRICE",
        "ASK5_PRICE",
        "BID5_VOLUME",
        "ASK5_VOLUME",
    )
    members = FieldBit.__members__
    partial = tuple(members[name] for name in partial_names if name in members)
    full = tuple(members[name] for name in full_names if name in members)
    missing_full = [name for name in full_names if name not in members]

    if not missing_full:
        try:
            build_bitmap(full)
            SymbolQuotesCmd([(_ENHANCED_MARKET, _STOCK_CODE)], full).build_request()
        except Exception as exc:
            limitation = (
                "installed easy-tdx bitmap/command cannot construct order-book "
                f"levels 3-5 ({type(exc).__name__})"
            )
        else:
            return EnhancedHandicapPlan(
                fields=full,
                levels=5,
                aliases=dict(ENHANCED_ORDER_BOOK_ALIASES),
                limitation=None,
            )
    else:
        limitation = (
            "installed easy-tdx is missing full order-book fields: "
            + ", ".join(missing_full)
        )

    build_bitmap(partial)
    SymbolQuotesCmd([(_ENHANCED_MARKET, _STOCK_CODE)], partial).build_request()
    return EnhancedHandicapPlan(
        fields=partial,
        levels=2,
        aliases=dict(ENHANCED_ORDER_BOOK_ALIASES),
        limitation=limitation,
    )


def _probe_security_catalog(context: _ProbeContext) -> None:
    context.attempt(
        "tdx.normal.security-list-all-network",
        SourceRequest(pool="normal", operation="security-catalog"),
        validate_security_catalog,
    )


def _probe_board_list(context: _ProbeContext) -> None:
    response_holder: list[object] = []

    def validate_and_hold(response: object) -> ValidationEvidence:
        response_holder.append(response)
        return validate_protocol_fields(response, required={"code", "name"})

    outcome = context.attempt(
        "tdx.enhanced.board-list",
        SourceRequest(pool="enhanced", operation="board-list"),
        validate_and_hold,
    )
    if outcome.status == "succeeded":
        rows = response_rows(response_holder[0], limit=1)
        if rows:
            board_id = str(rows[0].get("code", "")).strip()
            board_name = str(rows[0].get("name", "")).strip()
            if board_id and board_name:
                context.discovered_board = DiscoveredBoard(
                    id=board_id,
                    name=board_name,
                )
            else:
                raise CapabilityUnavailable(
                    "industry board identity could not be verified"
                )


def _probe_board_members(context: _ProbeContext) -> None:
    if context.discovered_board is None:
        context.record(
            _skipped_outcome(
                "tdx.enhanced.board-members",
                CapabilityUnavailable("industry board discovery unavailable"),
            )
        )
        return
    board_id = context.discovered_board.id
    context.attempt(
        "tdx.enhanced.board-members",
        SourceRequest(
            pool="enhanced",
            operation="board-members",
            board_id=board_id,
        ),
        lambda response: validate_protocol_fields(
            response,
            required={"code", "name"},
        ),
    )


def _probe_official_funds(context: _ProbeContext) -> None:
    context.attempt(
            "tdx.enhanced.capital-flow",
            SourceRequest(pool="enhanced", operation="official-funds"),
            lambda response: validate_official_funds(
                response,
                expected_market=_ENHANCED_MARKET,
                expected_code=_STOCK_CODE,
            ),
        )


def _probe_quotes(context: _ProbeContext) -> None:
    context.attempt(
            "tdx.normal.quotes",
            SourceRequest(pool="normal", operation="normal-quotes"),
            lambda response: validate_quotes(
                response,
                expected_market=_ENHANCED_MARKET,
                expected_code=_STOCK_CODE,
            ),
        )
    context.attempt(
            "tdx.enhanced.quotes",
            SourceRequest(
                pool="enhanced",
                operation="enhanced-quotes",
                fields=ENHANCED_QUOTE_FIELDS,
            ),
            lambda response: validate_quotes(
                response,
                expected_market=_ENHANCED_MARKET,
                expected_code=_STOCK_CODE,
            ),
        )


def _probe_transactions(context: _ProbeContext) -> None:
    context.attempt(
            "tdx.normal.transactions",
            SourceRequest(pool="normal", operation="transactions"),
            lambda response: validate_transactions(
                response,
                expected_market=_ENHANCED_MARKET,
                expected_code=_STOCK_CODE,
            ),
        )


def _probe_minute_data(context: _ProbeContext) -> None:
    context.attempt(
            "tdx.normal.minute-data",
            SourceRequest(pool="normal", operation="minute-data"),
            validate_minute_data,
        )


def _probe_bars(context: _ProbeContext) -> None:
    context.attempt(
            "tdx.normal.bars",
            SourceRequest(pool="normal", operation="normal-bars"),
            lambda response: validate_bars(
                response,
                expected_market=_ENHANCED_MARKET,
                expected_code=_STOCK_CODE,
            ),
        )
    context.attempt(
            "tdx.enhanced.kline",
            SourceRequest(pool="enhanced", operation="enhanced-bars"),
            lambda response: validate_bars(
                response,
                expected_market=_ENHANCED_MARKET,
                expected_code=_STOCK_CODE,
            ),
        )


def _probe_order_book(context: _ProbeContext) -> None:
    normal = context.attempt(
        "tdx.normal.order-book",
        SourceRequest(pool="normal", operation="normal-order-book"),
        lambda response: validate_order_book(
            normalize_protocol_aliases(response, NORMAL_ORDER_BOOK_ALIASES),
            expected_market=_ENHANCED_MARKET,
            expected_code=_STOCK_CODE,
            levels=5,
        ),
    )

    try:
        plan = enhanced_handicap_plan()
    except Exception as exc:
        context.record(_failed_outcome("tdx.enhanced.order-book", exc))
        return
    enhanced = context.attempt(
        "tdx.enhanced.order-book",
        SourceRequest(
            pool="enhanced",
            operation="enhanced-order-book",
            fields=plan.fields,
        ),
        lambda response: validate_order_book(
            normalize_protocol_aliases(response, plan.aliases),
            expected_market=_ENHANCED_MARKET,
            expected_code=_STOCK_CODE,
            levels=plan.levels,
        ),
    )
    if enhanced.status == "succeeded" and plan.limitation is not None:
        context.replace_last(SourceOutcome(
            source=enhanced.source,
            attempted=True,
            status="failed",
            evidence=enhanced.evidence,
            error=sanitized_error(
                LocalClientCapabilityLimitation(
                    f"{plan.limitation}; verified levels 1-2 only"
                )
            ),
        ))


CAPABILITY_REGISTRY: tuple[tuple[CapabilityName, CapabilityCheck], ...] = (
    ("security_catalog", _probe_security_catalog),
    ("board_list", _probe_board_list),
    ("board_members", _probe_board_members),
    ("official_funds", _probe_official_funds),
    ("quotes", _probe_quotes),
    ("transactions", _probe_transactions),
    ("minute_data", _probe_minute_data),
    ("bars", _probe_bars),
    ("order_book", _probe_order_book),
)


def _aggregate_result(
    outcomes: list[SourceOutcome],
    *,
    started: float,
    finished: float,
) -> CapabilityResult:
    successful = [outcome for outcome in outcomes if outcome.status == "succeeded"]
    isolation_failed = any(
        outcome.source == "probe.capability-isolation"
        and outcome.status == "failed"
        for outcome in outcomes
    )
    labels = [
        outcome.source
        for outcome in (outcomes if isolation_failed else (successful or outcomes))
    ]
    source = "+".join(dict.fromkeys(labels))
    fields: list[str] = []
    for outcome in successful:
        for field in outcome.evidence:
            if field not in fields and len(fields) < 12:
                fields.append(field)
    latency_ms = (finished - started) * 1000.0
    if not math.isfinite(latency_ms) or latency_ms < 0:
        latency_ms = 0.0
    latency_ms = round(latency_ms, 3)

    if successful and not isolation_failed:
        return CapabilityResult(
            available=True,
            source=source,
            latency_ms=latency_ms,
            sample_fields=fields,
            error=None,
        )
    errors = [outcome.error for outcome in outcomes if outcome.error is not None]
    error = (
        errors[0]
        if len(errors) == 1
        else sanitized_error(CapabilityUnavailable("all attempted sources failed"))
    )
    return CapabilityResult(
        available=False,
        source=source,
        latency_ms=latency_ms,
        sample_fields=[],
        error=error,
    )


def _controlled_deadline_result() -> tuple[CapabilityResult, list[SourceOutcome]]:
    error = sanitized_error(
        ProbeDeadlineExceeded("overall probe deadline exhausted")
    )
    outcome = SourceOutcome(
        source="probe.deadline",
        attempted=False,
        status="skipped",
        evidence=[],
        error=error,
    )
    result = CapabilityResult(
        available=False,
        source="probe.deadline",
        latency_ms=0.0,
        sample_fields=[],
        error=error,
    )
    return result, [outcome]


def _failed_outcome(source: str, exc: BaseException) -> SourceOutcome:
    return SourceOutcome(
        source=source,
        attempted=True,
        status="failed",
        evidence=[],
        error=sanitized_error(exc),
    )


def _skipped_outcome(source: str, exc: BaseException) -> SourceOutcome:
    return SourceOutcome(
        source=source,
        attempted=False,
        status="skipped",
        evidence=[],
        error=sanitized_error(exc),
    )


def _validate_deadline(name: str, value: float) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")


assert tuple(name for name, _check in CAPABILITY_REGISTRY) == CAPABILITY_NAMES
