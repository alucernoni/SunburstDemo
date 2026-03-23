import { useRef, useEffect } from "react";
import * as d3 from "d3";
import type { HierarchyData, PoliticianNode } from "./types";

interface SunburstProps {
  data: HierarchyData;
  width?: number;
  height?: number;
}

// Party colors for the inner ring
const PARTY_COLORS: Record<string, string> = {
  Democratic:  "#3B82F6", // blue
  Republican:  "#EF4444", // red
  Independent: "#A855F7", // purple
  Other:       "#6B7280", // gray
};

// Diverging color scale for politician alpha:
// red (underperformed) → gray (matched SPY) → green (outperformed)
const alphaColor = d3
  .scaleLinear<string>()
  .domain([-0.3, 0, 0.3])
  .clamp(true)
  .range(["#EF4444", "#6B7280", "#22C55E"]);

function getArcColor(d: d3.HierarchyRectangularNode<HierarchyData>): string {
  if (d.depth === 1) {
    // Party ring — use party color
    const party = (d.data as { name: string }).name;
    return PARTY_COLORS[party] ?? PARTY_COLORS["Other"];
  }

  if (d.depth === 2) {
    // Politician ring — color by weighted alpha
    const node = d.data as unknown as PoliticianNode;
    if (node.weighted_alpha == null) return PARTY_COLORS["Other"];
    return alphaColor(node.weighted_alpha);
  }

  // Ticker ring — inherit politician's alpha color at reduced opacity
  const politicianNode = d.parent;
  if (politicianNode) {
    const node = politicianNode.data as unknown as PoliticianNode;
    if (node.weighted_alpha != null) {
      return d3.color(alphaColor(node.weighted_alpha))!.copy({ opacity: 0.6 }).formatRgb();
    }
  }
  return "#4B5563";
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

    // Partition layout
    const root = d3
      .hierarchy(data)
      .sum((d) => ("value" in d ? (d as { value?: number }).value ?? 0 : 0))
      .sort((a, b) => (b.value ?? 0) - (a.value ?? 0));

    const partitionRoot = d3.partition<HierarchyData>().size([2 * Math.PI, radius])(root);

    // Arc generator
    const arc = d3
      .arc<d3.HierarchyRectangularNode<HierarchyData>>()
      .startAngle((d) => d.x0)
      .endAngle((d) => d.x1)
      .innerRadius((d) => d.y0)
      .outerRadius((d) => d.y1 - 1);

    // Draw arcs
    g.selectAll("path")
      .data(partitionRoot.descendants().filter((d) => d.depth > 0))
      .join("path")
      .attr("d", (d) => arc(d) ?? "")
      .attr("fill", (d) => getArcColor(d))
      .attr("stroke", "#111")
      .attr("stroke-width", 0.5);

  }, [data, width, height]);

  return <svg ref={svgRef} />;
}
