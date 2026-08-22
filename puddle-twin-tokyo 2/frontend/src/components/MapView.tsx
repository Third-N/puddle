import { useEffect, useRef, useState } from 'react';
import maplibregl from 'maplibre-gl';
import { X } from 'lucide-react';
import { DEFAULT_CENTER, DEFAULT_ZOOM } from '../data/places';
import { fetchAreaInfo } from '../api/client';
import type { DangerPoint, LatLng, SearchResult } from '../types';

const MAP_STYLE = 'https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json';

interface MapViewProps {
  origin: LatLng | null;
  destination: LatLng | null;
  result: SearchResult | null;
  onMapClick: (point: LatLng) => void;
  selectedDangerPoint: DangerPoint | null;
  onSelectDangerPoint: (point: DangerPoint | null) => void;
  highlightedRouteId: 'shortest' | 'avoid' | null;
}

/**
 * デモ対象地域の「外側」を塗るポリゴンを作る。
 *
 * 対象地域そのものを塗るのではなく、周囲に穴あきの覆いをかけている。
 * 使える範囲がひと目で分かり、範囲外をクリックしてエラーで気づく、という
 * 手戻りが無くなる。
 */
function toOutsideMask(bounds: {
  minLat: number;
  minLng: number;
  maxLat: number;
  maxLng: number;
}) {
  const { minLat, minLng, maxLat, maxLng } = bounds;
  return {
    type: 'Feature' as const,
    properties: {},
    geometry: {
      type: 'Polygon' as const,
      coordinates: [
        // 外周（世界全体）は反時計回り
        [
          [-180, -85],
          [180, -85],
          [180, 85],
          [-180, 85],
          [-180, -85],
        ],
        // 穴（対象地域）は時計回り
        [
          [minLng, minLat],
          [minLng, maxLat],
          [maxLng, maxLat],
          [maxLng, minLat],
          [minLng, minLat],
        ],
      ],
    },
  };
}

function toGeoJSONLine(path: LatLng[]) {
  return {
    type: 'Feature' as const,
    properties: {},
    geometry: {
      type: 'LineString' as const,
      coordinates: path.map((p) => [p.lng, p.lat]),
    },
  };
}

function toGeoJSONPoints(points: DangerPoint[]) {
  return {
    type: 'FeatureCollection' as const,
    features: points.map((p) => ({
      type: 'Feature' as const,
      properties: { id: p.id, weight: p.weight, level: p.level },
      geometry: { type: 'Point' as const, coordinates: [p.lng, p.lat] },
    })),
  };
}

