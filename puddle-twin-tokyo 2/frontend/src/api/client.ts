import type { LatLng, RainIntensity, SearchResult } from '../types';

/**
 * バックエンド(FastAPI)への唯一の入り口。
 *
 * 開発中は vite.config.ts のプロキシで /api が http://localhost:8000 に転送される。
 * 別ホストに立てる場合は .env に VITE_API_BASE_URL を設定する。
 */
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api';

export class ApiError extends Error {}

/** バックエンドは失敗時に { detail: "..." } を返す。その文言をそのまま画面に出す。 */
async function readErrorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === 'string') return body.detail;
    // pydantic のバリデーションエラーは detail が配列になる
    if (Array.isArray(body?.detail) && body.detail[0]?.msg) return body.detail[0].msg;
  } catch {
    // JSON でないレスポンスはここに来る
  }
  if (response.status === 503) return 'サーバーの準備ができていません。しばらくしてからお試しください';
  // 開発中は、APIが落ちているとViteのプロキシが 500 を返す。
  // 「HTTP 500」だけ出しても原因が分からないので、確認先まで書く。
  if (response.status >= 500) {
    return 'バックエンドに接続できません。APIサーバー（uvicorn）が起動しているか確認してください';
  }
  return `ルート検索に失敗しました (HTTP ${response.status})`;
}

export interface AreaInfo {
  bounds: { minLat: number; minLng: number; maxLat: number; maxLng: number };
  center: LatLng;
  intensities: { value: RainIntensity; label: string; mmPerHour: number }[];
  hazardCount: number;
}

/** 出発地・目的地・雨の強さから、最短ルートと回避ルートを取得する。 */
export async function fetchSearchResult(
  origin: LatLng,
  destination: LatLng,
  intensity: RainIntensity,
  signal?: AbortSignal,
): Promise<SearchResult> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/route`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ origin, destination, intensity }),
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError('バックエンドに接続できません。APIサーバーが起動しているか確認してください');
  }

  if (!response.ok) {
    throw new ApiError(await readErrorMessage(response));
  }

  return (await response.json()) as SearchResult;
}

export interface PlaceLabel {
  label: string;
  kind: 'station' | 'landmark' | 'building' | 'street' | 'coordinate';
  distanceM: number;
}

/**
 * 地図上の1点に付ける呼び名を取得する。
 * バックエンドがOSMの駅・施設・ビル・道路名から決める。
 */
export async function fetchPlaceLabel(
  point: LatLng,
  signal?: AbortSignal,
): Promise<PlaceLabel> {
  const params = new URLSearchParams({ lat: String(point.lat), lng: String(point.lng) });
  const response = await fetch(`${API_BASE_URL}/place?${params}`, { signal });
  if (!response.ok) throw new ApiError(await readErrorMessage(response));
  return (await response.json()) as PlaceLabel;
}

/** バックエンドが応答するかどうかだけを見る。画面を開いた時点の確認に使う。 */
export async function fetchHealth(signal?: AbortSignal): Promise<{ status: string }> {
  const response = await fetch(`${API_BASE_URL}/health`, { signal });
  if (!response.ok) throw new ApiError(await readErrorMessage(response));
  return (await response.json()) as { status: string };
}

/** デモ対象地域の範囲。地図の初期表示や範囲外チェックに使える。 */
export async function fetchAreaInfo(signal?: AbortSignal): Promise<AreaInfo> {
  const response = await fetch(`${API_BASE_URL}/area`, { signal });
  if (!response.ok) throw new ApiError(await readErrorMessage(response));
  return (await response.json()) as AreaInfo;
}
