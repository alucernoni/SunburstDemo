import { useRef, useEffect } from "react";
import * as d3 from "d3";
import type { HierarchyData, PoliticianNode, TickerNode, CollapsedTicker } from "./types";

interface SunburstProps {
  data: HierarchyData;
  totalPoliticians: number;
  width?: number;
  height?: number;
  expandedPoliticians?: Set<string>;
  zoomedParty?: string | null;
  onPartyClick?: (party: string | null) => void;
  zoomedPolitician?: string | null;
  onPoliticianClick?: (name: string | null) => void;
  onShowTickerPanel?: (politicianName: string, tickers: CollapsedTicker[]) => void;
}

const PARTY_COLORS: Record<string, string> = {
  Democratic:  "#3B82F6",
  Republican:  "#F97316",   // orange — distinct from the red used for negative alpha
  Independent: "#A855F7",
  Other:       "#64748B",
};

const alphaColor = d3
  .scaleLinear<string>()
  .domain([-0.3, 0, 0.3])
  .clamp(true)
  .range(["#EF4444", "#475569", "#22C55E"]);

const formatVolume = (v: number) =>
  v >= 1_000_000
    ? `$${(v / 1_000_000).toFixed(1)}M`
    : `$${(v / 1_000).toFixed(0)}K`;

const formatAlpha = (a: number | null) =>
  a == null ? "N/A" : `${a >= 0 ? "+" : ""}${(a * 100).toFixed(1)}%`;

// Stable key for each arc node — used by D3 join to track nodes across updates
function nodeKey(d: d3.HierarchyRectangularNode<HierarchyData>): string {
  return d.ancestors().map((n) => n.data.name).reverse().join("/");
}

function getArcColor(d: d3.HierarchyRectangularNode<HierarchyData>): string {
  if (d.depth === 1) {
    const party = (d.data as { name: string }).name;
    return PARTY_COLORS[party] ?? PARTY_COLORS["Other"];
  }
  if (d.depth === 2) {
    const node = d.data as unknown as PoliticianNode;
    if (node.weighted_alpha == null) return PARTY_COLORS["Other"];
    return alphaColor(node.weighted_alpha);
  }
  const node = d.parent?.data as unknown as PoliticianNode;
  if (node?.weighted_alpha != null) {
    return d3.color(alphaColor(node.weighted_alpha))!.copy({ opacity: 0.6 }).formatRgb();
  }
  return "#4B5563";
}

function getTooltipHtml(d: d3.HierarchyRectangularNode<HierarchyData>): string {
  if (d.depth === 1) {
    const party = (d.data as { name: string }).name;
    const politicianCount = (d.children ?? []).reduce((sum, child) => {
      const node = child.data as unknown as PoliticianNode;
      if (node.collapsed) {
        const n = parseInt(node.name);
        return sum + (isNaN(n) ? 1 : n);
      }
      return sum + 1;
    }, 0);
    return `
      <div class="tt-title">${party}</div>
      <div class="tt-row"><span>Politicians</span><span>${politicianCount}</span></div>
      <div class="tt-row"><span>Total Volume</span><span>${formatVolume(d.value ?? 0)}</span></div>
    `;
  }
  if (d.depth === 2) {
    const node = d.data as unknown as PoliticianNode;
    const alpha = node.weighted_alpha;
    const cls = alpha == null ? "" : alpha >= 0 ? "positive" : "negative";
    return `
      <div class="tt-title">${node.name}</div>
      <div class="tt-row"><span>Alpha vs SPY</span><span class="${cls}">${formatAlpha(alpha)}</span></div>
      <div class="tt-row"><span>Total Volume</span><span>${formatVolume(node.total_volume)}</span></div>
      <div class="tt-row"><span>Trades</span><span>${node.trade_count}</span></div>
    `;
  }
  if (d.depth === 3) {
    const node = d.data as unknown as TickerNode;
    const politician = d.parent?.data as unknown as PoliticianNode;
    const alpha = node.collapsed ? null : (node.alpha ?? null);
    const cls = alpha == null ? "" : alpha >= 0 ? "positive" : "negative";
    return `
      <div class="tt-title">${node.name}</div>
      ${alpha != null ? `<div class="tt-row"><span>Alpha vs SPY</span><span class="${cls}">${formatAlpha(alpha)}</span></div>` : ""}
      <div class="tt-row"><span>Volume</span><span>${formatVolume(node.value)}</span></div>
      ${politician ? `<div class="tt-row"><span>Trader</span><span>${politician.name}</span></div>` : ""}
    `;
  }
  return "";
}

