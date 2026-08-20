from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
import math
import re
import time
from typing import Any, Protocol, TypeVar, cast

from easy_tdx import BoardType, KlineCategory, Market, Period
from easy_tdx.codec.bitmap import PresetField

from workbench.domain import CapabilityResult, ProviderCapabilities


MAX_SAMPLE_ROWS = 2
MAX_SAMPLE_FIELDS = 12
_MAX_ERROR_LENGTH = 200
_STOCK_CODE = "600000"
_NORMAL_MARKET = Market.SH
_ENHANCED_MARKET = 0
_SAMPLE_COUNT = 3
_BOARD_SAMPLE_COUNT = 8

_CREDENTIAL_KEY_PATTERN = re.compile(
    r"(?:^|[_.-])(?:user(?:name)?|password|passwd|token|secret|api[-_]?key|credentials?|host(?:name)?)(?:$|[_.-])",
    re.IGNORECASE,
)
_CREDENTIAL_VALUE_PATTERN = re.compile(
    r"\b(?:user(?:name)?|password|passwd|token|secret|api[-_]?key|credentials?|host(?:name)?)\b"
    r"\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)",
    re.IGNORECASE,
)
_URL_CREDENTIAL_PATTERN = re.compile(
    r"\b([a-z][a-z0-9+.-]*://)[^/@\s]+@",
    re.IGNORECASE,
)
_IPV4_PATTERN = re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")
_IPV6_PATTERN = re.compile(
    r"\[(?:[0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}\]",
    re.IGNORECASE,
)
_HOST_PORT_PATTERN = re.compile(
    r"\b(?:(?:[a-z0-9-]+\.)+[a-z]{2,}(?::\d{1,5})?|[a-z][a-z0-9-]*:\d{1,5})\b",
    re.IGNORECASE,
)
_ABSOLUTE_PATH_PATTERN = re.compile(
    r'''(?ix)(?<!\w)["']?\\\\|(?<![\w])["']?[a-z]:[\\/]|(?<![:/\w])["']?/'''
)
_STACK_MARKER_PATTERN = re.compile(
    r"(?im)(?:^|\n)\s*(?:traceback\b|file\s+[\"']|at\s+\S+\s*\()"
)

_CAPITAL_FLOW_FIELDS = {
    "date",
    "main_in",
    "main_out",
    "main_net",
    "small_in",
    "small_out",
    "small_net",
    "mid_in",
    "mid_out",
    "mid_net",
    "large_in",
    "large_out",
    "large_net",
}
_ORDER_BOOK_FIELDS = {
    "bid_price",
    "bid2_price",
    "bid3_price",
    "bid4_price",
    "bid5_price",
    "ask_price",
    "ask2_price",
    "ask3_price",
    "ask4_price",
    "ask5_price",
    "bid_volume",
    "bid2_volume",
    "bid3_volume",
    "bid4_volume",
    "bid5_volume",
    "ask_volume",
    "ask2_volume",
    "ask3_volume",
    "ask4_volume",
    "ask5_volume",
}

ResultT = TypeVar("ResultT")
Clock = Callable[[], float]


class ProbeNodePool(Protocol):
    def execute(self, operation: Callable[[Any], ResultT]) -> ResultT: ...


class CapabilityUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _Evidence:
    source: str
    sample_fields: list[str]


