// frontend/src/types.ts

// Represents the structure of a balance for a single asset
export interface AssetBalance {
  free: number;
  used: number;
  total: number;
}

// Represents balances for multiple assets on a single exchange
export interface ExchangeBalance {
  exchange: string;
  balances: Record<string, AssetBalance>; // e.g., {"USDT": AssetBalance, "BTC": AssetBalance}
}

// Represents an entry in an order book (bid or ask)
export interface OrderBookEntry {
  price: number;
  amount: number;
}

// Represents the order book for a specific trading pair on an exchange
export interface OrderBook {
  exchange: string;
  symbol: string;
  bids: OrderBookEntry[];
  asks: OrderBookEntry[];
  timestamp: string; // ISO 8601 datetime string
}

// Represents a single trade leg (buy or sell)
export interface TradeLeg {
  id: string;
  exchange: string;
  symbol: string;
  side: "buy" | "sell";
  amount: number;    // Amount in base currency
  price: number;     // Price in quote currency
  fee: number;       // Fee in quote currency
  timestamp: string; // ISO 8601 datetime string
}

// Represents a completed arbitrage trade (both buy and sell legs)
export interface ArbitrageTrade {
  id: string; // Unique ID for the arbitrage event
  opportunity_id: string; // ID of the opportunity that led to this trade
  timestamp: string; // ISO 8601 datetime string
  symbol: string;
  buy_trade: TradeLeg;
  sell_trade: TradeLeg;
  profit: number;          // Net profit in quote currency (e.g., USDT)
  profit_percentage: number;
  is_test: boolean;
}

// Represents a potential arbitrage opportunity
export interface ArbitrageOpportunity {
  id: string;
  buy_exchange: string;
  sell_exchange: string;
  symbol: string;
  buy_price: number;
  sell_price: number;
  spread_percentage: number;
  potential_profit_percentage: number;
  max_trade_amount: number; // Max amount in base currency
  timestamp: string; // ISO 8601 datetime string
}

// Represents an alert or system message
export interface AlertMessage {
  id: string; // Added for unique key in lists
  type: "info" | "warning" | "error" | "success" | "trade_success" | "trade_error" | "pair_disabled" | "exchange_disabled" | "global_halt" | "pair_reactivated" | "exchange_reactivated" | "global_reactivated" | "system_error";
  message: string;
  timestamp: string; // ISO 8601 datetime string
  entity?: string;    // e.g., pair, exchange_id, "global"
  can_reactivate?: boolean;
  severity?: "info" | "warning" | "error" | "critical";
}

// Represents the overall status of the bot from the backend
export interface BotStatus {
  is_running: boolean;
  is_test_mode: boolean;
  active_exchanges: string[];
  websocket_status: "Connected" | "Disconnected" | "Reconnecting" | "Error";
  // Add more fields as needed, e.g., current mode (live/test), specific test simulation status
}

// For test mode settings
export interface TestModeSettings {
  usdt_cap: number;
  asset_cap: number;
  buffer_percentage: number; // Stored as decimal, e.g., 0.0001 for 0.01%
  exchanges: string[];
}

// For failsafe status display
export interface FailsafeStatusData {
  disabled_pairs: Record<string, { timestamp: string; reason: string; duration_minutes: number }>;
  disabled_exchanges: Record<string, { timestamp: string; reason: string; duration_minutes: number }>;
  global_halt: boolean;
  global_halt_timestamp: string | null;
  // Add other relevant failsafe info if needed by UI
}

// For WebSocket messages
export interface WebSocketMessage {
  type: string; // e.g., "bot_status_update", "new_trade", "new_opportunity", "new_alert", "test_simulation_update"
  payload: any;
}

// Specific payload for test simulation status updates via WebSocket
export interface TestSimulationStatusPayload {
  status: "STARTING" | "RUNNING" | "STOPPED" | "ERROR";
  message?: string; // Optional message, e.g., error details
  active_since?: string; // ISO timestamp when it started running
  total_test_trades?: number;
  total_test_profit?: number;
}

