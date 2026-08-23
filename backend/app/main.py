"""水たまりゼロ東京 バックエンドAPI。

    uvicorn app.main:app --reload --port 8000

エンドポイント:
    GET  /api/health   起動確認
    GET  /api/area     デモ対象地域と雨量の選択肢
    POST /api/route    最短ルート・回避ルート・危険地点をまとめて返す
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import DEMO_AREA, RAIN_PROFILES
from .models import (
    AreaInfo,
    ErrorResponse,
    LatLng,
    PlaceLabel,
    PlaceSuggestion,
    RouteRequest,
    SearchResult,
)
from .service import DataNotBuiltError, OutOfAreaError, PuddleService

_state: dict[str, PuddleService] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 生成物の読み込みは数百ms かかるので、起動時に1回だけ行う
    _state["service"] = PuddleService.load()
    yield
    _state.clear()


app = FastAPI(
    title="水たまりゼロ東京 API",
    version="0.1.0",
    description="東京都の地形データから、雨の日に水たまりを避けて歩けるルートを返す。",
    lifespan=lifespan,
)

# 開発中の Vite (5173) からの呼び出しを許可する
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def service() -> PuddleService:
    return _state["service"]


@app.exception_handler(OutOfAreaError)
async def out_of_area_handler(request: Request, exc: OutOfAreaError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(DataNotBuiltError)
async def data_not_built_handler(
    request: Request, exc: DataNotBuiltError
) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.get("/api/health")
async def health() -> dict:
    loaded = "service" in _state
    return {
        "status": "ok" if loaded else "loading",
        "hazardCount": len(service().hazard_points) if loaded else 0,
    }


@app.get("/api/area", response_model=AreaInfo)
async def area() -> AreaInfo:
    """デモ対象地域の範囲と、雨量セレクタの選択肢を返す。"""
    return AreaInfo(
        bounds={
            "minLat": DEMO_AREA.min_lat,
            "minLng": DEMO_AREA.min_lon,
            "maxLat": DEMO_AREA.max_lat,
            "maxLng": DEMO_AREA.max_lon,
        },
        center=LatLng(
            lat=(DEMO_AREA.min_lat + DEMO_AREA.max_lat) / 2,
            lng=(DEMO_AREA.min_lon + DEMO_AREA.max_lon) / 2,
        ),
        intensities=[
            {"value": key, "label": profile["label"], "mmPerHour": profile["mm_per_hour"]}
            for key, profile in RAIN_PROFILES.items()
        ],
        hazardCount=len(service().hazard_points),
    )


@app.get(
    "/api/place",
    response_model=PlaceLabel,
    responses={400: {"model": ErrorResponse}},
)
async def place(lat: float, lng: float) -> PlaceLabel:
    """地図上の1点に付ける呼び名を返す。座標のままだと画面で伝わらないため。"""
    if "service" not in _state:
        raise HTTPException(status_code=503, detail="データを読み込み中です")
    return service().describe_point(LatLng(lat=lat, lng=lng))


@app.get("/api/search", response_model=list[PlaceSuggestion])
async def search_places(q: str, limit: int = 8) -> list[PlaceSuggestion]:
    """地点名で候補を返す。入力欄の補完に使う。"""
    if "service" not in _state:
        raise HTTPException(status_code=503, detail="データを読み込み中です")
    return service().suggest_places(q, max(1, min(limit, 20)))


@app.post(
    "/api/route",
    response_model=SearchResult,
    responses={400: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def route(request: RouteRequest) -> SearchResult:
    """出発地・目的地・雨の強さから、2本のルートと危険地点を返す。"""
    if "service" not in _state:
        raise HTTPException(status_code=503, detail="データを読み込み中です")
    return service().search(request.origin, request.destination, request.intensity)