def probe_tdx_capabilities(
    normal_pool: ProbeNodePool,
    enhanced_pool: ProbeNodePool,
    *,
    clock: Clock = time.monotonic,
) -> ProviderCapabilities:
    """Probe each TDX protocol capability independently.

    Injected pools own their client lifecycle. The probe records protocol field names only;
    it never records node identities or complete response rows.
    """

    discovered_board: tuple[str, str] | None = None
    enhanced_quote_fields = PresetField.BASIC + PresetField.HANDICAP

    def security_catalog() -> _Evidence:
        def fetch(client: Any) -> object:
            count = client.get_security_count(_NORMAL_MARKET)
            if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
                raise CapabilityUnavailable("security count response was empty")
            return client.get_security_list(_NORMAL_MARKET, 0)

        response = normal_pool.execute(fetch)
        return _response_evidence(
            "tdx.normal.security-list",
            response,
            required={"code", "name"},
        )

    def board_list() -> _Evidence:
        nonlocal discovered_board
        response = enhanced_pool.execute(
            lambda client: client.get_board_list(
                board_type=BoardType.HY,
                count=_BOARD_SAMPLE_COUNT,
            )
        )
        evidence = _response_evidence(
            "tdx.enhanced.board-list",
            response,
            required={"code", "name"},
        )
        first_row = _first_row(response)
        board_id = _safe_identifier(first_row.get("code"))
        board_name = _safe_identifier(first_row.get("name"))
        if board_id is None or board_name is None:
            raise CapabilityUnavailable("industry board identity could not be verified")
        discovered_board = (board_id, board_name)
        return evidence

    def board_members() -> _Evidence:
        if discovered_board is None:
            raise CapabilityUnavailable("industry board discovery unavailable")
        board_id, _board_name = discovered_board
        response = enhanced_pool.execute(
            lambda client: client.get_board_members(board_id, count=_SAMPLE_COUNT)
        )
        return _response_evidence(
            "tdx.enhanced.board-members",
            response,
            required={"code", "name"},
        )

    def official_funds() -> _Evidence:
        response = enhanced_pool.execute(
            lambda client: client.get_capital_flow(_ENHANCED_MARKET, _STOCK_CODE)
        )
        return _response_evidence(
            "tdx.enhanced.capital-flow",
            response,
            required=_CAPITAL_FLOW_FIELDS,
        )

    def normal_quotes() -> _Evidence:
        response = normal_pool.execute(
            lambda client: client.get_security_quotes(
                [(_NORMAL_MARKET, _STOCK_CODE)]
            )
        )
        return _response_evidence(
            "tdx.normal.quotes",
            response,
            required={"code"},
            required_any=({"price", "close"},),
        )

    def enhanced_quotes() -> _Evidence:
        response = enhanced_pool.execute(
            lambda client: client.get_stock_quotes(
                [(_ENHANCED_MARKET, _STOCK_CODE)],
                fields=enhanced_quote_fields,
            )
        )
        return _response_evidence(
            "tdx.enhanced.quotes",
            response,
            required={"code"},
            required_any=({"price", "close"},),
        )

    def transactions() -> _Evidence:
        response = normal_pool.execute(
            lambda client: client.get_transaction_data(
                _NORMAL_MARKET,
                _STOCK_CODE,
                0,
                _SAMPLE_COUNT,
            )
        )
        return _response_evidence(
            "tdx.normal.transactions",
            response,
            required={"time", "price", "vol"},
        )

    def minute_data() -> _Evidence:
        response = normal_pool.execute(
            lambda client: client.get_minute_time_data(_NORMAL_MARKET, _STOCK_CODE)
        )
        return _response_evidence(
            "tdx.normal.minute-data",
            response,
            required={"vol"},
            required_any=({"price", "close"},),
        )

    def normal_bars() -> _Evidence:
        response = normal_pool.execute(
            lambda client: client.get_security_bars(
                _NORMAL_MARKET,
                _STOCK_CODE,
                KlineCategory.DAY,
                0,
                _SAMPLE_COUNT,
            )
        )
        return _response_evidence(
            "tdx.normal.bars",
            response,
            required={"open", "high", "low", "close"},
        )

    def enhanced_bars() -> _Evidence:
        response = enhanced_pool.execute(
            lambda client: client.get_stock_kline(
                _ENHANCED_MARKET,
                _STOCK_CODE,
                Period.DAILY,
                0,
                _SAMPLE_COUNT,
            )
        )
        return _response_evidence(
            "tdx.enhanced.kline",
            response,
            required={"open", "high", "low", "close"},
        )

    def order_book() -> _Evidence:
        response = enhanced_pool.execute(
            lambda client: client.get_stock_quotes(
                [(_ENHANCED_MARKET, _STOCK_CODE)],
                fields=enhanced_quote_fields,
            )
        )
        return _response_evidence(
            "tdx.enhanced.order-book",
            response,
            required={"code", *_ORDER_BOOK_FIELDS},
        )

    results: dict[str, CapabilityResult] = {}
    results["security_catalog"] = _run_capability(
        "tdx.normal.security-list", security_catalog, clock
    )
    results["board_list"] = _run_capability(
        "tdx.enhanced.board-list", board_list, clock
    )
    results["board_members"] = _run_capability(
        "tdx.enhanced.board-members", board_members, clock
    )
    results["official_funds"] = _run_capability(
        "tdx.enhanced.capital-flow", official_funds, clock
    )
    results["quotes"] = _run_capability(
        "tdx.normal.quotes+tdx.enhanced.quotes",
        lambda: _combine_evidence(normal_quotes, enhanced_quotes),
        clock,
    )
    results["transactions"] = _run_capability(
        "tdx.normal.transactions", transactions, clock
    )
    results["minute_data"] = _run_capability(
        "tdx.normal.minute-data", minute_data, clock
    )
    results["bars"] = _run_capability(
        "tdx.normal.bars+tdx.enhanced.kline",
        lambda: _combine_evidence(normal_bars, enhanced_bars),
        clock,
    )
    results["order_book"] = _run_capability(
        "tdx.enhanced.order-book", order_book, clock
    )
    return ProviderCapabilities.model_validate(results)


