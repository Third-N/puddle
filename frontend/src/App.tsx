import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { SearchPanel } from './components/SearchPanel';
import { MapView } from './components/MapView';
import { labelForPoint } from './data/places';
import { ApiError, fetchHealth, fetchPlaceLabel, fetchSearchResult } from './api/client';
import type {
  Banner,
  DangerPoint,
  LatLng,
  RainIntensity,
  SearchResult,
  SearchStatus,
} from './types';
import './App.css';

type PickStage = 'origin' | 'destination' | 'done';

/** これ未満の差は誤差の範囲とみなし、回避ルートを勧めない。 */
const MEANINGFUL_RISK_REDUCTION = 3;

/**
 * 選んだ地点の呼び名を、バックエンドから取ってくる。
 *
 * 応答を待つ間は座標のまま出しておき、届いたら差し替える。
 * 名前が出るまで欄が空になると、選べたのかどうか分からなくなるため。
 */
function usePlaceLabel(point: LatLng | null, chosenName: string | null): string | null {
  const [label, setLabel] = useState<string | null>(null);

  useEffect(() => {
    if (!point) {
      setLabel(null);
      return;
    }
    // 検索で名前を選んだ場合は、その名前をそのまま出す。
    // 座標から引き直すと、選んだ名前と違うものが表示されて混乱する。
    if (chosenName) {
      setLabel(chosenName);
      return;
    }
    setLabel(labelForPoint(point));

    const controller = new AbortController();
    fetchPlaceLabel(point, controller.signal)
      .then((place) => setLabel(place.label))
      // 取れなければ座標表示のままでよい。ここで画面を止める必要はない。
      .catch(() => undefined);

    return () => controller.abort();
  }, [point?.lat, point?.lng, chosenName]);

  return label;
}

