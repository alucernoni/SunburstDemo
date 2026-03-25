import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import Sunburst from "./Sunburst";
import Legend from "./Legend";
import TickerPanel from "./TickerPanel";
import type { HierarchyData, PoliticianNode, TickerNode, CollapsedTicker } from "./types";

const SLIDER_MIN  = -0.4;
const SLIDER_MAX  =  0.4;
const SLIDER_STEP =  0.01;
const MAX_SIZE    =  800;

// Politician ring (depth 2) sits at y ≈ 5/8 * radius in a 4-level partition
const RING2_MID_FRACTION = 5 / 8;
// Arc length (px) at ring-2 midpoint above which a politician's tickers auto-expand
const AUTO_EXPAND_ARC_PX = 400;

// Politicians whose combined volume is <= this fraction of the party total get collapsed.
const POLITICIAN_COLLAPSE_FRACTION = 0.10;
// Hard cap on visible politicians per party — ensures labels fit even for large parties.
// Approximates: party arc (~π rad) / label floor (~0.12 rad each) ≈ 26.
const POLITICIAN_MAX_VISIBLE = 24;

// Collapse the smallest politicians within each party into "N others".
// Two conditions (union — whichever requires more collapsing):
//   1. Bottom 10% by volume
//   2. Count exceeds POLITICIAN_MAX_VISIBLE
function collapseSmallPoliticians(data: HierarchyData): HierarchyData {
  return {
    ...data,
    children: data.children.map((party) => {
      const politicians = party.children as PoliticianNode[];
      const partyTotal  = politicians.reduce((s, p) => s + p.total_volume, 0);
      const threshold   = partyTotal * POLITICIAN_COLLAPSE_FRACTION;

      // Walk from smallest to largest, accumulating into the collapse bucket
      const sorted = [...politicians].sort((a, b) => a.total_volume - b.total_volume);
      let cumulative = 0;
      const toCollapse: PoliticianNode[] = [];
      for (const p of sorted) {
        const remaining           = sorted.length - toCollapse.length;
        const belowVolumeThreshold = cumulative + p.total_volume <= threshold;
        const exceedsCountLimit    = remaining > POLITICIAN_MAX_VISIBLE;
        if (belowVolumeThreshold || exceedsCountLimit) {
          cumulative += p.total_volume;
          toCollapse.push(p);
        } else break;
      }

      // Don't collapse a single politician — "1 other" is unhelpful
      if (toCollapse.length <= 1) return party;

      const toKeep = politicians
        .filter((p) => !toCollapse.includes(p))
        .sort((a, b) => b.total_volume - a.total_volume);

      const othersNode: PoliticianNode = {
        name:           `${toCollapse.length} others`,
        party_code:     politicians[0]?.party_code ?? "",
        weighted_alpha: null,
        total_volume:   cumulative,
        trade_count:    toCollapse.reduce((s, p) => s + p.trade_count, 0),
        is_current:     false,
        collapsed:      true,
        value:          cumulative,  // D3's .sum() uses this since children: [] gives no leaf sum
        children:       [],
      };

      return { ...party, children: [...toKeep, othersNode] };
    }),
  };
}

// If a politician has exactly "1 other" collapsed, inline that ticker directly.
function sanitizeCollapsed(data: HierarchyData): HierarchyData {
  return {
    ...data,
    children: data.children.map((party) => ({
      ...party,
      children: (party.children as PoliticianNode[]).map((politician) => {
        const collapsedNode = politician.children.find((t) => t.collapsed);
        if (!collapsedNode || (collapsedNode.collapsed_tickers?.length ?? 0) !== 1) return politician;
        const onlyTicker = collapsedNode.collapsed_tickers![0];
        return {
          ...politician,
          children: [
            ...politician.children.filter((t) => !t.collapsed),
            { name: onlyTicker.name, value: onlyTicker.value },
          ],
        };
      }),
    })),
  };
}

function filterByCurrent(data: HierarchyData, currentOnly: boolean): HierarchyData {
  if (!currentOnly) return data;
  return {
    ...data,
    children: data.children
      .map((party) => ({
        ...party,
        children: (party.children as PoliticianNode[]).filter((p) => p.is_current),
      }))
      .filter((party) => party.children.length > 0),
  };
}

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

