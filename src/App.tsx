import { useState, useEffect, useMemo } from "react";
import Sunburst from "./Sunburst";
import type { HierarchyData, PoliticianNode } from "./types";

const SLIDER_MIN = -0.4;
const SLIDER_MAX =  0.4;
const SLIDER_STEP = 0.01;

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

export default function App() {
  const [data,     setData]     = useState<HierarchyData | null>(null);
  const [error,    setError]    = useState<string | null>(null);
  const [minAlpha, setMinAlpha] = useState(SLIDER_MIN);

  useEffect(() => {
    fetch("/hierarchy.json")
      .then((r) => {
        if (!r.ok) throw new Error(`Failed to load hierarchy.json (${r.status})`);
        return r.json() as Promise<HierarchyData>;
      })
      .then(setData)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  const filteredData = useMemo(
    () => (data ? filterByAlpha(data, minAlpha) : null),
    [data, minAlpha]
  );

  if (error) return <div style={{ padding: 24, color: "red" }}>Error: {error}</div>;
  if (!filteredData) return <div style={{ padding: 24 }}>Loading...</div>;

  const alphaLabel = `${minAlpha >= 0 ? "+" : ""}${(minAlpha * 100).toFixed(0)}%`;
  const visibleCount = filteredData.children.reduce(
    (sum, party) => sum + party.children.length, 0
  );

  return (
    <main style={{ display: "flex", flexDirection: "column", alignItems: "center", padding: 24, gap: 16 }}>
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
      <Sunburst data={filteredData} width={800} height={800} />
    </main>
  );
}
