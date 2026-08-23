import { haversineMeters } from '../utils/geo';
import { nearestStreetName } from './graph';
import type { LatLng, PlaceLabel, PlaceSuggestion } from '../types';
import type { EngineData, Place } from './data';

/**
 * 座標に呼び名を付ける／地点名で検索する。
 * バックエンド(app/places.py)と同じ規則で動かしている。
 */

/** 駅は、この距離より近ければ「付近」を付けずに駅名だけで呼ぶ。 */
const EXACT_HIT_M = 60;
/** 駅がこの距離内にあるときは、より近い施設があっても駅名を優先する。 */
const STATION_PRIORITY_M = 150;

const KIND_ORDER: Record<Place['kind'], number> = { station: 0, landmark: 1, building: 2 };

export function labelForPoint(data: EngineData, point: LatLng): PlaceLabel {
  const radii = data.settings.placeSearchRadiusM;

  // 種別ごとに「近い」の意味が違うので、半径で割った値どうしで比べる。
  // 300m先の駅と20m先のビルなら、後者のほうが地点の説明として役に立つ。
  const candidates: { score: number; name: string; kind: PlaceLabel['kind']; distanceM: number }[] = [];

  for (const place of data.places) {
    if (Math.abs(place.lat - point.lat) > 0.004 || Math.abs(place.lon - point.lng) > 0.005) continue;
    const distanceM = haversineMeters(point, { lat: place.lat, lng: place.lon });
    const radius = radii[place.kind];
    if (distanceM <= radius) {
      candidates.push({ score: distanceM / radius, name: place.name, kind: place.kind, distanceM });
    }
  }

  const street = nearestStreetName(data.graph, point, radii.street);
  if (street) {
    candidates.push({
      score: street.distanceM / radii.street,
      name: street.name,
      kind: 'street',
      distanceM: street.distanceM,
    });
  }

  if (candidates.length === 0) {
    return {
      label: `地点 (${point.lat.toFixed(4)}, ${point.lng.toFixed(4)})`,
      kind: 'coordinate',
      distanceM: 0,
    };
  }

  // 駅のそばなら、人はその駅名で場所を言う
  const nearbyStations = candidates.filter(
    (c) => c.kind === 'station' && c.distanceM <= STATION_PRIORITY_M,
  );
  const pool = nearbyStations.length > 0 ? nearbyStations : candidates;
  const best = pool.reduce((a, b) => (b.score < a.score ? b : a));

  const label =
    best.kind === 'station' && best.distanceM <= EXACT_HIT_M ? best.name : `${best.name} 付近`;
  return { label, kind: best.kind, distanceM: Math.round(best.distanceM) };
}

export function searchPlaces(data: EngineData, query: string, limit = 8): PlaceSuggestion[] {
  const needle = query.trim().toLowerCase();
  if (needle.length === 0) return [];

  const hits = data.places
    .filter((place) => place.name.toLowerCase().includes(needle))
    .map((place) => ({
      place,
      // 前方一致 → 駅・施設・ビルの順 → 名前の短い順。
      // 短い名前ほど、その地域を代表する呼び名であることが多い。
      prefix: place.name.toLowerCase().startsWith(needle) ? 0 : 1,
      kind: KIND_ORDER[place.kind],
    }))
    .sort(
      (a, b) =>
        a.prefix - b.prefix || a.kind - b.kind || a.place.name.length - b.place.name.length,
    );

  return hits.slice(0, limit).map(({ place }) => ({
    label: place.name,
    kind: place.kind,
    lat: place.lat,
    lng: place.lon,
  }));
}
