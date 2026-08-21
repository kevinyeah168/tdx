from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime
import math
from numbers import Integral, Real
import re
from typing import cast

from easy_tdx import Market


MAX_SAMPLE_ROWS = 2
MAX_SAMPLE_FIELDS = 12
_MAX_ERROR_LENGTH = 200

_PROTOCOL_FIELD_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_SENSITIVE_FIELD_PATTERN = re.compile(
    r"(?:^|_)(?:user(?:name)?|password|passwd|token|secret|api_?key|"
    r"credentials?|host(?:name)?)(?:$|_)",
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

_OFFICIAL_FUND_FIELDS = (
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
)

NORMAL_ORDER_BOOK_ALIASES = {
    **{f"bid{level}": f"bid{level}_price" for level in range(1, 6)},
    **{f"bid_vol{level}": f"bid{level}_volume" for level in range(1, 6)},
    **{f"ask{level}": f"ask{level}_price" for level in range(1, 6)},
    **{f"ask_vol{level}": f"ask{level}_volume" for level in range(1, 6)},
}

ENHANCED_ORDER_BOOK_ALIASES = {
    "bid_price": "bid1_price",
    "bid_volume": "bid1_volume",
    "ask_price": "ask1_price",
    "ask_volume": "ask1_volume",
    "limit_up_count": "bid2_volume",
    "limit_down_count": "ask2_volume",
    "up_count": "bid5_volume",
    "down_count": "ask5_volume",
}


class CapabilityUnavailable(RuntimeError):
    pass


class LocalClientCapabilityLimitation(CapabilityUnavailable):
    pass


class ProbeDeadlineExceeded(CapabilityUnavailable):
    pass


@dataclass(frozen=True, slots=True)
class ValidationEvidence:
    sample_fields: list[str]


def validate_security_catalog(response: object) -> ValidationEvidence:
    rows = response_rows(response)
    if not rows:
        raise CapabilityUnavailable("security catalog response was empty")

    markets: dict[int, set[str]] = {
        int(Market.SH): set(),
        int(Market.SZ): set(),
        int(Market.BJ): set(),
    }
    unique_symbols: set[tuple[int, str]] = set()
    for row in rows:
        market = _market_number(row.get("market"))
        code = _required_identifier(row, "code")
        _required_identifier(row, "name")
        if market not in markets or not _valid_a_share_code(market, code):
            continue
        symbol = (market, code)
        if symbol in unique_symbols:
            raise CapabilityUnavailable(
                "security catalog did not contain enough unique records"
            )
        unique_symbols.add(symbol)
        markets[market].add(code)

    if any(len(codes) < 2 for codes in markets.values()):
        raise CapabilityUnavailable(
            "security catalog did not demonstrate SH/SZ/BJ aggregation"
        )
    if len(unique_symbols) < 6:
        raise CapabilityUnavailable(
            "security catalog did not contain enough unique records"
        )
    return _evidence(response)


def validate_quotes(
    response: object,
    *,
    expected_market: int,
    expected_code: str,
) -> ValidationEvidence:
    rows = _required_rows(response, "quote")
    for row in rows:
        _validate_context(
            row,
            expected_market=expected_market,
            expected_code=expected_code,
            required=True,
        )
        price = _finite_field(row, ("price", "close"), minimum=0.0, positive=True)
        previous_close = _finite_field(
            row,
            ("pre_close", "last_close"),
            minimum=0.0,
            positive=True,
        )
        _finite_field(row, ("vol", "volume"), minimum=0.0)
        _finite_field(row, ("amount",), minimum=0.0)
        _validate_ohlc(row, fallback_close=price)
        if previous_close <= 0:
            raise CapabilityUnavailable("quote previous close was unusable")
    return _evidence(response)


def validate_official_funds(
    response: object,
    *,
    expected_market: int,
    expected_code: str,
) -> ValidationEvidence:
    rows = _required_rows(response, "official funds")
    for row in rows:
        _validate_context(
            row,
            expected_market=expected_market,
            expected_code=expected_code,
            required=False,
        )
        values = {field: _finite_field(row, (field,)) for field in _OFFICIAL_FUND_FIELDS}
        if not math.isclose(
            values["main_net"],
            values["main_in"] - values["main_out"],
            rel_tol=1e-6,
            abs_tol=1e-3,
        ):
            raise CapabilityUnavailable("official main fund values were inconsistent")
        if not math.isclose(
            values["small_net"],
            values["small_in"] - values["small_out"],
            rel_tol=1e-6,
            abs_tol=1e-3,
        ):
            raise CapabilityUnavailable("official small fund values were inconsistent")
    return _evidence(response)


def validate_minute_data(response: object) -> ValidationEvidence:
    rows = _required_rows(response, "minute data")
    for row in rows:
        _parse_datetime(row.get("datetime"))
        _finite_field(row, ("price", "close"), minimum=0.0, positive=True)
        _finite_field(row, ("vol", "volume"), minimum=0.0)
    return _evidence(response)


def validate_bars(
    response: object,
    *,
    expected_market: int,
    expected_code: str,
) -> ValidationEvidence:
    rows = _required_rows(response, "bar")
    for row in rows:
        _validate_context(
            row,
            expected_market=expected_market,
            expected_code=expected_code,
            required=False,
        )
        _parse_datetime(row.get("datetime"))
        _validate_ohlc(row)
        _finite_field(row, ("vol", "volume"), minimum=0.0)
        _finite_field(row, ("amount",), minimum=0.0)
    return _evidence(response)


def validate_order_book(
    response: object,
    *,
    expected_market: int,
    expected_code: str,
    levels: int,
) -> ValidationEvidence:
    if levels not in {2, 5}:
        raise ValueError("order-book validation supports two or five levels")
    rows = _required_rows(response, "order book")
    for row in rows:
        _validate_context(
            row,
            expected_market=expected_market,
            expected_code=expected_code,
            required=True,
        )
        for level in range(1, levels + 1):
            for side in ("bid", "ask"):
                _finite_field(
                    row,
                    (f"{side}{level}_price",),
                    minimum=0.0,
                    positive=True,
                )
                _finite_field(
                    row,
                    (f"{side}{level}_volume",),
                    minimum=0.0,
                )

    fields = sample_protocol_fields(response)
    if levels == 5 and "bid5_price" not in fields:
        if len(fields) >= MAX_SAMPLE_FIELDS:
            fields[-1] = "bid5_price"
        else:
            fields.append("bid5_price")
    return ValidationEvidence(sample_fields=fields)


def validate_protocol_fields(
    response: object,
    *,
    required: set[str],
    required_any: tuple[set[str], ...] = (),
) -> ValidationEvidence:
    rows = _required_rows(response, "protocol")
    protocol_fields = set(rows[0])
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
    return _evidence(response)


def normalize_protocol_aliases(
    response: object,
    aliases: Mapping[str, str],
) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    for source_row in response_rows(response):
        row: dict[str, object] = {}
        for decoded_name, value in source_row.items():
            semantic_name = aliases.get(decoded_name, decoded_name)
            row.setdefault(semantic_name, value)
        normalized.append(row)
    return normalized


def sample_protocol_fields(response: object) -> list[str]:
    fields: list[str] = []
    columns = getattr(response, "columns", None)
    if columns is not None:
        candidates = list(columns)
    else:
        rows = response_rows(response, limit=MAX_SAMPLE_ROWS)
        candidates = [key for row in rows for key in row]

    for candidate in candidates:
        field = _safe_protocol_field(candidate)
        if field is None or field in fields:
            continue
        fields.append(field)
        if len(fields) >= MAX_SAMPLE_FIELDS:
            break
    return fields


def response_rows(
    response: object,
    *,
    limit: int | None = None,
) -> list[dict[str, object]]:
    to_dict = getattr(response, "to_dict", None)
    if callable(to_dict):
        records = to_dict(orient="records")
        if isinstance(records, list):
            values = records if limit is None else records[:limit]
            return [_row_mapping(row) for row in values]
    if isinstance(response, Mapping):
        return [_row_mapping(response)]
    if isinstance(response, Sequence) and not isinstance(
        response, str | bytes | bytearray
    ):
        sequence_values = list(response if limit is None else response[:limit])
        return [_row_mapping(row) for row in sequence_values]
    if response is None:
        return []
    return [_row_mapping(response)]


def sanitized_error(exc: BaseException) -> str:
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


def _required_rows(response: object, endpoint: str) -> list[dict[str, object]]:
    rows = response_rows(response)
    if not rows:
        raise CapabilityUnavailable(f"{endpoint} response was empty")
    return rows


def _row_mapping(row: object) -> dict[str, object]:
    if isinstance(row, Mapping):
        return {str(key): value for key, value in row.items()}
    if is_dataclass(row) and not isinstance(row, type):
        return cast(dict[str, object], asdict(row))
    values = getattr(row, "__dict__", None)
    if isinstance(values, dict):
        return {str(key): value for key, value in values.items()}
    return {}


def _evidence(response: object) -> ValidationEvidence:
    fields = sample_protocol_fields(response)
    if not fields:
        raise CapabilityUnavailable("response had no safe protocol fields")
    return ValidationEvidence(sample_fields=fields)


def _market_number(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, Integral):
        return None
    return int(value)


def _valid_a_share_code(market: int, code: str) -> bool:
    if re.fullmatch(r"\d{6}", code) is None:
        return False
    if market == int(Market.SH):
        return code.startswith(("60", "68"))
    if market == int(Market.SZ):
        return code.startswith(("00", "30"))
    if market == int(Market.BJ):
        return code.startswith(("4", "8", "9"))
    return False


def _required_identifier(row: Mapping[str, object], field: str) -> str:
    value = row.get(field)
    if value is None:
        raise CapabilityUnavailable(f"response missing required protocol field: {field}")
    try:
        identifier = str(value).strip()
    except Exception as exc:
        raise CapabilityUnavailable(f"response {field} was invalid") from exc
    if not identifier or len(identifier) > 80:
        raise CapabilityUnavailable(f"response {field} was invalid")
    return identifier


def _validate_context(
    row: Mapping[str, object],
    *,
    expected_market: int,
    expected_code: str,
    required: bool,
) -> None:
    if required or "market" in row:
        if _market_number(row.get("market")) != expected_market:
            raise CapabilityUnavailable("response market did not match the request")
    if required or "code" in row:
        if _required_identifier(row, "code") != expected_code:
            raise CapabilityUnavailable("response symbol did not match the request")


def _finite_field(
    row: Mapping[str, object],
    alternatives: tuple[str, ...],
    *,
    minimum: float | None = None,
    positive: bool = False,
) -> float:
    selected = next((field for field in alternatives if field in row), None)
    if selected is None:
        raise CapabilityUnavailable(
            "response missing required protocol field: " + " or ".join(alternatives)
        )
    value = row[selected]
    if isinstance(value, bool) or not isinstance(value, Real):
        raise CapabilityUnavailable(f"response {selected} was not numeric")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise CapabilityUnavailable(f"response {selected} was not finite")
    if minimum is not None and numeric < minimum:
        raise CapabilityUnavailable(f"response {selected} was below its valid range")
    if positive and numeric <= 0:
        raise CapabilityUnavailable(f"response {selected} was unusable")
    return numeric


def _validate_ohlc(
    row: Mapping[str, object],
    *,
    fallback_close: float | None = None,
) -> None:
    open_price = _finite_field(row, ("open",), minimum=0.0)
    high = _finite_field(row, ("high",), minimum=0.0)
    low = _finite_field(row, ("low",), minimum=0.0)
    close = (
        _finite_field(row, ("close",), minimum=0.0)
        if "close" in row
        else fallback_close
    )
    if close is None:
        raise CapabilityUnavailable("response missing required protocol field: close")
    if high < max(open_price, low, close) or low > min(open_price, high, close):
        raise CapabilityUnavailable("response contained impossible OHLC relationships")


def _parse_datetime(value: object) -> datetime | date:
    if isinstance(value, datetime | date):
        return value
    if not isinstance(value, str) or not value.strip():
        raise CapabilityUnavailable("response datetime was missing or invalid")
    candidate = value.strip()
    try:
        if re.fullmatch(r"\d{8}", candidate):
            return datetime.strptime(candidate, "%Y%m%d")
        return datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise CapabilityUnavailable("response datetime was not parseable") from exc


def _safe_protocol_field(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    field = value.strip()
    if _PROTOCOL_FIELD_PATTERN.fullmatch(field) is None:
        return None
    if _SENSITIVE_FIELD_PATTERN.search(field):
        return None
    return field
