import { useState, useEffect } from "react";
import Sunburst from "./Sunburst";
import type { HierarchyData } from "./types";

export default function App() {
  const [data, setData] = useState<HierarchyData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/hierarchy.json")
      .then((r) => {
        if (!r.ok) throw new Error(`Failed to load hierarchy.json (${r.status})`);
        return r.json() as Promise<HierarchyData>;
      })
      .then(setData)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  if (error) return <div style={{ padding: 24, color: "red" }}>Error: {error}</div>;
  if (!data)  return <div style={{ padding: 24 }}>Loading...</div>;

  return (
    <main style={{ display: "flex", justifyContent: "center", padding: 24 }}>
      <Sunburst data={data} width={800} height={800} />
    </main>
  );
}
