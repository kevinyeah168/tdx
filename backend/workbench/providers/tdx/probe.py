from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from importlib.metadata import version
import math
import time
from typing import Generic, Protocol, TypeVar

from easy_tdx import BoardType, KlineCategory, Market, Period
from easy_tdx.codec.bitmap import FieldBit, PresetField, build_bitmap
from easy_tdx.mac.commands.symbol_quotes import SymbolQuotesCmd

from workbench.domain import CapabilityResult, ProviderCapabilities
from workbench.providers.tdx.clients import EnhancedProbeClient, NormalProbeClient
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
)


_STOCK_CODE = "600000"
_NORMAL_MARKET = Market.SH
_ENHANCED_MARKET = int(Market.SH)
_SAMPLE_COUNT = 3
_BOARD_SAMPLE_COUNT = 8

ENHANCED_QUOTE_FIELDS = PresetField.COMMON

ClientT = TypeVar("ClientT", covariant=True)
ResultT = TypeVar("ResultT")
Clock = Callable[[], float]
Validator = Callable[[object], ValidationEvidence]


class ProbeNodePool(Protocol, Generic[ClientT]):
    def execute(self, operation: Callable[[ClientT], ResultT]) -> ResultT: ...


@dataclass(frozen=True, slots=True)
class EnhancedHandicapPlan:
    fields: tuple[FieldBit, ...]
    levels: int
    aliases: dict[str, str]
    limitation: str | None


@dataclass(slots=True)
class _ProbeContext:
    normal_pool: ProbeNodePool[NormalProbeClient]
    enhanced_pool: ProbeNodePool[EnhancedProbeClient]
    clock: Clock
    overall_deadline_at: float
    capability_deadline_at: float = math.inf
    discovered_board: DiscoveredBoard | None = None

    def deadline_exhausted(self) -> bool:
        now = self.clock()
        return now >= self.overall_deadline_at or now >= self.capability_deadline_at

    def attempt(
        self,
        source: str,
        operation: Callable[[], object],
        validator: Validator,
    ) -> SourceOutcome:
        if self.deadline_exhausted():
            return _failed_outcome(
                source,
                ProbeDeadlineExceeded("capability deadline exhausted before source attempt"),
            )
        try:
            response = operation()
            evidence = validator(response)
        except Exception as exc:
            return _failed_outcome(source, exc)
        return SourceOutcome(
            source=source,
            attempted=True,
            status="succeeded",
            evidence=evidence.sample_fields,
            error=None,
        )


CapabilityCheck = Callable[[_ProbeContext], list[SourceOutcome]]


def probe_tdx_capabilities(
    normal_pool: ProbeNodePool[NormalProbeClient],
    enhanced_pool: ProbeNodePool[EnhancedProbeClient],
    *,
    clock: Clock = time.monotonic,
    captured_at: datetime | None = None,
    easy_tdx_version: str | None = None,
    overall_deadline_seconds: float = 120.0,
    capability_deadline_seconds: float = 20.0,
) -> TdxCapabilityReport:
    """Probe TDX capabilities independently and retain every source outcome."""

    _validate_deadline("overall_deadline_seconds", overall_deadline_seconds)
    _validate_deadline("capability_deadline_seconds", capability_deadline_seconds)
    overall_started = clock()
    context = _ProbeContext(
        normal_pool=normal_pool,
        enhanced_pool=enhanced_pool,
        clock=clock,
        overall_deadline_at=overall_started + overall_deadline_seconds,
    )
    results: dict[str, CapabilityResult] = {}
    source_outcomes: dict[str, list[SourceOutcome]] = {}

    for capability, check in CAPABILITY_REGISTRY:
        if clock() >= context.overall_deadline_at:
            result, outcomes = _controlled_deadline_result()
        else:
            started = clock()
            context.capability_deadline_at = min(
                context.overall_deadline_at,
                started + capability_deadline_seconds,
            )
            outcomes = check(context)
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


def _probe_security_catalog(context: _ProbeContext) -> list[SourceOutcome]:
    return [
        context.attempt(
            "tdx.normal.security-list-all",
            lambda: context.normal_pool.execute(
                lambda client: client.get_security_list_all()
            ),
            validate_security_catalog,
        )
    ]


