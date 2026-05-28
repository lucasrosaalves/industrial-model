from __future__ import annotations

import datetime
from typing import TypedDict

from industrial_model import InstanceId


class StringFilter(TypedDict, total=False):
    eq: str
    prefix: str
    in_: list[str]
    exists: bool


class StringListFilter(TypedDict, total=False):
    containsAny: list[str]
    containsAll: list[str]


class IntFilter(TypedDict, total=False):
    eq: int
    gt: int
    gte: int
    lt: int
    lte: int
    in_: list[int]
    exists: bool


class FloatFilter(TypedDict, total=False):
    eq: float
    gt: float
    gte: float
    lt: float
    lte: float
    in_: list[float]
    exists: bool


class BoolFilter(TypedDict, total=False):
    eq: bool
    exists: bool


class InstanceIdFilter(TypedDict, total=False):
    eq: InstanceId
    in_: list[InstanceId]
    exists: bool


class InstanceIdListFilter(TypedDict, total=False):
    containsAny: list[InstanceId]
    containsAll: list[InstanceId]


class DatetimeFilter(TypedDict, total=False):
    eq: datetime.datetime
    gt: datetime.datetime
    gte: datetime.datetime
    lt: datetime.datetime
    lte: datetime.datetime
    in_: list[datetime.datetime]
    exists: bool


class DateFilter(TypedDict, total=False):
    eq: datetime.date
    gt: datetime.date
    gte: datetime.date
    lt: datetime.date
    lte: datetime.date
    in_: list[datetime.date]
    exists: bool