// Only auto-expand the "N others" ticker group when it's small enough to display with labels.
// Large groups use the side panel instead — inlining hundreds of tickers produces tiny slices.
const MAX_INLINE_TICKER_EXPAND = 10;

// When a politician is zoomed to fill 2π, expand their tickers from collapsed_tickers up to
// this limit — the Case-1 capacity of the full ticker ring.
// = floor(2π * (MAX_SIZE/2 * 7/8) / MIN_ARC_PX[3]) ≈ floor(2π * 350 / 14) ≈ 157
const ZOOM_MAX_TICKERS = Math.floor(2 * Math.PI * (MAX_SIZE / 2) * (7 / 8) / 14);

function expandForZoom(data: HierarchyData, politicianName: string): HierarchyData {
  return {
    ...data,
    children: data.children.map((party) => ({
      ...party,
      children: (party.children as PoliticianNode[]).map((pol) => {
        if (pol.name !== politicianName) return pol;
        const visibleTickers  = pol.children.filter((t) => !t.collapsed);
        const othersNode      = pol.children.find((t) => t.collapsed);
        if (!othersNode?.collapsed_tickers?.length) return pol;

        // Merge visible + collapsed, sorted by value desc (already sorted from pipeline)
        const all      = [...visibleTickers, ...(othersNode.collapsed_tickers)];
        const toShow   = all.slice(0, ZOOM_MAX_TICKERS);
        const leftover = all.slice(ZOOM_MAX_TICKERS);

        if (leftover.length === 0) return { ...pol, children: toShow };
        if (leftover.length === 1) {
          return { ...pol, children: [...toShow, { name: leftover[0].name, value: leftover[0].value }] };
        }
        const newOthers: TickerNode = {
          name:              `${leftover.length} others`,
          value:             leftover.reduce((s, t) => s + t.value, 0),
          collapsed:         true,
          collapsed_tickers: leftover,
        };
        return { ...pol, children: [...toShow, newOthers] };
      }),
    })),
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
        // Keep the "N others" node intact when the collapsed group is too large to display
        if (!othersNode || (othersNode.collapsed_tickers?.length ?? 0) > MAX_INLINE_TICKER_EXPAND) {
          return politician;
        }
        return { ...politician, children: [...visibleTickers, ...(othersNode.collapsed_tickers ?? [])] };
      }),
    })),
  };
}

