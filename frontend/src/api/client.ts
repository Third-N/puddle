import type {
  AreaInfo,
  LatLng,
  PlaceLabel,
  PlaceSuggestion,
  RainIntensity,
  SearchResult,
} from '../types';

/**
 * データ取得の唯一の入り口。
 *
 * 2つの動かし方がある。
 *   通常   … FastAPIバックエンドを呼ぶ（開発時は /api をViteがプロキシ）
 *   静的   … 生成済みデータを読み、経路探索をブラウザで行う（VITE_STATIC_DATA=1）
 *
 * 静的版はGitHub Pagesのような静的ホスティングだけで動く。サーバーを
 * 立てずに誰でも触れるURLを出せるので、デモの公開に使っている。
 * 呼び出し側からはどちらも同じ関数に見えるようにしてある。
 */
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api';
const STATIC_MODE = import.meta.env.VITE_STATIC_DATA === '1';

export class ApiError extends Error {}

export type { AreaInfo, PlaceLabel };

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

/** 静的版で使う計算エンジン。必要になったときだけ読み込む。 */
async function engine() {
  const [{ loadEngineData }, routing, places] = await Promise.all([
    import('../engine/data'),
    import('../engine/routing'),
    import('../engine/places'),
  ]);
  return { data: await loadEngineData(), routing, places };
}

function toApiError(error: unknown): never {
  if (error instanceof DOMException && error.name === 'AbortError') throw error;
  throw new ApiError(error instanceof Error ? error.message : 'ルート検索に失敗しました');
}

/** 出発地・目的地・雨の強さから、最短ルートと回避ルートを取得する。 */
export async function fetchSearchResult(
  origin: LatLng,
  destination: LatLng,
  intensity: RainIntensity,
  signal?: AbortSignal,
): Promise<SearchResult> {
  if (STATIC_MODE) {
    try {
      const { data, routing } = await engine();
      return routing.computeRoutes(data, origin, destination, intensity);
    } catch (error) {
      toApiError(error);
    }
  }

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

/** 地図上の1点に付ける呼び名を取得する。 */
export async function fetchPlaceLabel(
  point: LatLng,
  signal?: AbortSignal,
): Promise<PlaceLabel> {
  if (STATIC_MODE) {
    const { data, places } = await engine();
    return places.labelForPoint(data, point);
  }
  const params = new URLSearchParams({ lat: String(point.lat), lng: String(point.lng) });
  const response = await fetch(`${API_BASE_URL}/place?${params}`, { signal });
  if (!response.ok) throw new ApiError(await readErrorMessage(response));
  return (await response.json()) as PlaceLabel;
}

/** 地点名で候補を引く。入力欄の補完に使う。 */
export async function searchPlaces(
  query: string,
  signal?: AbortSignal,
): Promise<PlaceSuggestion[]> {
  if (STATIC_MODE) {
    const { data, places } = await engine();
    return places.searchPlaces(data, query);
  }
  const params = new URLSearchParams({ q: query, limit: '8' });
  const response = await fetch(`${API_BASE_URL}/search?${params}`, { signal });
  if (!response.ok) throw new ApiError(await readErrorMessage(response));
  return (await response.json()) as PlaceSuggestion[];
}

/** バックエンドが応答するかどうかだけを見る。画面を開いた時点の確認に使う。 */
export async function fetchHealth(signal?: AbortSignal): Promise<{ status: string }> {
  if (STATIC_MODE) {
    await engine();
    return { status: 'ok' };
  }
  const response = await fetch(`${API_BASE_URL}/health`, { signal });
  if (!response.ok) throw new ApiError(await readErrorMessage(response));
  return (await response.json()) as { status: string };
}

/** デモ対象地域の範囲。地図の初期表示や範囲外チェックに使える。 */
export async function fetchAreaInfo(signal?: AbortSignal): Promise<AreaInfo> {
  if (STATIC_MODE) {
    const { data } = await engine();
    const area = data.settings.demoArea;
    return {
      bounds: area,
      center: { lat: (area.minLat + area.maxLat) / 2, lng: (area.minLng + area.maxLng) / 2 },
      intensities: Object.entries(data.settings.rainProfiles).map(([value, profile]) => ({
        value: value as RainIntensity,
        label: profile.label,
        mmPerHour: profile.mmPerHour,
      })),
      hazardCount: data.hazards.length,
    };
  }
  const response = await fetch(`${API_BASE_URL}/area`, { signal });
  if (!response.ok) throw new ApiError(await readErrorMessage(response));
  return (await response.json()) as AreaInfo;
}
