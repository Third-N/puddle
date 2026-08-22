import { AlertTriangle, Footprints, MapPin, Navigation2, RotateCcw, Search } from 'lucide-react';
import type { Banner, RainIntensity, RouteResult, SearchResult, SearchStatus } from '../types';

interface SearchPanelProps {
  originLabel: string | null;
  destinationLabel: string | null;
  pickStage: 'origin' | 'destination' | 'done';
  intensity: RainIntensity;
  onIntensityChange: (level: RainIntensity) => void;
  onSearch: () => void;
  onReset: () => void;
  status: SearchStatus;
  errorMessage: string | null;
  result: SearchResult | null;
  banner: Banner | null;
  highlightedRouteId: 'shortest' | 'avoid' | null;
  onHighlightRoute: (id: 'shortest' | 'avoid' | null) => void;
}

const INTENSITY_OPTIONS: { value: RainIntensity; label: string }[] = [
  { value: 'light', label: '弱雨' },
  { value: 'medium', label: '中雨' },
  { value: 'heavy', label: '強雨' },
];

function riskTone(score: number): 'high' | 'medium' | 'low' {
  if (score >= 55) return 'high';
  if (score >= 25) return 'medium';
  return 'low';
}

function RouteCard({
  route,
  highlighted,
  onHover,
}: {
  route: RouteResult;
  highlighted: boolean;
  onHover: (id: 'shortest' | 'avoid' | null) => void;
}) {
  const tone = riskTone(route.riskScore);
  return (
    <button
      type="button"
      className={`route-card route-card--${route.id} ${highlighted ? 'route-card--active' : ''}`}
      onMouseEnter={() => onHover(route.id)}
      onMouseLeave={() => onHover(null)}
      onFocus={() => onHover(route.id)}
      onBlur={() => onHover(null)}
    >
      <span className="route-card__icon" style={{ backgroundColor: route.color }}>
        <Footprints size={18} />
      </span>
      <span className="route-card__body">
        <span className="route-card__title">{route.label}</span>
        <span className="route-card__meta">
          <span>{route.durationMin}分</span>
          <span>{route.distanceM}m</span>
          <span className={`route-card__risk route-card__risk--${tone}`}>
            <AlertTriangle size={14} />
            危険度 {route.riskScore}%
          </span>
        </span>
      </span>
    </button>
  );
}

export function SearchPanel({
  originLabel,
  destinationLabel,
  pickStage,
  intensity,
  onIntensityChange,
  onSearch,
  onReset,
  status,
  errorMessage,
  result,
  banner,
  highlightedRouteId,
  onHighlightRoute,
}: SearchPanelProps) {
  const helperText =
    pickStage === 'origin'
      ? '地図をクリックして出発地を選択してください'
      : pickStage === 'destination'
        ? '続けて地図をクリックして目的地を選択してください'
        : '「ルートを検索」を押してください';

  return (
    <aside className="panel">
      <h1 className="panel__title">水たまりゼロ東京</h1>
      <p className="panel__subtitle">雨の日も、濡れにくい道を。</p>

      <div className="field">
        <label className="field__label">
          <MapPin size={16} className="field__icon field__icon--origin" />
          出発地
        </label>
        <div className="field__value">{originLabel ?? '未選択'}</div>
      </div>

      <div className="field">
        <label className="field__label">
          <Navigation2 size={16} className="field__icon field__icon--destination" />
          目的地
        </label>
        <div className="field__value">{destinationLabel ?? '未選択'}</div>
      </div>

      <p className="panel__helper">{helperText}</p>

      <div className="intensity">
        {INTENSITY_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            type="button"
            className={`intensity__option ${intensity === opt.value ? 'intensity__option--active' : ''}`}
            onClick={() => onIntensityChange(opt.value)}
          >
            {opt.label}
          </button>
        ))}
      </div>

      <button type="button" className="btn btn--primary" onClick={onSearch} disabled={status === 'loading'}>
        <Search size={18} />
        {status === 'loading' ? '検索中…' : 'ルートを検索'}
      </button>

      <button type="button" className="btn btn--ghost" onClick={onReset}>
        <RotateCcw size={16} />
        選択をリセット
      </button>

      {status !== 'loading' && errorMessage && <p className="panel__error">{errorMessage}</p>}

      {result && (
        <div className="routes">
          {result.routes.map((route) => (
            <RouteCard
              key={route.id}
              route={route}
              highlighted={highlightedRouteId === route.id}
              onHover={onHighlightRoute}
            />
          ))}
        </div>
      )}

      {banner?.kind === 'improved' && (
        <div className="banner">
          {banner.extraMinutes > 0
            ? `${banner.extraMinutes}分の遠回りで、危険度を${banner.riskReduction}ポイント低減`
            : `遠回りなしで、危険度を${banner.riskReduction}ポイント低減`}
        </div>
      )}

      {banner?.kind === 'no-gain' && (
        <div className="banner banner--neutral">
          この区間は迂回しても濡れにくくなりません。最短ルートで問題ありません
        </div>
      )}
    </aside>
  );
}
