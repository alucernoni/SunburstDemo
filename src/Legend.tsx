export default function Legend() {
  return (
    <div className="legend">
      {/* Alpha color scale */}
      <div className="legend-section">
        <span className="legend-title">Alpha vs S&amp;P 500</span>
        <div className="legend-gradient-row">
          <span className="legend-tick negative">−30%</span>
          <div className="legend-gradient" />
          <span className="legend-tick">0%</span>
          <div className="legend-gradient legend-gradient-pos" />
          <span className="legend-tick positive">+30%</span>
        </div>
      </div>

      {/* Party swatches */}
      <div className="legend-section">
        <span className="legend-title">Party</span>
        <div className="legend-swatches">
          {[
            { label: "Democratic",  color: "#3B82F6" },
            { label: "Republican",  color: "#EF4444" },
            { label: "Independent", color: "#A855F7" },
          ].map(({ label, color }) => (
            <div key={label} className="legend-swatch-row">
              <span className="legend-swatch" style={{ background: color }} />
              <span>{label}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Interaction hints */}
      <div className="legend-section legend-hints">
        <span>Click <span className="hint-dashed">- - -</span> arc to expand tickers</span>
        <span>Click politician arc to collapse</span>
      </div>
    </div>
  );
}