type ArcAngles = { x0: number; x1: number; y0: number; y1: number };

function isCollapsed(d: d3.HierarchyRectangularNode<HierarchyData>): boolean {
  return d.depth === 3 && !!(d.data as unknown as TickerNode).collapsed;
}

function isCollapsedPolitician(d: d3.HierarchyRectangularNode<HierarchyData>): boolean {
  return d.depth === 2 && !!(d.data as unknown as PoliticianNode).collapsed;
}

// Minimum angle (radians) guaranteed to each party ring segment
const MIN_PARTY_ARC = (12 * Math.PI) / 180; // 12°

function rescaleSubtree(
  node: d3.HierarchyRectangularNode<HierarchyData>,
  newX0: number,
  newX1: number
): void {
  const oldSpan = node.x1 - node.x0;
  const newSpan = newX1 - newX0;
  if (node.children && oldSpan > 0) {
    for (const child of node.children) {
      rescaleSubtree(
        child,
        newX0 + ((child.x0 - node.x0) / oldSpan) * newSpan,
        newX0 + ((child.x1 - node.x0) / oldSpan) * newSpan
      );
    }
  }
  node.x0 = newX0;
  node.x1 = newX1;
}

function enforceMinPartyArcs(root: d3.HierarchyRectangularNode<HierarchyData>): void {
  const parties = root.children;
  if (!parties || parties.length === 0) return;
  const total = 2 * Math.PI;
  const totalValue = root.value ?? 1;
  const floored = parties.map((d) => Math.max((d.value ?? 0) / totalValue * total, MIN_PARTY_ARC));
  const scale = total / floored.reduce((s, a) => s + a, 0);
  let cursor = 0;
  for (let i = 0; i < parties.length; i++) {
    const arcSize = floored[i] * scale;
    rescaleSubtree(parties[i], cursor, cursor + arcSize);
    cursor += arcSize;
  }
}

// Ring midpoints in a 4-level partition (root→party→politician→ticker, size=[2π,radius])
const RING2_MID_FRACTION  = 5 / 8;  // depth 2: (radius/2 + 3*radius/4) / 2
const RING3_MID_FRACTION  = 7 / 8;  // depth 3: (3*radius/4 + radius) / 2
// In crowded mode (floor × n > arc), each slice gets this fraction of equal share as floor
const LABEL_FLOOR_ALPHA   = 0.5;   // used for politician ring (depth 2)
const TICKER_FLOOR_ALPHA  = 0.8;   // used for ticker ring (depth 3) — more even distribution

function enforceMinPoliticianArcs(
  root: d3.HierarchyRectangularNode<HierarchyData>,
  radius: number
): void {
  // Arc length at ring-2 midpoint needed to show a label — add 2px margin so
  // politicians at the floor always clear the label visibility filter.
  const minLabelArc = MIN_ARC_PX[2] / (radius * RING2_MID_FRACTION);

  for (const party of root.children ?? []) {
    const politicians = party.children;
    if (!politicians || politicians.length === 0) continue;

    const partyArc  = party.x1 - party.x0;
    const n         = politicians.length;
    const totalVal  = party.value ?? 1;

    // Case 1: everyone fits with the full label floor → use it
    // Case 2: too crowded → scale floor down to LABEL_FLOOR_ALPHA × equal share
    const floorArc  = n * minLabelArc <= partyArc
      ? minLabelArc
      : (partyArc / n) * LABEL_FLOOR_ALPHA;

    const remaining = Math.max(0, partyArc - n * floorArc);

    let cursor = party.x0;
    for (const politician of politicians) {
      const fraction = totalVal > 0 ? (politician.value ?? 0) / totalVal : 1 / n;
      rescaleSubtree(politician, cursor, cursor + floorArc + fraction * remaining);
      cursor += floorArc + fraction * remaining;
    }
  }
}