def _probe_board_list(context: _ProbeContext) -> list[SourceOutcome]:
    response_holder: list[object] = []

    def fetch() -> object:
        response = context.enhanced_pool.execute(
            lambda client: client.get_board_list(
                board_type=BoardType.HY,
                count=_BOARD_SAMPLE_COUNT,
            )
        )
        response_holder.append(response)
        return response

    outcome = context.attempt(
        "tdx.enhanced.board-list",
        fetch,
        lambda response: validate_protocol_fields(
            response,
            required={"code", "name"},
        ),
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
                outcome = _failed_outcome(
                    "tdx.enhanced.board-list",
                    CapabilityUnavailable("industry board identity could not be verified"),
                )
    return [outcome]


def _probe_board_members(context: _ProbeContext) -> list[SourceOutcome]:
    if context.discovered_board is None:
        return [
            _failed_outcome(
                "tdx.enhanced.board-members",
                CapabilityUnavailable("industry board discovery unavailable"),
            )
        ]
    board_id = context.discovered_board.id
    return [
        context.attempt(
            "tdx.enhanced.board-members",
            lambda: context.enhanced_pool.execute(
                lambda client: client.get_board_members(
                    board_id,
                    count=_SAMPLE_COUNT,
                )
            ),
            lambda response: validate_protocol_fields(
                response,
                required={"code", "name"},
            ),
        )
    ]


def _probe_official_funds(context: _ProbeContext) -> list[SourceOutcome]:
    return [
        context.attempt(
            "tdx.enhanced.capital-flow",
            lambda: context.enhanced_pool.execute(
                lambda client: client.get_capital_flow(
                    _ENHANCED_MARKET,
                    _STOCK_CODE,
                )
            ),
            lambda response: validate_official_funds(
                response,
                expected_market=_ENHANCED_MARKET,
                expected_code=_STOCK_CODE,
            ),
        )
    ]


def _probe_quotes(context: _ProbeContext) -> list[SourceOutcome]:
    return [
        context.attempt(
            "tdx.normal.quotes",
            lambda: context.normal_pool.execute(
                lambda client: client.get_security_quotes(
                    [(_NORMAL_MARKET, _STOCK_CODE)]
                )
            ),
            lambda response: validate_quotes(
                response,
                expected_market=_ENHANCED_MARKET,
                expected_code=_STOCK_CODE,
            ),
        ),
        context.attempt(
            "tdx.enhanced.quotes",
            lambda: context.enhanced_pool.execute(
                lambda client: client.get_stock_quotes(
                    [(_ENHANCED_MARKET, _STOCK_CODE)],
                    fields=ENHANCED_QUOTE_FIELDS,
                )
            ),
            lambda response: validate_quotes(
                response,
                expected_market=_ENHANCED_MARKET,
                expected_code=_STOCK_CODE,
            ),
        ),
    ]


def _probe_transactions(context: _ProbeContext) -> list[SourceOutcome]:
    return [
        context.attempt(
            "tdx.normal.transactions",
            lambda: context.normal_pool.execute(
                lambda client: client.get_transaction_data(
                    _NORMAL_MARKET,
                    _STOCK_CODE,
                    0,
                    _SAMPLE_COUNT,
                )
            ),
            lambda response: validate_protocol_fields(
                response,
                required={"time", "price", "vol"},
            ),
        )
    ]


def _probe_minute_data(context: _ProbeContext) -> list[SourceOutcome]:
    return [
        context.attempt(
            "tdx.normal.minute-data",
            lambda: context.normal_pool.execute(
                lambda client: client.get_minute_time_data(
                    _NORMAL_MARKET,
                    _STOCK_CODE,
                )
            ),
            validate_minute_data,
        )
    ]


def _probe_bars(context: _ProbeContext) -> list[SourceOutcome]:
    return [
        context.attempt(
            "tdx.normal.bars",
            lambda: context.normal_pool.execute(
                lambda client: client.get_security_bars(
                    _NORMAL_MARKET,
                    _STOCK_CODE,
                    KlineCategory.DAY,
                    0,
                    _SAMPLE_COUNT,
                )
            ),
            lambda response: validate_bars(
                response,
                expected_market=_ENHANCED_MARKET,
                expected_code=_STOCK_CODE,
            ),
        ),
        context.attempt(
            "tdx.enhanced.kline",
            lambda: context.enhanced_pool.execute(
                lambda client: client.get_stock_kline(
                    _ENHANCED_MARKET,
                    _STOCK_CODE,
                    Period.DAILY,
                    0,
                    _SAMPLE_COUNT,
                )
            ),
            lambda response: validate_bars(
                response,
                expected_market=_ENHANCED_MARKET,
                expected_code=_STOCK_CODE,
            ),
        ),
    ]


def _probe_order_book(context: _ProbeContext) -> list[SourceOutcome]:
    normal = context.attempt(
        "tdx.normal.order-book",
        lambda: context.normal_pool.execute(
            lambda client: client.get_security_quotes(
                [(_NORMAL_MARKET, _STOCK_CODE)]
            )
        ),
        lambda response: validate_order_book(
            normalize_protocol_aliases(response, NORMAL_ORDER_BOOK_ALIASES),
            expected_market=_ENHANCED_MARKET,
            expected_code=_STOCK_CODE,
            levels=5,
        ),
    )

    plan = enhanced_handicap_plan()
    enhanced = context.attempt(
        "tdx.enhanced.order-book",
        lambda: context.enhanced_pool.execute(
            lambda client: client.get_stock_quotes(
                [(_ENHANCED_MARKET, _STOCK_CODE)],
                fields=plan.fields,
            )
        ),
        lambda response: validate_order_book(
            normalize_protocol_aliases(response, plan.aliases),
            expected_market=_ENHANCED_MARKET,
            expected_code=_STOCK_CODE,
            levels=plan.levels,
        ),
    )
    if enhanced.status == "succeeded" and plan.limitation is not None:
        enhanced = SourceOutcome(
            source=enhanced.source,
            attempted=True,
            status="failed",
            evidence=enhanced.evidence,
            error=sanitized_error(
                LocalClientCapabilityLimitation(
                    f"{plan.limitation}; verified levels 1-2 only"
                )
            ),
        )
    return [normal, enhanced]


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
    labels = [outcome.source for outcome in (successful or outcomes)]
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

    if successful:
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
        attempted=True,
        status="failed",
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


def _validate_deadline(name: str, value: float) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")


assert tuple(name for name, _check in CAPABILITY_REGISTRY) == CAPABILITY_NAMES
