import { useRef, useEffect } from "react";
import * as d3 from "d3";
import type { HierarchyData } from "./types";

interface SunburstProps {
  data: HierarchyData;
  width?: number;
  height?: number;
}

export default function Sunburst({ data, width = 800, height = 800 }: SunburstProps) {
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    if (!svgRef.current) return;

    // D3 owns the SVG DOM — clear on each render
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
      .attr("fill", "#ccc")
      .attr("stroke", "#fff")
      .attr("stroke-width", 0.5);

  }, [data, width, height]);

  return <svg ref={svgRef} />;
}
