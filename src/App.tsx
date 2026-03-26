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

// Ticker ring (depth 3) sits at y ≈ 7/8 * radius in a 4-level partition
const RING3_MID_FRACTION = 7 / 8;
// Minimum arc length in px for a labeled ticker slice (matches Sunburst.tsx MIN_ARC_PX[3])
const TICKER_MIN_ARC_PX = 14;
// Floor fraction for politician arc distribution (matches Sunburst.tsx LABEL_FLOOR_ALPHA)
const LABEL_FLOOR_ALPHA = 0.5;
// No minimum — if the arc can't fit even one labeled ticker, collapse everything
// into a single "N tickers" node so there are zero unlabeled slices.
const MIN_VISIBLE_TICKERS = 0;
// Minimum party arc in radians (matches Sunburst.tsx MIN_PARTY_ARC = 12°)
const MIN_PARTY_ARC_RAD = (12 * Math.PI) / 180;

// Collapse tickers that won't fit labeled arcs at the current chart size.
// Mirrors enforceMinPartyArcs + enforceMinPoliticianArcs + enforceMinTickerArcs in Sunburst.tsx
// so the pipeline's 200-ticker pool is trimmed to exactly what the chart can label.
// Zoom state is passed so that zoomed parties/politicians get the correct (larger) arc.
function collapseSmallTickers(
  data: HierarchyData,
  chartSize: number,
  zoomedParty: string | null,
  zoomedPolitician: string | null,
): HierarchyData {
  const radius        = chartSize / 2;
  const ring2MidPx   = radius * RING2_MID_FRACTION;
  const ring3MidPx   = radius * RING3_MID_FRACTION;
  const minPolArcRad = 20 / ring2MidPx;       // MIN_ARC_PX[2] in radians
  const minTickerRad = TICKER_MIN_ARC_PX / ring3MidPx;

  // Include ALL politicians (visible + collapsed "N others") to match enforceMinPoliticianArcs
  const totalVolume = data.children.reduce(
    (s, party) => s + (party.children as PoliticianNode[])
      .reduce((sp, p) => sp + p.total_volume, 0),
    0,
  );

  // Replicate enforceMinPartyArcs: small parties get a floor of MIN_PARTY_ARC_RAD,
  // and ALL parties are scaled uniformly so they still sum to 2π.
  // Without this, parties like the tiny Independent party inflate total arc by taking a
  // floor that steals space from Dems/Reps, causing polArc to be overestimated here.
  const flooredPartyArcs = data.children.map((party) => {
    const partyVol = (party.children as PoliticianNode[]).reduce((s, p) => s + p.total_volume, 0);
    const rawArc   = totalVolume > 0 ? (partyVol / totalVolume) * 2 * Math.PI : 0;
    return Math.max(rawArc, MIN_PARTY_ARC_RAD);
  });
  const partyArcScale = (2 * Math.PI) / flooredPartyArcs.reduce((s, a) => s + a, 0);

  return {
    ...data,
    children: data.children.map((party, partyIdx) => {
      const allPols  = party.children as PoliticianNode[];
      const partyVol = allPols.reduce((s, p) => s + p.total_volume, 0);
      // Zoomed party fills the full circle; otherwise match enforceMinPartyArcs
      const partyArc = zoomedParty === party.name
        ? 2 * Math.PI
        : flooredPartyArcs[partyIdx] * partyArcScale;
      // n includes collapsed "N others" politician — matches enforceMinPoliticianArcs
      const n        = allPols.length;
      const polFloor = n > 0 && n * minPolArcRad <= partyArc
        ? minPolArcRad
        : n > 0 ? (partyArc / n) * LABEL_FLOOR_ALPHA : 0;
      const remaining = Math.max(0, partyArc - n * polFloor);

      return {
        ...party,
        children: allPols.map((pol) => {
          if (pol.collapsed) return pol;
          const fraction = partyVol > 0 ? pol.total_volume / partyVol : 1 / Math.max(n, 1);
          // Zoomed politician fills the full circle
          const polArc = zoomedPolitician === pol.name
            ? 2 * Math.PI
            : polFloor + fraction * remaining;
          // Subtract 1 to reserve a slot for the potential "N others" collapsed node.
          // Without this, n visible + 1 "N others" = n+1 total, which fails the
          // enforceMinTickerArcs Case-1 check and drops all labels into Case 2.
          const maxVisible = Math.max(Math.floor(polArc / minTickerRad) - 1, MIN_VISIBLE_TICKERS);

          // Merge visible + pipeline's collapsed_tickers into one sorted pool
          const visibleTickers = pol.children.filter((t) => !t.collapsed);
          const existingOthers = pol.children.find((t) => t.collapsed);
          const allTickers: TickerNode[] = [
            ...visibleTickers.map((t) => ({ name: t.name, value: t.value, alpha: t.alpha })),
            ...(existingOthers?.collapsed_tickers ?? []),
          ];

          const toShow   = allTickers.slice(0, maxVisible);
          const leftover = allTickers.slice(maxVisible);

          if (leftover.length === 0) {
            return { ...pol, children: toShow };
          }
          if (leftover.length === 1) {
            return { ...pol, children: [...toShow, { name: leftover[0].name, value: leftover[0].value }] };
          }
          // "N tickers" when everything is collapsed (nothing visible to be "other than");
          // "N others" when some tickers are shown alongside the collapsed group.
          const collapsedLabel = toShow.length === 0
            ? `${leftover.length} tickers`
            : `${leftover.length} others`;
          const newOthers: TickerNode = {
            name:              collapsedLabel,
            value:             leftover.reduce((s, t) => s + t.value, 0),
            collapsed:         true,
            collapsed_tickers: leftover,
          };
          return { ...pol, children: [...toShow, newOthers] };
        }),
      };
    }),
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

// When a politician is zoomed to fill 2π, expand their tickers from collapsed_tickers.
// Limit is the Case-1 capacity of the full ticker ring at the actual chart size.
// = floor(2π * radius * 7/8 / MIN_ARC_PX[3])
function zoomMaxTickers(chartSize: number): number {
  // Subtract 1 to reserve a slot for the potential "N others" node (same logic as collapseSmallTickers)
  return Math.floor(2 * Math.PI * (chartSize / 2) * RING3_MID_FRACTION / TICKER_MIN_ARC_PX) - 1;
}

function expandForZoom(data: HierarchyData, politicianName: string, maxTickers: number): HierarchyData {
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
const toShow   = all.slice(0, maxTickers);
        const leftover = all.slice(maxTickers);

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

  // Step 1: filter + collapse (zoom state informs how many tickers to keep per politician)
  const filteredData = useMemo(() => {
    if (!data) return null;
    return collapseSmallTickers(
      collapseSmallPoliticians(
        filterByCurrent(filterByAlpha(data, minAlpha), currentOnly)
      ),
      chartSize,
      zoomedParty,
      zoomedPolitician,
    );
  }, [data, minAlpha, currentOnly, chartSize, zoomedParty, zoomedPolitician]);

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
    if (zoomedPolitician) d = expandForZoom(d, zoomedPolitician, zoomMaxTickers(chartSize));
    return d;
  }, [filteredData, effectiveExpanded, zoomedPolitician, chartSize]);

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
