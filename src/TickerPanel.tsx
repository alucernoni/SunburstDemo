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

const formatAlpha = (a: number | null | undefined) =>
  a == null ? "—" : `${a >= 0 ? "+" : ""}${(a * 100).toFixed(1)}%`;

export default function TickerPanel({ politicianName, tickers, onClose }: TickerPanelProps) {

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
          {tickers.map((t, i) => {
            const alpha = t.alpha ?? null;
            const alphaClass = alpha == null ? "ticker-panel-alpha-na" : alpha >= 0 ? "ticker-panel-alpha-pos" : "ticker-panel-alpha-neg";
            return (
              <div key={t.name} className="ticker-panel-row">
                <span className="ticker-panel-rank">{i + 1}</span>
                <span className="ticker-panel-symbol">{t.name}</span>
                <span className={alphaClass}>{formatAlpha(alpha)}</span>
                <span className="ticker-panel-vol">{formatVolume(t.value)}</span>
              </div>
            );
          })}
        </div>

        <div className="ticker-panel-footer">Click outside or press Esc to close</div>
      </div>
    </div>
  );
}