export default function App() {
  const [origin, setOrigin] = useState<LatLng | null>(null);
  const [destination, setDestination] = useState<LatLng | null>(null);
  // 検索から選んだときの名前。地図クリックで選んだときは null。
  const [originName, setOriginName] = useState<string | null>(null);
  const [destinationName, setDestinationName] = useState<string | null>(null);
  const [pickStage, setPickStage] = useState<PickStage>('origin');
  const [intensity, setIntensity] = useState<RainIntensity>('medium');
  const [status, setStatus] = useState<SearchStatus>('idle');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [result, setResult] = useState<SearchResult | null>(null);
  const [selectedDangerPoint, setSelectedDangerPoint] = useState<DangerPoint | null>(null);
  const [highlightedRouteId, setHighlightedRouteId] = useState<'shortest' | 'avoid' | null>(null);

  const originLabel = usePlaceLabel(origin, originName);
  const destinationLabel = usePlaceLabel(destination, destinationName);

  // 画面を開いた時点でバックエンドの生死を確かめる。
  // 検索ボタンを押して初めて気づくより、先に分かったほうがよい。
  useEffect(() => {
    const controller = new AbortController();
    fetchHealth(controller.signal).catch((error) => {
      if (error instanceof DOMException && error.name === 'AbortError') return;
      setStatus('error');
      setErrorMessage(
        'バックエンドに接続できません。APIサーバー（uvicorn）が起動しているか確認してください',
      );
    });
    return () => controller.abort();
  }, []);

  const handleMapClick = useCallback(
    (point: LatLng) => {
      setSelectedDangerPoint(null);

      if (pickStage === 'destination') {
        setDestination(point);
        setDestinationName(null);
        setPickStage('done');
        return;
      }

      // pickStage is 'origin' or 'done' (starting a fresh pick).
      setOrigin(point);
      setOriginName(null);
      setDestination(null);
      setDestinationName(null);
      setResult(null);
      setStatus('idle');
      setErrorMessage(null);
      setPickStage('destination');
    },
    [pickStage],
  );

  // 雨量を切り替えると検索が走り直すので、古い応答が新しい結果を上書きしないよう
  // 直前のリクエストを中断し、通し番号でも二重にガードしている。
  const requestIdRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);

  const runSearch = useCallback(async (o: LatLng, d: LatLng, level: RainIntensity) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const requestId = ++requestIdRef.current;

    setStatus('loading');
    setErrorMessage(null);

    try {
      const next = await fetchSearchResult(o, d, level, controller.signal);
      if (requestId !== requestIdRef.current) return;
      setResult(next);
      setStatus('success');
      // 危険地点のポップアップを開いたまま雨量を変えたときは、
      // 開きっぱなしにせず、同じ地点の新しい判定内容へ差し替える。
      setSelectedDangerPoint((current) =>
        current ? (next.dangerPoints.find((p) => p.id === current.id) ?? null) : null,
      );
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') return;
      if (requestId !== requestIdRef.current) return;
      setResult(null);
      setSelectedDangerPoint(null);
      setStatus('error');
      setErrorMessage(
        error instanceof ApiError ? error.message : 'ルート検索に失敗しました',
      );
    }
  }, []);

  // 検索結果を共有できるよう、選んだ地点と雨量をURLに残す。
  // リンクを送れば同じ比較がそのまま開く。
  const hydratedRef = useRef(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const parsePoint = (raw: string | null): LatLng | null => {
      if (!raw) return null;
      const [lat, lng] = raw.split(',').map(Number);
      return Number.isFinite(lat) && Number.isFinite(lng) ? { lat, lng } : null;
    };

    const rain = params.get('r');
    const level: RainIntensity =
      rain === 'light' || rain === 'medium' || rain === 'heavy' ? rain : 'medium';
    const from = parsePoint(params.get('o'));
    const to = parsePoint(params.get('d'));

    setIntensity(level);
    if (from) setOrigin(from);
    if (to) setDestination(to);

    if (from && to) {
      setPickStage('done');
      void runSearch(from, to, level);
    } else if (from) {
      setPickStage('destination');
    }

    hydratedRef.current = true;
  }, [runSearch]);

  useEffect(() => {
    // 読み込み時の復元が終わるまでは書き戻さない。URLを自分で消してしまう。
    if (!hydratedRef.current) return;

    const params = new URLSearchParams();
    if (origin) params.set('o', `${origin.lat.toFixed(5)},${origin.lng.toFixed(5)}`);
    if (destination) params.set('d', `${destination.lat.toFixed(5)},${destination.lng.toFixed(5)}`);
    if (intensity !== 'medium') params.set('r', intensity);

    const query = params.toString();
    window.history.replaceState(null, '', query ? `?${query}` : window.location.pathname);
  }, [origin, destination, intensity]);

  const handleSearch = useCallback(() => {
    if (!origin || !destination) {
      setStatus('error');
      setErrorMessage('地図上で出発地と目的地を選択してください');
      return;
    }
    void runSearch(origin, destination, intensity);
  }, [origin, destination, intensity, runSearch]);

  const handleIntensityChange = useCallback(
    (level: RainIntensity) => {
      setIntensity(level);
      if (origin && destination && status === 'success') {
        void runSearch(origin, destination, level);
      }
    },
    [origin, destination, status, runSearch],
  );

  const handleSelectPlace = useCallback(
    (role: 'origin' | 'destination', point: LatLng, label: string) => {
      setResult(null);
      setStatus('idle');
      setErrorMessage(null);
      setSelectedDangerPoint(null);

      if (role === 'origin') {
        setOrigin(point);
        setOriginName(label);
        setPickStage(destination ? 'done' : 'destination');
      } else {
        setDestination(point);
        setDestinationName(label);
        setPickStage(origin ? 'done' : 'origin');
      }
    },
    [origin, destination],
  );

  const handleClearPlace = useCallback((role: 'origin' | 'destination') => {
    setResult(null);
    setStatus('idle');
    setErrorMessage(null);
    setSelectedDangerPoint(null);

    if (role === 'origin') {
      setOrigin(null);
      setOriginName(null);
      setPickStage('origin');
    } else {
      setDestination(null);
      setDestinationName(null);
      setPickStage('destination');
    }
  }, []);

  const handleReset = useCallback(() => {
    abortRef.current?.abort();
    requestIdRef.current += 1;
    setOrigin(null);
    setOriginName(null);
    setDestination(null);
    setDestinationName(null);
    setPickStage('origin');
    setResult(null);
    setStatus('idle');
    setErrorMessage(null);
    setSelectedDangerPoint(null);
    setHighlightedRouteId(null);
  }, []);

  const banner = useMemo((): Banner | null => {
    if (!result) return null;
    const shortest = result.routes.find((r) => r.id === 'shortest');
    const avoid = result.routes.find((r) => r.id === 'avoid');
    if (!shortest || !avoid) return null;

    const riskReduction = shortest.riskScore - avoid.riskScore;
    // 迂回しても危険度がほとんど下がらない区間はある。1ポイントの差を
    // 成果のように見せるより、「最短で問題ない」と言い切ったほうが
    // 判断材料として役に立つ。
    if (riskReduction < MEANINGFUL_RISK_REDUCTION) return { kind: 'no-gain' };

    const extraMinutes = Math.max(0, avoid.durationMin - shortest.durationMin);
    return { kind: 'improved', extraMinutes, riskReduction };
  }, [result]);

  return (
    <div className="app">
      <SearchPanel
        originLabel={originLabel}
        destinationLabel={destinationLabel}
        pickStage={pickStage}
        intensity={intensity}
        onIntensityChange={handleIntensityChange}
        onSearch={handleSearch}
        onReset={handleReset}
        status={status}
        errorMessage={errorMessage}
        result={result}
        banner={banner}
        highlightedRouteId={highlightedRouteId}
        onHighlightRoute={setHighlightedRouteId}
        onSelectPlace={handleSelectPlace}
        onClearPlace={handleClearPlace}
      />
      <MapView
        origin={origin}
        destination={destination}
        result={result}
        onMapClick={handleMapClick}
        selectedDangerPoint={selectedDangerPoint}
        onSelectDangerPoint={setSelectedDangerPoint}
        highlightedRouteId={highlightedRouteId}
      />
    </div>
  );
}
