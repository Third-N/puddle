import { useEffect, useId, useRef, useState } from 'react';
import { MapPin, Navigation2, X } from 'lucide-react';
import { searchPlaces } from '../api/client';
import type { LatLng, PlaceSuggestion } from '../types';

interface PlaceFieldProps {
  role: 'origin' | 'destination';
  label: string;
  /** 確定している地点の呼び名。未選択なら null。 */
  value: string | null;
  onSelect: (point: LatLng, label: string) => void;
  onClear: () => void;
}

const KIND_LABEL: Record<PlaceSuggestion['kind'], string> = {
  station: '駅',
  landmark: '施設',
  building: 'ビル',
};

/**
 * 地点の入力欄。名前で検索して選べる。
 *
 * 地図クリックだけだと、行き先が決まっている人ほど使いにくい。
 * 検索と地図クリックのどちらでも同じ状態に行き着くようにしてある。
 */
export function PlaceField({ role, label, value, onSelect, onClear }: PlaceFieldProps) {
  const [query, setQuery] = useState('');
  const [suggestions, setSuggestions] = useState<PlaceSuggestion[]>([]);
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const listId = useId();

  // 入力が止まってから引く。1文字ごとに投げると候補が入れ替わり続ける。
  useEffect(() => {
    const text = query.trim();
    if (text.length === 0) {
      setSuggestions([]);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      searchPlaces(text, controller.signal)
        .then((hits) => {
          setSuggestions(hits);
          setHighlight(0);
          setOpen(true);
        })
        .catch(() => undefined);
    }, 180);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [query]);

  // 欄の外を押したら候補を閉じる
  useEffect(() => {
    if (!open) return;
    const onDocumentClick = (event: MouseEvent) => {
      if (!wrapRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDocumentClick);
    return () => document.removeEventListener('mousedown', onDocumentClick);
  }, [open]);

  const choose = (place: PlaceSuggestion) => {
    onSelect({ lat: place.lat, lng: place.lng }, place.label);
    setQuery('');
    setSuggestions([]);
    setOpen(false);
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Escape') {
      setOpen(false);
      return;
    }

    if (event.key === 'Enter') {
      // 日本語入力では、変換を確定するEnterが先に来る。
      // これを地点の決定として扱うと、変換中の候補で勝手に確定してしまう。
      if (event.nativeEvent.isComposing || event.keyCode === 229) return;
      event.preventDefault();
      if (suggestions.length > 0) {
        choose(suggestions[highlight] ?? suggestions[0]);
        return;
      }
      // 候補が出そろう前にEnterを押されることがある。
      // そのときは待たせずに引き直し、先頭を選ぶ。
      // 値は入力欄から直接読む。状態は最後の1打ぶん遅れていることがある。
      const text = event.currentTarget.value.trim();
      if (text.length === 0) return;
      searchPlaces(text)
        .then((hits) => hits.length > 0 && choose(hits[0]))
        .catch(() => undefined);
      return;
    }

    if (suggestions.length === 0) return;
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setOpen(true);
      setHighlight((h) => (h + 1) % suggestions.length);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setOpen(true);
      setHighlight((h) => (h - 1 + suggestions.length) % suggestions.length);
    }
  };

  const Icon = role === 'origin' ? MapPin : Navigation2;

  return (
    <div className="field" ref={wrapRef}>
      <label className="field__label" htmlFor={listId}>
        <Icon size={16} className={`field__icon field__icon--${role}`} />
        {label}
      </label>

      {value ? (
        <div className="field__chosen">
          <span className="field__chosen-name">{value}</span>
          <button type="button" className="field__clear" onClick={onClear} aria-label={`${label}を解除`}>
            <X size={14} />
          </button>
        </div>
      ) : (
        <div className="field__search">
          <input
            id={listId}
            className="field__input"
            type="text"
            value={query}
            placeholder="駅名・施設名で検索、または地図をクリック"
            autoComplete="off"
            role="combobox"
            aria-expanded={open}
            aria-controls={`${listId}-list`}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => suggestions.length > 0 && setOpen(true)}
            onKeyDown={onKeyDown}
          />
          {open && suggestions.length > 0 && (
            <ul className="suggestions" id={`${listId}-list`} role="listbox">
              {suggestions.map((place, index) => (
                <li key={`${place.label}-${place.lat}-${place.lng}`}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={index === highlight}
                    className={`suggestions__item ${index === highlight ? 'suggestions__item--active' : ''}`}
                    onMouseEnter={() => setHighlight(index)}
                    onClick={() => choose(place)}
                  >
                    <span className="suggestions__name">{place.label}</span>
                    <span className="suggestions__kind">{KIND_LABEL[place.kind]}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
