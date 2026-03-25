import { useEffect } from "react";
import type { CollapsedTicker } from "./types";

interface TickerPanelProps {
  politicianName: string;
  tickers: CollapsedTicker[];
  onClose: () => void;
}

const formatVolume = (v: number) =>
  v >= 1_000_000
    ? `$${(v / 1_000_000).toFixed(1)}M`
    : `$${(v / 1_000).toFixed(0)}K`;

export default function TickerPanel({ politicianName, tickers, onClose }: TickerPanelProps) {
  const maxVol = Math.max(...tickers.map((t) => t.value));

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="ticker-panel-backdrop" onClick={onClose}>
      <div className="ticker-panel" onClick={(e) => e.stopPropagation()}>
        <div className="ticker-panel-header">
          <div>
            <div className="ticker-panel-title">{politicianName}</div>
            <div className="ticker-panel-subtitle">{tickers.length} additional tickers</div>
          </div>
          <button className="ticker-panel-close" onClick={onClose}>✕</button>
        </div>

        <div className="ticker-panel-list">
          {tickers.map((t, i) => (
            <div key={t.name} className="ticker-panel-row">
              <span className="ticker-panel-rank">{i + 1}</span>
              <span className="ticker-panel-symbol">{t.name}</span>
              <div className="ticker-panel-bar-track">
                <div
                  className="ticker-panel-bar-fill"
                  style={{ width: `${(t.value / maxVol) * 100}%` }}
                />
              </div>
              <span className="ticker-panel-vol">{formatVolume(t.value)}</span>
            </div>
          ))}
        </div>

        <div className="ticker-panel-footer">Click outside or press Esc to close</div>
      </div>
    </div>
  );
}
