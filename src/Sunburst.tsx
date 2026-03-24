import { useRef, useEffect } from "react";
import * as d3 from "d3";
import type { HierarchyData, PoliticianNode, TickerNode } from "./types";

interface SunburstProps {
  data: HierarchyData;
  width?: number;
  height?: number;
  expandedPoliticians?: Set<string>;
  onCollapsedClick?: (politicianName: string) => void;
}

const PARTY_COLORS: Record<string, string> = {
  Democratic:  "#3B82F6",
  Republican:  "#EF4444",
  Independent: "#A855F7",
  Other:       "#6B7280",
};

const alphaColor = d3
  .scaleLinear<string>()
  .domain([-0.3, 0, 0.3])
  .clamp(true)
  .range(["#EF4444", "#6B7280", "#22C55E"]);

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
    return `
      <div class="tt-title">${party}</div>
      <div class="tt-row"><span>Politicians</span><span>${d.children?.length ?? 0}</span></div>
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
    return `
      <div class="tt-title">${node.name}</div>
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

export default function Sunburst({ data, width = 800, height = 800, expandedPoliticians, onCollapsedClick }: SunburstProps) {
  const svgRef     = useRef<SVGSVGElement>(null);
  const gRef       = useRef<d3.Selection<SVGGElement, unknown, null, undefined> | null>(null);
  const tooltipRef = useRef<d3.Selection<HTMLDivElement, unknown, HTMLElement, unknown> | null>(null);
  const prevAngles = useRef<Map<string, ArcAngles>>(new Map());

  // One-time setup: create the <g> and tooltip
  useEffect(() => {
    if (!svgRef.current) return;
    gRef.current = d3.select(svgRef.current).append("g");
    tooltipRef.current = d3
      .select("body")
      .append("div")
      .attr("class", "sunburst-tooltip")
      .style("opacity", 0);
    return () => { tooltipRef.current?.remove(); };
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
          .sort((a, b) => (b.value ?? 0) - (a.value ?? 0))
      );

    const arc = d3
      .arc<ArcAngles>()
      .startAngle((d) => d.x0)
      .endAngle((d) => d.x1)
      .innerRadius((d) => d.y0)
      .outerRadius((d) => d.y1 - 1);

    const nodes = partitionRoot.descendants().filter((d) => d.depth > 0);

    gRef.current
      .selectAll<SVGPathElement, d3.HierarchyRectangularNode<HierarchyData>>("path")
      .data(nodes, nodeKey)
      .join(
        (enter) =>
          enter
            .append("path")
            .attr("fill", getArcColor)
            .attr("stroke", (d) => isCollapsed(d) ? "#fff" : "#111")
            .attr("stroke-width", (d) => isCollapsed(d) ? 1.5 : 0.5)
            .attr("stroke-dasharray", (d) => isCollapsed(d) ? "3,2" : "none")
            .style("cursor", "pointer")
            .each(function (d) {
              // Store initial angles so first render has no tween artifact
              prevAngles.current.set(nodeKey(d), { x0: d.x0, x1: d.x1, y0: d.y0, y1: d.y1 });
            })
            .attr("d", (d) => arc(d) ?? ""),
        (update) =>
          update
            .attr("fill", getArcColor)
            .attr("stroke", (d) => isCollapsed(d) ? "#fff" : "#111")
            .attr("stroke-width", (d) => isCollapsed(d) ? 1.5 : 0.5)
            .attr("stroke-dasharray", (d) => isCollapsed(d) ? "3,2" : "none")
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
        if (!onCollapsedClick) return;
        if (isCollapsed(d)) {
          // "N others" clicked — expand
          const politicianName = (d.parent?.data as unknown as PoliticianNode)?.name;
          if (politicianName) onCollapsedClick(politicianName);
        } else if (d.depth === 2) {
          // Politician arc clicked — collapse if currently expanded
          const politicianName = (d.data as unknown as PoliticianNode).name;
          if (expandedPoliticians?.has(politicianName)) onCollapsedClick(politicianName);
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

  }, [data, width, height, expandedPoliticians, onCollapsedClick]);

  return <svg ref={svgRef} />;
}
