import { useRef, useEffect } from "react";
import * as d3 from "d3";
import type { HierarchyData, PoliticianNode, TickerNode } from "./types";

interface SunburstProps {
  data: HierarchyData;
  width?: number;
  height?: number;
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
  const politicianNode = d.parent;
  if (politicianNode) {
    const node = politicianNode.data as unknown as PoliticianNode;
    if (node.weighted_alpha != null) {
      return d3.color(alphaColor(node.weighted_alpha))!.copy({ opacity: 0.6 }).formatRgb();
    }
  }
  return "#4B5563";
}

function getTooltipHtml(d: d3.HierarchyRectangularNode<HierarchyData>): string {
  if (d.depth === 1) {
    const party = (d.data as { name: string }).name;
    const politicianCount = d.children?.length ?? 0;
    const totalVolume = d.value ?? 0;
    return `
      <div class="tt-title">${party}</div>
      <div class="tt-row"><span>Politicians</span><span>${politicianCount}</span></div>
      <div class="tt-row"><span>Total Volume</span><span>${formatVolume(totalVolume)}</span></div>
    `;
  }
  if (d.depth === 2) {
    const node = d.data as unknown as PoliticianNode;
    const alpha = node.weighted_alpha;
    const alphaStr = formatAlpha(alpha);
    const alphaClass = alpha == null ? "" : alpha >= 0 ? "positive" : "negative";
    return `
      <div class="tt-title">${node.name}</div>
      <div class="tt-row"><span>Alpha vs SPY</span><span class="${alphaClass}">${alphaStr}</span></div>
      <div class="tt-row"><span>Total Volume</span><span>${formatVolume(node.total_volume)}</span></div>
      <div class="tt-row"><span>Trades</span><span>${node.trade_count}</span></div>
    `;
  }
  if (d.depth === 3) {
    const node = d.data as unknown as TickerNode;
    const politicianNode = d.parent?.data as unknown as PoliticianNode;
    return `
      <div class="tt-title">${node.name}</div>
      <div class="tt-row"><span>Volume</span><span>${formatVolume(node.value)}</span></div>
      ${politicianNode ? `<div class="tt-row"><span>Trader</span><span>${politicianNode.name}</span></div>` : ""}
    `;
  }
  return "";
}

export default function Sunburst({ data, width = 800, height = 800 }: SunburstProps) {
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    if (!svgRef.current) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const radius = Math.min(width, height) / 2;

    const g = svg
      .attr("width", width)
      .attr("height", height)
      .append("g")
      .attr("transform", `translate(${width / 2}, ${height / 2})`);

    // Tooltip div — appended to body so it floats above everything
    const tooltip = d3
      .select("body")
      .append("div")
      .attr("class", "sunburst-tooltip")
      .style("opacity", 0);

    const partitionRoot = d3
      .partition<HierarchyData>()
      .size([2 * Math.PI, radius])(
        d3
          .hierarchy(data)
          .sum((d) => ("value" in d ? (d as { value?: number }).value ?? 0 : 0))
          .sort((a, b) => (b.value ?? 0) - (a.value ?? 0))
      );

    const arc = d3
      .arc<d3.HierarchyRectangularNode<HierarchyData>>()
      .startAngle((d) => d.x0)
      .endAngle((d) => d.x1)
      .innerRadius((d) => d.y0)
      .outerRadius((d) => d.y1 - 1);

    g.selectAll("path")
      .data(partitionRoot.descendants().filter((d) => d.depth > 0))
      .join("path")
      .attr("d", (d) => arc(d) ?? "")
      .attr("fill", (d) => getArcColor(d))
      .attr("stroke", "#111")
      .attr("stroke-width", 0.5)
      .style("cursor", "pointer")
      .on("mouseover", (event: MouseEvent, d) => {
        d3.select(event.currentTarget as Element)
          .attr("stroke", "#fff")
          .attr("stroke-width", 1.5);
        tooltip
          .html(getTooltipHtml(d))
          .style("opacity", 1);
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

    // Cleanup tooltip on unmount
    return () => { tooltip.remove(); };
  }, [data, width, height]);

  return <svg ref={svgRef} />;
}