def sanitized_error(exc: BaseException) -> str:
    """Return a bounded single-line exception summary safe for committed reports."""

    class_name = type(exc).__name__ if type(exc).__name__.isidentifier() else "ProviderError"
    try:
        message = str(exc)
    except Exception:
        message = "error details unavailable"

    stack_marker = _STACK_MARKER_PATTERN.search(message)
    if stack_marker is not None:
        message = message[: stack_marker.start()]
    message = _URL_CREDENTIAL_PATTERN.sub(r"\1<redacted>@", message)
    message = _CREDENTIAL_VALUE_PATTERN.sub("<redacted>", message)
    message = _IPV4_PATTERN.sub("<host redacted>", message)
    message = _IPV6_PATTERN.sub("<host redacted>", message)
    message = _HOST_PORT_PATTERN.sub("<host redacted>", message)
    path_marker = _ABSOLUTE_PATH_PATTERN.search(message)
    if path_marker is not None:
        prefix = message[: path_marker.start()].rstrip(" :,-\t\r\n")
        message = f"{prefix} <path redacted>" if prefix else "<path redacted>"
    message = " ".join(message.split())
    summary = f"{class_name}: {message}" if message else class_name
    if len(summary) > _MAX_ERROR_LENGTH:
        summary = f"{summary[: _MAX_ERROR_LENGTH - 3]}..."
    return summary


def _run_capability(
    attempted_source: str,
    check: Callable[[], _Evidence],
    clock: Clock,
) -> CapabilityResult:
    started = clock()
    try:
        evidence = check()
    except Exception as exc:
        available = False
        source = attempted_source
        sample_fields: list[str] = []
        error = sanitized_error(exc)
    else:
        available = True
        source = evidence.source
        sample_fields = evidence.sample_fields
        error = None
    finished = clock()
    latency_ms = (finished - started) * 1000.0
    if not math.isfinite(latency_ms) or latency_ms < 0:
        latency_ms = 0.0
    return CapabilityResult(
        available=available,
        source=source,
        latency_ms=latency_ms,
        sample_fields=sample_fields,
        error=error,
    )


def _combine_evidence(*checks: Callable[[], _Evidence]) -> _Evidence:
    successes: list[_Evidence] = []
    errors: list[str] = []
    for check in checks:
        try:
            successes.append(check())
        except Exception as exc:
            errors.append(sanitized_error(exc))
    if not successes:
        detail = "; ".join(errors) or "no protocol source returned evidence"
        raise CapabilityUnavailable(detail)

    fields: list[str] = []
    for evidence in successes:
        for field in evidence.sample_fields:
            if field not in fields and len(fields) < MAX_SAMPLE_FIELDS:
                fields.append(field)
    return _Evidence(
        source="+".join(evidence.source for evidence in successes),
        sample_fields=fields,
    )


def _response_evidence(
    source: str,
    response: object,
    *,
    required: set[str],
    required_any: tuple[set[str], ...] = (),
) -> _Evidence:
    if _response_is_empty(response):
        raise CapabilityUnavailable("protocol response was empty")

    protocol_fields = set(_top_level_fields(response))
    missing = sorted(required - protocol_fields)
    if missing:
        raise CapabilityUnavailable(
            f"response missing required protocol fields: {', '.join(missing)}"
        )
    for alternatives in required_any:
        if protocol_fields.isdisjoint(alternatives):
            raise CapabilityUnavailable(
                "response missing required protocol fields: "
                + " or ".join(sorted(alternatives))
            )

    sample_fields = _bounded_sample_fields(response)
    if not sample_fields:
        raise CapabilityUnavailable("response had no safe protocol fields")
    return _Evidence(source=source, sample_fields=sample_fields)


