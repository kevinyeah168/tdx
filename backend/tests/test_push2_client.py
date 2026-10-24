from __future__ import annotations

import pytest

from workbench.providers.eastmoney.push2_client import (
    append_jsonp_params,
    parse_push2_payload,
)


def test_parse_push2_payload_json() -> None:
    payload = parse_push2_payload('{"rc":0,"data":{"diff":[{"f12":"600519"}]}}')
    assert payload["rc"] == 0
    assert payload["data"]["diff"][0]["f12"] == "600519"


def test_parse_push2_payload_jsonp() -> None:
    payload = parse_push2_payload('jQuery123_456({"rc":0,"data":{"total":1,"diff":[]}});')
    assert payload["rc"] == 0
    assert payload["data"]["total"] == 1


def test_parse_push2_payload_invalid() -> None:
    with pytest.raises(RuntimeError, match="not JSON or JSONP"):
        parse_push2_payload("not-json")


def test_append_jsonp_params_adds_cb_and_cache_buster() -> None:
    params = append_jsonp_params({"pn": "1"})
    assert params["pn"] == "1"
    assert params["cb"].startswith("jQuery3510")
    assert params["_"].isdigit()
