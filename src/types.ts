export interface CollapsedTicker {
  name: string;
  value: number;
}

export interface TickerNode {
  name: string;
  value: number;
  collapsed?: boolean;
  collapsed_tickers?: CollapsedTicker[];
}

export interface PoliticianNode {
  name: string;
  party_code: string;
  weighted_alpha: number | null;
  total_volume: number;
  trade_count: number;
  children: TickerNode[];
}

export interface PartyNode {
  name: string;
  children: PoliticianNode[];
}

export interface HierarchyData {
  name: string;
  children: PartyNode[];
}
