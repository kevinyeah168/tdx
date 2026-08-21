from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from workbench.domain import ProviderCapabilities


PROBE_SCHEMA_VERSION: Literal["1.0"] = "1.0"
PROBE_VERSION: Literal["3.1.0"] = "3.1.0"
SAMPLE_SYMBOL: Literal["SH600000"] = "SH600000"

CAPABILITY_NAMES = (
    "security_catalog",
    "board_list",
    "board_members",
    "official_funds",
    "quotes",
    "transactions",
    "minute_data",
    "bars",
    "order_book",
)

CapabilityName = Literal[
    "security_catalog",
    "board_list",
    "board_members",
    "official_funds",
    "quotes",
    "transactions",
    "minute_data",
    "bars",
    "order_book",
]
SourceStatus = Literal["succeeded", "failed"]
ProtocolField = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$")]


class ProbeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class DiscoveredBoard(ProbeModel):
    id: Annotated[str, Field(min_length=1, max_length=80)]
    name: Annotated[str, Field(min_length=1, max_length=80)]

    @field_validator("id", "name")
    @classmethod
    def strip_nonblank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("board identity must not be blank")
        return stripped


class SourceOutcome(ProbeModel):
    source: Annotated[str, Field(min_length=1, max_length=120)]
    attempted: Literal[True] = True
    status: SourceStatus
    evidence: list[ProtocolField] = Field(default_factory=list, max_length=12)
    error: Annotated[str, Field(min_length=1, max_length=200)] | None = None

    @field_validator("source")
    @classmethod
    def strip_source(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("source must not be blank")
        return stripped

    @model_validator(mode="after")
    def validate_status(self) -> "SourceOutcome":
        if self.status == "succeeded" and self.error is not None:
            raise ValueError("succeeded source cannot carry an error")
        if self.status == "failed" and self.error is None:
            raise ValueError("failed source requires an error")
        if len(set(self.evidence)) != len(self.evidence):
            raise ValueError("source evidence fields must be unique")
        return self


class CapabilitySourceOutcomes(ProbeModel):
    security_catalog: list[SourceOutcome] = Field(min_length=1)
    board_list: list[SourceOutcome] = Field(min_length=1)
    board_members: list[SourceOutcome] = Field(min_length=1)
    official_funds: list[SourceOutcome] = Field(min_length=1)
    quotes: list[SourceOutcome] = Field(min_length=1)
    transactions: list[SourceOutcome] = Field(min_length=1)
    minute_data: list[SourceOutcome] = Field(min_length=1)
    bars: list[SourceOutcome] = Field(min_length=1)
    order_book: list[SourceOutcome] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_sources(self) -> "CapabilitySourceOutcomes":
        for capability in CAPABILITY_NAMES:
            outcomes = getattr(self, capability)
            labels = [outcome.source for outcome in outcomes]
            if len(labels) != len(set(labels)):
                raise ValueError(
                    f"{capability} source outcome labels must be unique"
                )
        return self


class ProbeManifest(ProbeModel):
    schema_version: Literal["1.0"]
    probe_version: Literal["3.1.0"]
    captured_at: datetime
    easy_tdx_version: Annotated[str, Field(min_length=1, max_length=40)]
    sample_symbol: Literal["SH600000"]
    discovered_board: DiscoveredBoard | None
    source_outcomes: CapabilitySourceOutcomes

    @field_validator("captured_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("captured_at must be timezone-aware")
        return value


class TdxCapabilityReport(ProbeModel):
    manifest: ProbeManifest
    capabilities: ProviderCapabilities
