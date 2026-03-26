export interface CollapsedTicker {
  name: string;
  value: number;
  alpha?: number | null;
}

export interface TickerNode {
  name: string;
  value: number;
  alpha?: number | null;
  collapsed?: boolean;
  collapsed_tickers?: CollapsedTicker[];
}

export interface PoliticianNode {
  name: string;
  party_code: string;
  weighted_alpha: number | null;
  total_volume: number;
  trade_count: number;
  is_current: boolean;
  collapsed?: boolean;
  value?: number;    // set on collapsed "N others" nodes so D3's .sum() accounts for their volume
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