export default function App() {
  const [data,         setData]        = useState<HierarchyData | null>(null);
  const [error,        setError]       = useState<string | null>(null);
  const [minAlpha,     setMinAlpha]    = useState(SLIDER_MIN);
  const [currentOnly,  setCurrentOnly] = useState(false);
  const [zoomedParty,       setZoomedParty]       = useState<string | null>(null);
  const [zoomedPolitician,  setZoomedPolitician]  = useState<string | null>(null);
  const [tickerPanel,       setTickerPanel]       = useState<{ politicianName: string; tickers: CollapsedTicker[] } | null>(null);
  const [chartSize,    setChartSize]   = useState(MAX_SIZE);
  const chartAreaRef = useRef<HTMLDivElement>(null);

  // Size chart to fit the available square in the content row
  useEffect(() => {
    if (!chartAreaRef.current) return;
    const ro = new ResizeObserver((entries) => {
      const { width, height } = entries[0]!.contentRect;
      setChartSize(Math.min(Math.floor(width), Math.floor(height), MAX_SIZE));
    });
    ro.observe(chartAreaRef.current);
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

  const handleShowTickerPanel = useCallback((politicianName: string, tickers: CollapsedTicker[]) => {
    setTickerPanel({ politicianName, tickers });
  }, []);

  // Step 1: filter + sanitize (no expansion yet)
  const filteredData = useMemo(() => {
    if (!data) return null;
    return collapseSmallPoliticians(
      sanitizeCollapsed(filterByCurrent(filterByAlpha(data, minAlpha), currentOnly))
    );
  }, [data, minAlpha, currentOnly]);

  // Step 2: merge manual expanded set with arc-width-based auto-expansion
  const effectiveExpanded = useMemo(() => {
    const result = new Set<string>();
    if (!filteredData || chartSize === 0) return result;
    const radius = chartSize / 2;
    const ringMidRadius = radius * RING2_MID_FRACTION;
    const totalVolume = filteredData.children.reduce(
      (s, party) => s + (party.children as PoliticianNode[]).reduce((sp, p) => sp + p.total_volume, 0), 0
    );
    for (const party of filteredData.children) {
      const partyVolume = (party.children as PoliticianNode[]).reduce((s, p) => s + p.total_volume, 0);
      const partyArc = zoomedParty === party.name
        ? 2 * Math.PI
        : (totalVolume > 0 ? (partyVolume / totalVolume) * 2 * Math.PI : 0);
      for (const politician of party.children as PoliticianNode[]) {
        if (!politician.children.some((t) => t.collapsed)) continue;
        const arcAngle = zoomedPolitician === politician.name
          ? 2 * Math.PI
          : (partyVolume > 0 ? (politician.total_volume / partyVolume) * partyArc : 0);
        if (arcAngle * ringMidRadius >= AUTO_EXPAND_ARC_PX) result.add(politician.name);
      }
    }
    return result;
  }, [filteredData, zoomedParty, zoomedPolitician, chartSize]);

  // Step 3: apply auto-expansions, then also fully expand the zoomed politician's tickers
  const displayData = useMemo(() => {
    if (!filteredData) return null;
    let d = applyExpansions(filteredData, effectiveExpanded);
    if (zoomedPolitician) d = expandForZoom(d, zoomedPolitician);
    return d;
  }, [filteredData, effectiveExpanded, zoomedPolitician]);

  if (error) return <div style={{ padding: 24, color: "red" }}>Error: {error}</div>;

  const alphaLabel        = `${minAlpha >= 0 ? "+" : ""}${(minAlpha * 100).toFixed(0)}%`;
  const visibleCount      = displayData?.children.reduce((sum, p) => sum + p.children.length, 0) ?? 0;
  const totalPoliticians  = data?.children.reduce((sum, p) => sum + p.children.length, 0) ?? 0;

  return (
    <main className="app-layout">
      <div className="content-row">
        <div className="chart-column">
          <header className="app-header">
            <h1 className="app-title">Congressional Stock Trading</h1>
            <div className="controls">
              <div className="controls-row">
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
                <span className="slider-count">{visibleCount} shown</span>
                <label className="toggle-label">
                  <input
                    type="checkbox"
                    checked={currentOnly}
                    onChange={(e) => setCurrentOnly(e.target.checked)}
                  />
                  Current only
                </label>
              </div>
              <p className="footnote">* Only legislators with 10+ disclosed purchase transactions are included</p>
            </div>
          </header>

          <div ref={chartAreaRef} className="chart-area">
            {!displayData ? (
              <div className="spinner-wrapper">
                <div className="spinner" />
                <span>Loading trading data...</span>
              </div>
            ) : visibleCount === 0 ? (
              <div className="empty-state">
                <span className="empty-state-icon">○</span>
                <span className="empty-state-title">No politicians match these filters</span>
                <span className="empty-state-hint">Try lowering the alpha threshold or unchecking "Current only"</span>
              </div>
            ) : (
              <Sunburst
                data={displayData}
                totalPoliticians={totalPoliticians}
                width={chartSize}
                height={chartSize}
                expandedPoliticians={effectiveExpanded}
                zoomedParty={zoomedParty}
                onPartyClick={setZoomedParty}
                zoomedPolitician={zoomedPolitician}
                onPoliticianClick={setZoomedPolitician}
                onShowTickerPanel={handleShowTickerPanel}
              />
            )}
          </div>
        </div>
        <Legend />
        {tickerPanel && (
          <TickerPanel
            politicianName={tickerPanel.politicianName}
            tickers={tickerPanel.tickers}
            onClose={() => setTickerPanel(null)}
          />
        )}
      </div>
    </main>
  );
}
