export interface Balance {
  free: number;
  used: number;
  total: number;
}

export interface ExchangeBalance {
  exchange: string;
  balances: {
    BTC: Balance;
    ETH: Balance;
    SOL: Balance;
    USDT: Balance;
  };
}

export interface OrderBookEntry {
  price: number;
  amount: number;
}

export interface OrderBook {
  exchange: string;
  symbol: string;
  bids: OrderBookEntry[];
  asks: OrderBookEntry[];
  timestamp: string;
}

export interface ArbitrageOpportunity {
  buy_exchange: string;
  sell_exchange: string;
  symbol: string;
  buy_price: number;
  sell_price: number;
  spread_percentage: number;
  potential_profit_percentage: number;
  max_trade_amount: number;
  timestamp: string;
}

export interface Trade {
  id: string;
  exchange: string;
  symbol: string;
  side: string;
  amount: number;
  price: number;
  cost: number;
  fee: number;
  timestamp: string;
  is_test: boolean;
}

export interface ArbitrageTrade {
  id: string;
  buy_trade: Trade;
  sell_trade: Trade;
  profit: number;
  profit_percentage: number;
  timestamp: string;
  is_test: boolean;
}

export interface TestModeSettings {
  enabled: boolean;
  capital_per_pair: {
    "BTC/USDT"?: number;
    "ETH/USDT"?: number;
    "SOL/USDT"?: number;
  };
  buffer_percentage: number;
  exchanges: string[];
}

export interface BotStatus {
  running: boolean;
  test_mode: boolean;
  connected_exchanges: string[];
  last_update: string;
  error?: string;
}

export interface ExchangeCredentials {
  exchange: string;
  api_key: string;
  api_secret: string;
  additional_params?: Record<string, string>;
}
