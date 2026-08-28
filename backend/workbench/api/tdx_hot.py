from __future__ import annotations

from fastapi import Request

from workbench.providers.tdx.provider import TdxMarketProvider


def get_hot_provider(request: Request) -> TdxMarketProvider:
    provider = getattr(request.app.state, "hot_provider", None)
    if provider is None:
        raise RuntimeError("hot TDX provider is not initialized")
    return provider


def get_hot_enhanced_client(request: Request) -> object:
    provider = get_hot_provider(request)
    enhanced = getattr(provider, "_enhanced_client", None)
    if enhanced is None:
        raise RuntimeError("enhanced TDX client is unavailable")
    return enhanced