function enforceMinTickerArcs(
  root: d3.HierarchyRectangularNode<HierarchyData>,
  radius: number
): void {
  const minLabelArc = MIN_ARC_PX[3] / (radius * RING3_MID_FRACTION);

  for (const party of root.children ?? []) {
    for (const politician of party.children ?? []) {
      const tickers = politician.children;
      if (!tickers || tickers.length === 0) continue;

      const polArc  = politician.x1 - politician.x0;
      const n       = tickers.length;
      const totalVal = politician.value ?? 1;

      const floorArc = n * minLabelArc <= polArc
        ? minLabelArc
        : (polArc / n) * TICKER_FLOOR_ALPHA;

      const remaining = Math.max(0, polArc - n * floorArc);

      let cursor = politician.x0;
      for (const ticker of tickers) {
        const fraction = totalVal > 0 ? (ticker.value ?? 0) / totalVal : 1 / n;
        rescaleSubtree(ticker, cursor, cursor + floorArc + fraction * remaining);
        cursor += floorArc + fraction * remaining;
      }
    }
  }
}

// Minimum arc length (px) at midpoint radius required to show a label
const MIN_ARC_PX: Record<number, number> = { 1: 0, 2: 20, 3: 14 };

function getLabelText(d: d3.HierarchyRectangularNode<HierarchyData>): string {
  if (d.depth === 1) return (d.data as { name: string }).name;
  if (d.depth === 2) {
    const node = d.data as unknown as PoliticianNode;
    if (node.collapsed) return node.name; // "N others" — show as-is
    if (d.x1 - d.x0 > 1.5 * Math.PI) return node.name; // full name when zoomed
    const parts = node.name.trim().split(/\s+/);
    return parts[parts.length - 1] ?? node.name; // last name only
  }
  if (d.depth === 3) return (d.data as unknown as TickerNode).name;
  return "";
}

function getLabelTransform(d: d3.HierarchyRectangularNode<HierarchyData>): string {
  const angle  = (d.x0 + d.x1) / 2;          // midpoint angle in radians
  const r      = (d.y0 + d.y1) / 2;           // midpoint radius
  // When any ring is zoomed to fill the full circle (arc > 270°) the tangent formula puts
  // the label at the bottom oriented vertically. Pin it horizontally at the top instead.
  if ((d.depth === 1 || d.depth === 2) && (d.x1 - d.x0) > 1.5 * Math.PI) {
    return `translate(0, -${r})`;
  }
  const deg    = angle * 180 / Math.PI - 90;   // rotate to tangent, offset for SVG 0=right
  const flip   = angle > Math.PI ? 180 : 0;    // keep text right-side up in lower half
  return `rotate(${deg}) translate(${r}, 0) rotate(${flip})`;
}

function arcLength(d: d3.HierarchyRectangularNode<HierarchyData>): number {
  return ((d.y0 + d.y1) / 2) * (d.x1 - d.x0);
}

function getLabelFontSize(d: d3.HierarchyRectangularNode<HierarchyData>): number {
  return d.depth === 1 ? 11 : d.depth === 2 ? 9 : 8;
}

function getLabelColor(_d: d3.HierarchyRectangularNode<HierarchyData>): string {
  return "rgba(255,255,255,0.88)";
}