export function MapView({
  origin,
  destination,
  result,
  onMapClick,
  selectedDangerPoint,
  onSelectDangerPoint,
  highlightedRouteId,
}: MapViewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  // ソースとレイヤーを追加し終えたかどうか。
  // これを見ずに描画しようとすると、地図の準備が間に合わなかったときに
  // ルート線が一度も描かれないまま終わってしまう。
  const [layersReady, setLayersReady] = useState(false);
  const originMarkerRef = useRef<maplibregl.Marker | null>(null);
  const destinationMarkerRef = useRef<maplibregl.Marker | null>(null);
  const resultRef = useRef<SearchResult | null>(result);
  const onMapClickRef = useRef(onMapClick);
  const onSelectDangerPointRef = useRef(onSelectDangerPoint);

  resultRef.current = result;
  onMapClickRef.current = onMapClick;
  onSelectDangerPointRef.current = onSelectDangerPoint;

  // Create the map once.
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: MAP_STYLE,
      center: [DEFAULT_CENTER.lng, DEFAULT_CENTER.lat],
      zoom: DEFAULT_ZOOM,
      // 危険地点の判定に国土地理院の標高タイルを使っているため、出典表示が必要。
      attributionControl: {
        customAttribution:
          '標高: <a href="https://maps.gsi.go.jp/development/ichiran.html" target="_blank" rel="noreferrer">国土地理院</a>',
      },
    });

    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-left');

    map.on('click', (e) => {
      // 危険地点の上をクリックしたときは、出発地・目的地の選択をやり直さない。
      // MapLibre はレイヤー個別のハンドラとは別に、地図全体のハンドラも呼ぶため。
      if (map.getLayer('danger-points-circle')) {
        const hits = map.queryRenderedFeatures(e.point, { layers: ['danger-points-circle'] });
        if (hits.length > 0) return;
      }
      onMapClickRef.current({ lat: e.lngLat.lat, lng: e.lngLat.lng });
    });

    map.on('load', () => {
      // 対象地域の覆いは、ルートや危険地点より下に置きたいので先に追加する
      map.addSource('demo-area', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
      map.addLayer({
        id: 'demo-area-mask',
        type: 'fill',
        source: 'demo-area',
        paint: { 'fill-color': '#0f172a', 'fill-opacity': 0.22 },
      });
      map.addLayer({
        id: 'demo-area-outline',
        type: 'line',
        source: 'demo-area',
        paint: {
          'line-color': '#1d4ed8',
          'line-width': 1.5,
          'line-dasharray': [3, 2],
          'line-opacity': 0.7,
        },
      });

      map.addSource('shortest-route', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
      map.addSource('avoid-route', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
      map.addSource('danger-points', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });

      map.addLayer({
        id: 'shortest-route-line',
        type: 'line',
        source: 'shortest-route',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': '#6b7280', 'line-width': 5, 'line-opacity': 0.9 },
      });

      map.addLayer({
        id: 'avoid-route-line',
        type: 'line',
        source: 'avoid-route',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': '#16a34a', 'line-width': 5, 'line-opacity': 0.9 },
      });

      map.addLayer({
        id: 'danger-heat',
        type: 'heatmap',
        source: 'danger-points',
        paint: {
          'heatmap-weight': ['get', 'weight'],
          'heatmap-intensity': 1.4,
          'heatmap-radius': 42,
          'heatmap-opacity': 0.75,
          'heatmap-color': [
            'interpolate',
            ['linear'],
            ['heatmap-density'],
            0,
            'rgba(255,255,255,0)',
            0.3,
            'rgba(253,224,71,0.55)',
            0.6,
            'rgba(251,146,60,0.75)',
            1,
            'rgba(220,38,38,0.85)',
          ],
        },
      });

      map.addLayer({
        id: 'danger-points-circle',
        type: 'circle',
        source: 'danger-points',
        paint: {
          'circle-radius': 7,
          'circle-color': ['match', ['get', 'level'], 'high', '#dc2626', 'medium', '#f59e0b', '#facc15'],
          'circle-stroke-width': 2,
          'circle-stroke-color': '#ffffff',
        },
      });

      map.on('mouseenter', 'danger-points-circle', () => {
        map.getCanvas().style.cursor = 'pointer';
      });
      map.on('mouseleave', 'danger-points-circle', () => {
        map.getCanvas().style.cursor = '';
      });
      map.on('click', 'danger-points-circle', (e) => {
        const feature = e.features?.[0];
        const id = feature?.properties?.id as string | undefined;
        if (!id) return;
        const point = resultRef.current?.dangerPoints.find((p) => p.id === id) ?? null;
        onSelectDangerPointRef.current(point);
      });

      setLayersReady(true);
    });

    // コンテナのサイズ変更に地図を追従させる。
    // これが無いと、初期化時のサイズのまま canvas が固定されてしまう。
    const resizeObserver = new ResizeObserver(() => map.resize());
    resizeObserver.observe(containerRef.current);

    mapRef.current = map;

    return () => {
      resizeObserver.disconnect();
      map.remove();
      mapRef.current = null;
      setLayersReady(false);
    };
  }, []);

  // Origin / destination markers.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    if (origin) {
      if (!originMarkerRef.current) {
        const el = document.createElement('div');
        el.className = 'map-marker map-marker--origin';
        originMarkerRef.current = new maplibregl.Marker({ element: el }).setLngLat([origin.lng, origin.lat]).addTo(map);
      } else {
        originMarkerRef.current.setLngLat([origin.lng, origin.lat]);
      }
    } else if (originMarkerRef.current) {
      originMarkerRef.current.remove();
      originMarkerRef.current = null;
    }

    if (destination) {
      if (!destinationMarkerRef.current) {
        const el = document.createElement('div');
        el.className = 'map-marker map-marker--destination';
        destinationMarkerRef.current = new maplibregl.Marker({ element: el })
          .setLngLat([destination.lng, destination.lat])
          .addTo(map);
      } else {
        destinationMarkerRef.current.setLngLat([destination.lng, destination.lat]);
      }
    } else if (destinationMarkerRef.current) {
      destinationMarkerRef.current.remove();
      destinationMarkerRef.current = null;
    }
  }, [origin, destination]);

  // デモ対象地域の範囲をバックエンドから取って、地図に覆いを描く。
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !layersReady) return;

    const controller = new AbortController();
    fetchAreaInfo(controller.signal)
      .then((area) => {
        const source = map.getSource('demo-area') as maplibregl.GeoJSONSource | undefined;
        if (!source) return;
        source.setData({ type: 'FeatureCollection', features: [toOutsideMask(area.bounds)] });
      })
      // 取れなければ覆いを出さないだけ。地図自体は使える。
      .catch(() => undefined);

    return () => controller.abort();
  }, [layersReady]);

  // Route lines + danger points.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !layersReady) return;

    const applySources = () => {
      const shortestSource = map.getSource('shortest-route') as maplibregl.GeoJSONSource | undefined;
      const avoidSource = map.getSource('avoid-route') as maplibregl.GeoJSONSource | undefined;
      const dangerSource = map.getSource('danger-points') as maplibregl.GeoJSONSource | undefined;
      if (!shortestSource || !avoidSource || !dangerSource) return;

      if (!result) {
        shortestSource.setData({ type: 'FeatureCollection', features: [] });
        avoidSource.setData({ type: 'FeatureCollection', features: [] });
        dangerSource.setData({ type: 'FeatureCollection', features: [] });
        return;
      }

      const shortest = result.routes.find((r) => r.id === 'shortest');
      const avoid = result.routes.find((r) => r.id === 'avoid');

      shortestSource.setData({ type: 'FeatureCollection', features: shortest ? [toGeoJSONLine(shortest.path)] : [] });
      avoidSource.setData({ type: 'FeatureCollection', features: avoid ? [toGeoJSONLine(avoid.path)] : [] });
      dangerSource.setData(toGeoJSONPoints(result.dangerPoints));

      const allPoints = [...(shortest?.path ?? []), ...(avoid?.path ?? [])];
      if (allPoints.length > 0) {
        const bounds = allPoints.reduce(
          (b, p) => b.extend([p.lng, p.lat]),
          new maplibregl.LngLatBounds([allPoints[0].lng, allPoints[0].lat], [allPoints[0].lng, allPoints[0].lat]),
        );
        map.fitBounds(bounds, { padding: 90, maxZoom: 17, duration: 600 });
      }
    };

    applySources();
  }, [result, layersReady]);

  // Highlight a route when its card is hovered/focused.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.getLayer('shortest-route-line') || !map.getLayer('avoid-route-line')) return;
    map.setPaintProperty('shortest-route-line', 'line-width', highlightedRouteId === 'shortest' ? 7 : 5);
    map.setPaintProperty('avoid-route-line', 'line-width', highlightedRouteId === 'avoid' ? 7 : 5);
  }, [highlightedRouteId, layersReady]);

  return (
    <div className="map-wrap">
      <div ref={containerRef} className="map-container" />

      <div className="legend">
        <div className="legend__item">
          <span className="legend__swatch legend__swatch--line legend__swatch--gray" />
          最短
        </div>
        <div className="legend__item">
          <span className="legend__swatch legend__swatch--line legend__swatch--green" />
          回避
        </div>
        <div className="legend__item">
          <span className="legend__swatch legend__swatch--dot" />
          危険地点
        </div>
      </div>

      {selectedDangerPoint && (
        <div className="danger-popup">
          <button
            type="button"
            className="danger-popup__close"
            onClick={() => onSelectDangerPoint(null)}
            aria-label="閉じる"
          >
            <X size={16} />
          </button>
          <p className="danger-popup__title">
            水たまり発生リスク：
            {selectedDangerPoint.level === 'high' ? '高' : selectedDangerPoint.level === 'medium' ? '中' : '低'}
          </p>
          <p className="danger-popup__body">{selectedDangerPoint.reason}</p>
          <p className="danger-popup__note">※東京都の地形データに基づく推定です</p>
        </div>
      )}
    </div>
  );
}
