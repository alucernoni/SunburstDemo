import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import Sunburst from "./Sunburst";
import Legend from "./Legend";
import type { HierarchyData, PoliticianNode, TickerNode } from "./types";

const SLIDER_MIN  = -0.4;
const SLIDER_MAX  =  0.4;
const SLIDER_STEP =  0.01;
const MAX_SIZE    =  800;

function filterByAlpha(data: HierarchyData, minAlpha: number): HierarchyData {
  return {
    ...data,
    children: data.children
      .map((party) => ({
        ...party,
        children: (party.children as PoliticianNode[]).filter(
          (p) => p.weighted_alpha !== null && p.weighted_alpha >= minAlpha
        ),
      }))
      .filter((party) => party.children.length > 0),
  };
}

function applyExpansions(data: HierarchyData, expanded: Set<string>): HierarchyData {
  return {
    ...data,
    children: data.children.map((party) => ({
      ...party,
      children: (party.children as PoliticianNode[]).map((politician) => {
        if (!expanded.has(politician.name)) return politician;
        const visibleTickers = politician.children.filter((t) => !t.collapsed);
        const othersNode     = politician.children.find((t) => t.collapsed);
        const allTickers: TickerNode[] = othersNode
          ? [...visibleTickers, ...(othersNode.collapsed_tickers ?? [])]
          : visibleTickers;
        return { ...politician, children: allTickers };
      }),
    })),
  };
}

export default function App() {
  const [data,     setData]     = useState<HierarchyData | null>(null);
  const [error,    setError]    = useState<string | null>(null);
  const [minAlpha, setMinAlpha] = useState(SLIDER_MIN);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [chartSize, setChartSize] = useState(MAX_SIZE);
  const containerRef = useRef<HTMLDivElement>(null);

  // Responsive sizing
  useEffect(() => {
    if (!containerRef.current) return;
    const ro = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width ?? MAX_SIZE;
      setChartSize(Math.min(Math.floor(width), MAX_SIZE));
    });
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    fetch("/hierarchy.json")
      .then((r) => {
        if (!r.ok) throw new Error(`Failed to load hierarchy.json (${r.status})`);
        return r.json() as Promise<HierarchyData>;
      })
      .then(setData)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  const handleCollapsedClick = useCallback((politicianName: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(politicianName)) next.delete(politicianName);
      else next.add(politicianName);
      return next;
    });
  }, []);

  const displayData = useMemo(() => {
    if (!data) return null;
    return applyExpansions(filterByAlpha(data, minAlpha), expanded);
  }, [data, minAlpha, expanded]);

  if (error) return <div style={{ padding: 24, color: "red" }}>Error: {error}</div>;

  const alphaLabel   = `${minAlpha >= 0 ? "+" : ""}${(minAlpha * 100).toFixed(0)}%`;
  const visibleCount = displayData?.children.reduce((sum, p) => sum + p.children.length, 0) ?? 0;

  return (
    <main className="app-layout">
      <h1 className="app-title">Congressional Stock Trading</h1>

      <div className="slider-container">
        <label className="slider-label">
          Min Alpha vs SPY
          <span className="slider-value" style={{ color: minAlpha >= 0 ? "#22C55E" : "#EF4444" }}>
            {alphaLabel}
          </span>
        </label>
        <input
          type="range"
          min={SLIDER_MIN}
          max={SLIDER_MAX}
          step={SLIDER_STEP}
          value={minAlpha}
          onChange={(e) => setMinAlpha(parseFloat(e.target.value))}
          className="slider"
        />
        <span className="slider-count">{visibleCount} politicians</span>
      </div>

      <div ref={containerRef} className="chart-container">
        {!displayData ? (
          <div className="spinner-wrapper">
            <div className="spinner" />
            <span>Loading trading data...</span>
          </div>
        ) : (
          <Sunburst
            data={displayData}
            width={chartSize}
            height={chartSize}
            expandedPoliticians={expanded}
            onCollapsedClick={handleCollapsedClick}
          />
        )}
      </div>

      <Legend />
    </main>
  );
}
