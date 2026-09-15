"""TDX sector cloud (板块云图) real_hq fund flow provider."""
from __future__ import annotations

import base64
import json
import re
import struct
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Iterable

YUNTU_PAGE_REFERER = "https://data.tdx.com.cn/www/pages/tdx-yuntu/page-dp.html"
REAL_HQ_URL = "https://data.tdx.com.cn/yuntujsdata/real_hq.js"
REAL_HQ_INTERVAL_MS = 10_000
WAN_YUAN_TO_YUAN = 10_000.0


@dataclass(frozen=True, slots=True)
class YuntuSectorSnapshot:
    main_yuan: float
    change_pct: float


@dataclass(frozen=True, slots=True)
class YuntuStockQuote:
    stockcode: str
    setcode: int
    dqzf: float
    f_amo_sum_wan: float
    now: float
    z_close: float


def _read_varint(buffer: bytes, offset: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while offset < len(buffer):
        byte = buffer[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, offset
        shift += 7
    raise ValueError("truncated varint")


def _encode_varint(value: int) -> bytes:
    if value < 0:
        raise ValueError("unsigned varint required")
    chunks: list[int] = []
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            chunks.append(byte | 0x80)
        else:
            chunks.append(byte)
            break
    return bytes(chunks)


def _encode_float_field(field_number: int, value: float) -> bytes:
    tag = _encode_varint((field_number << 3) | 5)
    return tag + struct.pack("<f", float(value))


def _encode_string_field(field_number: int, value: str) -> bytes:
    encoded = value.encode("utf-8")
    tag = _encode_varint((field_number << 3) | 2)
    return tag + _encode_varint(len(encoded)) + encoded


def _encode_uint32_field(field_number: int, value: int) -> bytes:
    tag = _encode_varint((field_number << 3) | 0)
    return tag + _encode_varint(int(value))


def encode_gg_data(
    *,
    setcode: int,
    stockcode: str,
    dqzf: float = 0.0,
    f_amo_sum_wan: float = 0.0,
    now: float = 0.0,
    z_close: float = 0.0,
) -> bytes:
    return b"".join(
        (
            _encode_uint32_field(1, setcode),
            _encode_string_field(2, stockcode),
            _encode_float_field(4, z_close),
            _encode_float_field(5, now),
            _encode_float_field(6, dqzf),
            _encode_float_field(11, f_amo_sum_wan),
        )
    )


def encode_gg_list_from_items(items: Iterable[dict[str, object]]) -> bytes:
    chunks: list[bytes] = []
    for item in items:
        row = encode_gg_data(
            setcode=int(item.get("setcode", 1)),
            stockcode=str(item["stockcode"]),
            dqzf=float(item.get("dqzf", 0.0) or 0.0),
            f_amo_sum_wan=float(item.get("f_amo_sum_wan", 0.0) or 0.0),
            now=float(item.get("now", 0.0) or 0.0),
            z_close=float(item.get("z_close", 0.0) or 0.0),
        )
        tag = _encode_varint((1 << 3) | 2)
        chunks.append(tag + _encode_varint(len(row)) + row)
    return b"".join(chunks)


def _decode_gg_data(buffer: bytes) -> YuntuStockQuote:
    offset = 0
    setcode = 1
    stockcode = ""
    dqzf = 0.0
    f_amo_sum_wan = 0.0
    now = 0.0
    z_close = 0.0
    while offset < len(buffer):
        tag, offset = _read_varint(buffer, offset)
        field_number = tag >> 3
        wire_type = tag & 0x07
        if wire_type == 0:
            value, offset = _read_varint(buffer, offset)
            if field_number == 1:
                setcode = value
        elif wire_type == 2:
            length, offset = _read_varint(buffer, offset)
            chunk = buffer[offset : offset + length]
            offset += length
            if field_number == 2:
                stockcode = chunk.decode("utf-8", errors="replace")
        elif wire_type == 5:
            value = struct.unpack("<f", buffer[offset : offset + 4])[0]
            offset += 4
            if field_number == 4:
                z_close = value
            elif field_number == 5:
                now = value
            elif field_number == 6:
                dqzf = value
            elif field_number == 11:
                f_amo_sum_wan = value
        else:
            raise ValueError(f"unsupported wire type {wire_type}")
    return YuntuStockQuote(
        stockcode=stockcode,
        setcode=setcode,
        dqzf=dqzf,
        f_amo_sum_wan=f_amo_sum_wan,
        now=now,
        z_close=z_close,
    )


def decode_gg_list(buffer: bytes) -> list[YuntuStockQuote]:
    offset = 0
    rows: list[YuntuStockQuote] = []
    while offset < len(buffer):
        tag, offset = _read_varint(buffer, offset)
        field_number = tag >> 3
        wire_type = tag & 0x07
        if wire_type != 2 or field_number != 1:
            raise ValueError("unexpected GGList field")
        length, offset = _read_varint(buffer, offset)
        chunk = buffer[offset : offset + length]
        offset += length
        rows.append(_decode_gg_data(chunk))
    return rows


def parse_yuntu_script_array(body: str, variable_name: str) -> list[str]:
    marker = f"var {variable_name}"
    start = body.find(marker)
    if start < 0:
        marker = variable_name
        start = body.find(marker)
    if start < 0:
        raise ValueError(f"{variable_name} not found in script body")
    eq = body.find("=", start)
    if eq < 0:
        raise ValueError(f"{variable_name} assignment not found")
    array_start = body.find("[", eq)
    if array_start < 0:
        raise ValueError(f"{variable_name} array not found")
    depth = 0
    for index in range(array_start, len(body)):
        char = body[index]
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return json.loads(body[array_start : index + 1])
    raise ValueError(f"{variable_name} array is truncated")


def decode_real_hq_script(body: str) -> list[YuntuStockQuote]:
    chunks = parse_yuntu_script_array(body, "G_REAL_HQ")
    rows: list[YuntuStockQuote] = []
    for chunk in chunks:
        if not chunk:
            continue
        payload = base64.b64decode(chunk)
        rows.extend(decode_gg_list(payload))
    return rows


def _fetch_with_urllib(url: str, referer: str, timeout_seconds: float) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "Referer": referer,
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return response.read().decode("utf-8", "replace")


def _fetch_with_curl_cffi(url: str, referer: str, timeout_seconds: float) -> str:
    from curl_cffi import requests

    response = requests.get(
        url,
        headers={"Referer": referer},
        impersonate="chrome",
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    return response.text


def fetch_real_hq_script(
    *,
    url: str = REAL_HQ_URL,
    referer: str = YUNTU_PAGE_REFERER,
    timeout_seconds: float = 15.0,
    ver: int | None = None,
) -> str:
    version = ver if ver is not None else int(time.time() * 1000) // REAL_HQ_INTERVAL_MS
    full_url = f"{url}?ver={version}"
    try:
        return _fetch_with_urllib(full_url, referer, timeout_seconds)
    except urllib.error.HTTPError:
        return _fetch_with_curl_cffi(full_url, referer, timeout_seconds)


def build_sector_main_map(
    rows: Iterable[YuntuStockQuote],
    sector_ids: Iterable[str] | None = None,
) -> dict[str, float]:
    return {
        sector_id: snapshot.main_yuan
        for sector_id, snapshot in build_sector_snapshot_map(rows, sector_ids).items()
    }


def build_sector_snapshot_map(
    rows: Iterable[YuntuStockQuote],
    sector_ids: Iterable[str] | None = None,
) -> dict[str, YuntuSectorSnapshot]:
    wanted = {str(sector_id).strip() for sector_id in sector_ids} if sector_ids else None
    result: dict[str, YuntuSectorSnapshot] = {}
    for row in rows:
        code = row.stockcode.strip()
        if not code:
            continue
        if wanted is not None and code not in wanted:
            continue
        result[code] = YuntuSectorSnapshot(
            main_yuan=row.f_amo_sum_wan * WAN_YUAN_TO_YUAN,
            change_pct=round(row.dqzf * 100.0, 2),
        )
    return result


def fetch_yuntu_sector_snapshots(
    sector_ids: Iterable[str],
    *,
    timeout_seconds: float = 15.0,
) -> dict[str, YuntuSectorSnapshot]:
    body = fetch_real_hq_script(timeout_seconds=timeout_seconds)
    rows = decode_real_hq_script(body)
    return build_sector_snapshot_map(rows, sector_ids)


def fetch_yuntu_sector_main_map(
    sector_ids: Iterable[str],
    *,
    timeout_seconds: float = 15.0,
) -> dict[str, float]:
    return {
        sector_id: snapshot.main_yuan
        for sector_id, snapshot in fetch_yuntu_sector_snapshots(
            sector_ids,
            timeout_seconds=timeout_seconds,
        ).items()
    }


def main_yuan_from_wan(value_wan: float) -> float:
    return float(value_wan) * WAN_YUAN_TO_YUAN


def is_sector_index_code(code: str) -> bool:
    return bool(re.fullmatch(r"88\d{4}", code.strip()))
