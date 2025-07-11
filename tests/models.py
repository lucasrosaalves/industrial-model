from __future__ import annotations

import datetime

from pydantic import Field

from industrial_model import (
    ViewInstance,
)


class CogniteDescribable(ViewInstance):
    name: str | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)


class CogniteAssetType(CogniteDescribable):
    code: str


class CogniteEquipment(CogniteDescribable):
    asset: CogniteAsset | None = None


class CogniteAsset(CogniteDescribable):
    source_created_time: datetime.datetime | None = None
    source_updated_time: datetime.datetime | None = None
    parent: CogniteAsset | None = None
    path: list[CogniteAsset] = Field(default_factory=list)
    type: CogniteAssetType | None = None
    equipment: list[CogniteEquipment] = Field(default_factory=list)
