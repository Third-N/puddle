"""APIの振る舞いを、フロントの型に合っているかという観点で確認する。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

TOKYO_STATION = {"lat": 35.6812, "lng": 139.7671}
YURAKUCHO_STATION = {"lat": 35.6751, "lng": 139.7628}
HIBIYA = {"lat": 35.6740, "lng": 139.7595}
KYOBASHI = {"lat": 35.6777, "lng": 139.7706}
OSAKA_STATION = {"lat": 34.7024, "lng": 135.4959}
DEMO_AREA_BOUNDS = {"minLat": 35.6700, "minLng": 139.7570, "maxLat": 35.6870, "maxLng": 139.7760}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def search(client, origin, destination, intensity="medium"):
    response = client.post(
        "/api/route",
        json={"origin": origin, "destination": destination, "intensity": intensity},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["hazardCount"] > 0


def test_area(client):
    body = client.get("/api/area").json()
    assert [i["value"] for i in body["intensities"]] == ["light", "medium", "heavy"]
    assert body["bounds"]["minLat"] < body["center"]["lat"] < body["bounds"]["maxLat"]


def test_route_shape_matches_frontend_types(client):
    body = search(client, TOKYO_STATION, YURAKUCHO_STATION)

    assert {route["id"] for route in body["routes"]} == {"shortest", "avoid"}
    for route in body["routes"]:
        assert route["label"] and route["color"].startswith("#")
        assert route["distanceM"] > 0
        assert route["durationMin"] >= 1
        assert 0 <= route["riskScore"] <= 100
        assert len(route["path"]) >= 2
        assert set(route["path"][0]) == {"lat", "lng"}

    assert body["dangerPoints"], "ルート周辺の危険地点が1件も返っていない"
    for point in body["dangerPoints"]:
        assert 0 <= point["baseWeight"] <= 1
        assert 0 <= point["weight"] <= 1
        assert point["displayRisk"] == round(point["weight"] * 100)
        assert point["level"] in {"high", "medium", "low"}
        assert point["reason"]


def test_route_ends_match_the_requested_points(client):
    """線がマーカーから離れないよう、両端はクリック地点そのものにしている。"""
    body = search(client, HIBIYA, KYOBASHI)
    for route in body["routes"]:
        assert route["path"][0] == HIBIYA
        assert route["path"][-1] == KYOBASHI


def test_avoid_route_is_safer_and_not_shorter(client):
    """回避ルートは、最短ルートより危険度が下がり、距離は縮まない。"""
    body = search(client, HIBIYA, KYOBASHI)
    shortest = next(r for r in body["routes"] if r["id"] == "shortest")
    avoid = next(r for r in body["routes"] if r["id"] == "avoid")

    assert avoid["riskScore"] < shortest["riskScore"]
    assert avoid["distanceM"] >= shortest["distanceM"]


def test_heavier_rain_raises_risk(client):
    """同じ経路でも、雨が強いほど危険度は上がる。"""
    scores = []
    for intensity in ("light", "medium", "heavy"):
        body = search(client, HIBIYA, KYOBASHI, intensity)
        shortest = next(r for r in body["routes"] if r["id"] == "shortest")
        scores.append(shortest["riskScore"])
    assert scores[0] < scores[1] < scores[2]


def test_danger_points_scale_with_rain(client):
    light = search(client, HIBIYA, KYOBASHI, "light")["dangerPoints"]
    heavy = search(client, HIBIYA, KYOBASHI, "heavy")["dangerPoints"]
    by_id = {p["id"]: p for p in light}
    for point in heavy:
        if point["id"] in by_id:
            assert point["weight"] >= by_id[point["id"]]["weight"]
            assert point["baseWeight"] == by_id[point["id"]]["baseWeight"]


def test_outside_demo_area_returns_400(client):
    response = client.post(
        "/api/route",
        json={
            "origin": OSAKA_STATION,
            "destination": YURAKUCHO_STATION,
            "intensity": "medium",
        },
    )
    assert response.status_code == 400
    assert "対象地域" in response.json()["detail"]


def test_same_point_returns_400(client):
    response = client.post(
        "/api/route",
        json={
            "origin": TOKYO_STATION,
            "destination": TOKYO_STATION,
            "intensity": "medium",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"]


def test_unknown_intensity_is_rejected(client):
    response = client.post(
        "/api/route",
        json={
            "origin": TOKYO_STATION,
            "destination": YURAKUCHO_STATION,
            "intensity": "typhoon",
        },
    )
    assert response.status_code == 422


IMPERIAL_MOAT = {"lat": 35.6838, "lng": 139.7580}  # 対象地域内だが、歩ける道から140m以上ある


def test_place_names_a_station(client):
    body = client.get("/api/place", params=TOKYO_STATION).json()
    assert body["label"] == "東京駅"
    assert body["kind"] == "station"
    assert body["distanceM"] < 100


def test_place_falls_back_to_something_readable(client):
    """駅から離れた地点でも、座標そのままにはしない。"""
    body = client.get("/api/place", params={"lat": 35.6790, "lng": 139.7620}).json()
    assert body["kind"] in {"landmark", "building", "street"}
    assert body["label"].endswith("付近")


def test_place_outside_area_returns_400(client):
    response = client.get("/api/place", params=OSAKA_STATION)
    assert response.status_code == 400
    assert "対象地域" in response.json()["detail"]


def test_point_far_from_any_road_is_rejected(client):
    """道から離れすぎた地点は、無理に寄せずに選び直してもらう。"""
    response = client.post(
        "/api/route",
        json={
            "origin": IMPERIAL_MOAT,
            "destination": YURAKUCHO_STATION,
            "intensity": "medium",
        },
    )
    assert response.status_code == 400
    assert "歩ける道" in response.json()["detail"]


def test_search_finds_stations_first(client):
    body = client.get("/api/search", params={"q": "東京"}).json()
    assert body, "候補が1件も返っていない"
    assert body[0]["label"] == "東京駅"
    assert body[0]["kind"] == "station"
    for hit in body:
        assert "東京" in hit["label"]
        assert DEMO_AREA_BOUNDS["minLat"] <= hit["lat"] <= DEMO_AREA_BOUNDS["maxLat"]


def test_search_with_empty_query_returns_nothing(client):
    assert client.get("/api/search", params={"q": "   "}).json() == []


def test_routes_report_overlap_with_tokyo_flood_forecast(client):
    """東京都の浸水予想と重なる区間の割合を返す。回避ルートのほうが小さいはず。"""
    body = search(client, TOKYO_STATION, YURAKUCHO_STATION)
    shortest = next(r for r in body["routes"] if r["id"] == "shortest")
    avoid = next(r for r in body["routes"] if r["id"] == "avoid")

    assert 0 <= shortest["floodOverlapPct"] <= 100
    assert 0 <= avoid["floodOverlapPct"] <= 100
    assert avoid["floodOverlapPct"] <= shortest["floodOverlapPct"]


def test_hazard_reason_cites_tokyo_data_when_available(client):
    """都の予想が付いている危険地点は、その根拠を文面に出す。"""
    body = search(client, TOKYO_STATION, YURAKUCHO_STATION, "heavy")
    reasons = [p["reason"] for p in body["dangerPoints"]]
    assert any("東京都の浸水予想" in r for r in reasons)
