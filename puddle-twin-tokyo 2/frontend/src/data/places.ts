import type { LatLng } from '../types';
import { haversineMeters } from '../utils/geo';

/** 地図の初期表示。デモ対象地域（東京駅〜有楽町〜日比谷〜京橋）の中心。 */
export const DEFAULT_CENTER: LatLng = { lat: 35.6785, lng: 139.7655 };
export const DEFAULT_ZOOM = 15.5;

export const KNOWN_PLACES: { name: string; lat: number; lng: number }[] = [
  { name: '東京駅', lat: 35.6812, lng: 139.7671 },
  { name: '有楽町駅', lat: 35.6751, lng: 139.7628 },
  { name: '銀座一丁目駅', lat: 35.6725, lng: 139.7663 },
  { name: '日比谷駅', lat: 35.674, lng: 139.7595 },
  { name: '京橋駅', lat: 35.6777, lng: 139.7706 },
];

const NEAR_THRESHOLD_M = 120;

/** Very small stand-in for reverse geocoding, used only to label picked points. */
export function labelForPoint(point: LatLng): string {
  for (const place of KNOWN_PLACES) {
    if (haversineMeters(point, place) < NEAR_THRESHOLD_M) return place.name;
  }
  return `地点 (${point.lat.toFixed(4)}, ${point.lng.toFixed(4)})`;
}