export default function Sunburst({ data, totalPoliticians, width = 800, height = 800, expandedPoliticians, zoomedParty, onPartyClick, zoomedPolitician, onPoliticianClick, onShowTickerPanel }: SunburstProps) {
  const svgRef      = useRef<SVGSVGElement>(null);
  const gRef        = useRef<d3.Selection<SVGGElement, unknown, null, undefined> | null>(null);
  const tooltipRef  = useRef<d3.Selection<HTMLDivElement, unknown, HTMLElement, unknown> | null>(null);
  const centerRef   = useRef<d3.Selection<SVGGElement, unknown, null, undefined> | null>(null);
  const prevAngles  = useRef<Map<string, ArcAngles>>(new Map());

  // One-time setup: create the <g> and tooltip
  useEffect(() => {
    if (!svgRef.current) return;
    gRef.current = d3.select(svgRef.current).append("g");
    const cg = gRef.current.append("g").attr("class", "center-label").attr("pointer-events", "none");
    cg.append("text").attr("class", "center-count").attr("text-anchor", "middle");
    cg.append("text").attr("class", "center-sub").attr("text-anchor", "middle");
    centerRef.current = cg;
    tooltipRef.current = d3
      .select("body")
      .append("div")
      .attr("class", "sunburst-tooltip")
      .style("opacity", 0);
    return () => {
      tooltipRef.current?.remove();
      tooltipRef.current = null;
      gRef.current?.remove();
      gRef.current = null;
      centerRef.current = null;
    };
  }, []);

  // Data update: runs whenever data, dimensions, or click handler changes
  useEffect(() => {
    if (!svgRef.current || !gRef.current || !tooltipRef.current) return;

    const tooltip = tooltipRef.current;
    const radius  = Math.min(width, height) / 2;

    d3.select(svgRef.current).attr("width", width).attr("height", height);
    gRef.current.attr("transform", `translate(${width / 2}, ${height / 2})`);

    const partitionRoot = d3
      .partition<HierarchyData>()
      .size([2 * Math.PI, radius])(
        d3
          .hierarchy(data)
          .sum((d) => ("value" in d ? (d as { value?: number }).value ?? 0 : 0))
          .sort((a, b) => {
            // Collapsed "N others" nodes always sort to the end of their parent arc
            if (a.depth === 2) {
              const aCol = !!(a.data as unknown as PoliticianNode).collapsed;
              const bCol = !!(b.data as unknown as PoliticianNode).collapsed;
              if (aCol !== bCol) return aCol ? 1 : -1;
            }
            if (a.depth === 3) {
              const aCol = !!(a.data as unknown as TickerNode).collapsed;
              const bCol = !!(b.data as unknown as TickerNode).collapsed;
              if (aCol !== bCol) return aCol ? 1 : -1;
            }
            return (b.value ?? 0) - (a.value ?? 0);
          })
      );

    const arc = d3
      .arc<ArcAngles>()
      .startAngle((d) => d.x0)
      .endAngle((d) => d.x1)
      .innerRadius((d) => d.y0)
      .outerRadius((d) => d.y1 - 1);

    enforceMinPartyArcs(partitionRoot);
    if (zoomedParty) {
      const zoomTarget = partitionRoot.children?.find((d) => d.data.name === zoomedParty);
      if (zoomTarget) rescaleSubtree(zoomTarget, 0, 2 * Math.PI);
    }

    enforceMinPoliticianArcs(partitionRoot, radius);

    // Find zoomed politician (if any) and rescale it + its parent party to fill the circle
    const zoomedPolNode = zoomedPolitician
      ? (partitionRoot.children
          ?.flatMap((p) => p.children ?? [])
          .find((d) => (d.data as unknown as PoliticianNode).name === zoomedPolitician) ?? null)
      : null;
    if (zoomedPolNode) {
      rescaleSubtree(zoomedPolNode.parent!, 0, 2 * Math.PI);
      rescaleSubtree(zoomedPolNode, 0, 2 * Math.PI);
    }

    enforceMinTickerArcs(partitionRoot, radius);

    const nodes = zoomedPolNode
      ? [zoomedPolNode.parent!, ...zoomedPolNode.descendants()]
      : zoomedParty
      ? (partitionRoot.children?.find((d) => d.data.name === zoomedParty)?.descendants() ?? [])
      : partitionRoot.descendants().filter((d) => d.depth > 0);

    gRef.current
      .selectAll<SVGPathElement, d3.HierarchyRectangularNode<HierarchyData>>("path")
      .data(nodes, nodeKey)
      .join(
        (enter) =>
          enter
            .append("path")
            .attr("fill", getArcColor)
            .attr("stroke", (d) => (isCollapsed(d) || isCollapsedPolitician(d)) ? "#fff" : "#111")
            .attr("stroke-width", (d) => (isCollapsed(d) || isCollapsedPolitician(d)) ? 1.5 : 0.5)
            .attr("stroke-dasharray", (d) => (isCollapsed(d) || isCollapsedPolitician(d)) ? "3,2" : "none")
            .style("cursor", "pointer")
            .each(function (d) {
              // Store initial angles so first render has no tween artifact
              prevAngles.current.set(nodeKey(d), { x0: d.x0, x1: d.x1, y0: d.y0, y1: d.y1 });
            })
            .attr("d", (d) => arc(d) ?? ""),
        (update) =>
          update
            .attr("fill", getArcColor)
            .attr("stroke", (d) => (isCollapsed(d) || isCollapsedPolitician(d)) ? "#fff" : "#111")
            .attr("stroke-width", (d) => (isCollapsed(d) || isCollapsedPolitician(d)) ? 1.5 : 0.5)
            .attr("stroke-dasharray", (d) => (isCollapsed(d) || isCollapsedPolitician(d)) ? "3,2" : "none")
            .transition()
            .duration(600)
            .attrTween("d", function (d) {
              const key  = nodeKey(d);
              const prev = prevAngles.current.get(key) ?? { x0: d.x0, x1: d.x1, y0: d.y0, y1: d.y1 };
              const next = { x0: d.x0, x1: d.x1, y0: d.y0, y1: d.y1 };
              const interp = d3.interpolateObject(prev, next);
              prevAngles.current.set(key, next);
              return (t: number) => arc(interp(t)) ?? "";
            }),
        (exit) =>
          exit.transition().duration(300).style("opacity", 0).remove()
      )
      .on("click", (_event: MouseEvent, d) => {
        if (d.depth === 1) {
          if (zoomedPolitician) {
            // Clicking the party ring while in politician zoom exits politician zoom
            onPoliticianClick?.(null);
          } else {
            const partyName = (d.data as { name: string }).name;
            onPartyClick?.(zoomedParty === partyName ? null : partyName);
          }
          return;
        }
        if (d.depth === 2 && !isCollapsedPolitician(d)) {
          const politicianName = (d.data as unknown as PoliticianNode).name;
          onPoliticianClick?.(zoomedPolitician === politicianName ? null : politicianName);
          return;
        }
        if (isCollapsed(d)) {
          // "N others" ticker clicked — open panel with full collapsed list
          const tickerNode = d.data as unknown as TickerNode;
          const politicianName = (d.parent?.data as unknown as PoliticianNode)?.name;
          if (politicianName && tickerNode.collapsed_tickers?.length) {
            onShowTickerPanel?.(politicianName, tickerNode.collapsed_tickers);
          }
        }
      })
      .on("mouseover", (event: MouseEvent, d) => {
        d3.select(event.currentTarget as Element)
          .attr("stroke", "#fff")
          .attr("stroke-width", 1.5);
        tooltip.html(getTooltipHtml(d)).style("opacity", 1);
      })
      .on("mousemove", (event: MouseEvent) => {
        tooltip
          .style("left", `${event.pageX + 14}px`)
          .style("top",  `${event.pageY - 28}px`);
      })
      .on("mouseout", (event: MouseEvent) => {
        d3.select(event.currentTarget as Element)
          .attr("stroke", "#111")
          .attr("stroke-width", 0.5);
        tooltip.style("opacity", 0);
      });

    // Labels
    const labelNodes = nodes.filter(
      (d) => arcLength(d) >= (MIN_ARC_PX[d.depth] ?? 999)
    );

    gRef.current
      .selectAll<SVGTextElement, d3.HierarchyRectangularNode<HierarchyData>>("text.arc-label")
      .data(labelNodes, nodeKey)
      .join(
        (enter) =>
          enter
            .append("text")
            .attr("class", "arc-label")
            .attr("transform", getLabelTransform)
            .attr("text-anchor", "middle")
            .attr("dominant-baseline", "middle")
            .attr("font-size", getLabelFontSize)
            .attr("fill", getLabelColor)
            .attr("pointer-events", "none")
            .style("user-select", "none")
            .text(getLabelText),
        (update) =>
          update
            .text(getLabelText)
            .attr("font-size", getLabelFontSize)
            .attr("fill", getLabelColor)
            .transition()
            .duration(600)
            .attr("transform", getLabelTransform),
        (exit) =>
          exit.transition().duration(300).style("opacity", 0).remove()
      );

    // Center label — count of visible politicians (update in place, no remove/reappend)
    if (centerRef.current) {
      const activeCount = nodes
        .filter((d) => d.depth === 2)
        .reduce((sum, d) => {
          const node = d.data as unknown as PoliticianNode;
          if (node.collapsed) {
            const n = parseInt(node.name);
            return sum + (isNaN(n) ? 1 : n);
          }
          return sum + 1;
        }, 0);
      const innerRadius = radius / (partitionRoot.height + 1);
      const countFontSize = Math.min(Math.round(innerRadius * 0.55), 28);
      centerRef.current.select(".center-count")
        .attr("dy", "-0.25em")
        .attr("font-size", countFontSize)
        .attr("font-weight", "700")
        .attr("fill", "#f3f4f6")
        .text(`${activeCount} / ${totalPoliticians}`);
      centerRef.current.select(".center-sub")
        .attr("dy", "1.1em")
        .attr("font-size", Math.max(9, Math.round(countFontSize * 0.38)))
        .attr("letter-spacing", "0.05em")
        .attr("fill", "#6b7280")
        .text("active traders");
    }

  }, [data, width, height, expandedPoliticians, zoomedParty, onPartyClick, zoomedPolitician, onPoliticianClick, onShowTickerPanel]);

  return <svg ref={svgRef} />;
}
