"""APIのリクエスト・レスポンススキーマ。

フロントの src/types.ts と1対1で対応させてある。
型を変えるときは両方そろえて変えること。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RainIntensity = Literal["light", "medium", "heavy"]
RouteId = Literal["shortest", "avoid"]
DangerLevel = Literal["high", "medium", "low"]


class LatLng(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)


class RouteRequest(BaseModel):
    origin: LatLng
    destination: LatLng
    intensity: RainIntensity = "medium"


class DangerPoint(BaseModel):
    id: str
    lat: float
    lng: float
    baseWeight: float = Field(..., description="雨量に依らない、その地点の素の危険度(0-1)")
    weight: float = Field(..., description="選択中の雨量を反映した危険度(0-1)")
    displayRisk: int = Field(..., description="weight を 0-100 で表したもの")
    level: DangerLevel
    reason: str


class RouteResult(BaseModel):
    id: RouteId
    label: str
    color: str
    distanceM: int
    durationMin: int
    riskScore: int = Field(..., description="そのルートで水たまりに出くわす推定確率(0-100)")
    floodOverlapPct: int = Field(
        0, description="東京都の浸水予想で浸水が想定される区間が経路に占める割合(0-100)"
    )
    path: list[LatLng]


class SearchResult(BaseModel):
    routes: list[RouteResult]
    dangerPoints: list[DangerPoint]


class PlaceLabel(BaseModel):
    """地図上の1点に付ける呼び名。"""

    label: str
    kind: Literal["station", "landmark", "building", "street", "coordinate"]
    distanceM: int


class PlaceSuggestion(BaseModel):
    """地点検索の候補1件。"""

    label: str
    kind: Literal["station", "landmark", "building"]
    lat: float
    lng: float


class AreaInfo(BaseModel):
    """フロントが対象地域を知るための情報。"""

    bounds: dict[str, float]
    center: LatLng
    intensities: list[dict]
    hazardCount: int


class ErrorResponse(BaseModel):
    detail: str