def _response_is_empty(response: object) -> bool:
    if response is None:
        return True
    empty = getattr(response, "empty", None)
    if isinstance(empty, bool):
        return empty
    if isinstance(response, Mapping | Sequence) and not isinstance(
        response, str | bytes | bytearray
    ):
        return len(response) == 0
    return False


def _first_row(response: object) -> dict[str, object]:
    rows = _sample_rows(response)
    if not rows:
        return {}
    row = rows[0]
    if isinstance(row, Mapping):
        return {str(key): value for key, value in row.items()}
    if is_dataclass(row) and not isinstance(row, type):
        return cast(dict[str, object], asdict(row))
    values = getattr(row, "__dict__", None)
    if isinstance(values, dict):
        return {str(key): value for key, value in values.items()}
    return {}


def _top_level_fields(response: object) -> list[str]:
    columns = getattr(response, "columns", None)
    if columns is not None:
        return [str(column) for column in list(columns)]
    row = _first_row(response)
    return list(row)


def _sample_rows(response: object) -> list[object]:
    head = getattr(response, "head", None)
    to_dict = getattr(response, "to_dict", None)
    if callable(head) and callable(to_dict):
        records = head(MAX_SAMPLE_ROWS).to_dict(orient="records")
        return list(records)[:MAX_SAMPLE_ROWS]
    if isinstance(response, Mapping):
        return [response]
    if isinstance(response, Sequence) and not isinstance(
        response, str | bytes | bytearray
    ):
        return list(response[:MAX_SAMPLE_ROWS])
    return [response]


def _bounded_sample_fields(response: object) -> list[str]:
    fields: list[str] = []

    def add_rows(value: object, prefix: str = "", depth: int = 0) -> None:
        if len(fields) >= MAX_SAMPLE_FIELDS or depth > 3:
            return
        if is_dataclass(value) and not isinstance(value, type):
            value = asdict(value)
        if isinstance(value, Mapping):
            for key, nested_value in value.items():
                safe_key = _safe_field_name(key)
                if safe_key is None:
                    continue
                field = f"{prefix}.{safe_key}" if prefix else safe_key
                if field not in fields:
                    fields.append(field)
                    if len(fields) >= MAX_SAMPLE_FIELDS:
                        return
                if isinstance(nested_value, Mapping | Sequence) and not isinstance(
                    nested_value, str | bytes | bytearray
                ):
                    add_rows(nested_value, field, depth + 1)
        elif isinstance(value, Sequence) and not isinstance(
            value, str | bytes | bytearray
        ):
            for nested_value in value[:MAX_SAMPLE_ROWS]:
                add_rows(nested_value, prefix, depth + 1)
                if len(fields) >= MAX_SAMPLE_FIELDS:
                    return
        else:
            values = getattr(value, "__dict__", None)
            if isinstance(values, dict):
                add_rows(values, prefix, depth + 1)

    rows = _sample_rows(response)
    for row in rows[:MAX_SAMPLE_ROWS]:
        add_rows(row)
        if len(fields) >= MAX_SAMPLE_FIELDS:
            break
    return fields


def _safe_field_name(value: object) -> str | None:
    try:
        field = str(value).strip()
    except Exception:
        return None
    if not field or len(field) > 80:
        return None
    if _CREDENTIAL_KEY_PATTERN.search(field):
        return None
    if (
        _IPV4_PATTERN.search(field)
        or _IPV6_PATTERN.search(field)
        or _HOST_PORT_PATTERN.search(field)
    ):
        return None
    if _ABSOLUTE_PATH_PATTERN.search(field) or _STACK_MARKER_PATTERN.search(field):
        return None
    return field


def _safe_identifier(value: object) -> str | None:
    if value is None:
        return None
    try:
        identifier = str(value).strip()
    except Exception:
        return None
    if not identifier or len(identifier) > 80:
        return None
    if _safe_field_name(identifier) is None:
        return None
    return identifier
