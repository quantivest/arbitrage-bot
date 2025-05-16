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
  timestamp: string; // ISO 8601 datetime string
  error?: string | null; // Optional error message if fetching balances failed
}

// Represents an entry in an order book (bid or ask)
export interface OrderBookEntry {
  price: number;
  quantity: number; 
}

// Represents the order book for a specific trading pair on an exchange
export interface OrderBook {
  exchange: string;
  pair: string; 
  bids: OrderBookEntry[];
  asks: OrderBookEntry[];
  timestamp: string; // ISO 8601 datetime string
}

// Represents a single trade leg (buy or sell)
export interface TradeLeg {
  exchange: string;
  pair: string; 
  side: "buy" | "sell";
  type: "market" | "limit"; 
  price: number;     
  amount_base: number;    
  amount_quote: number;   
  fee_amount?: number;       
  fee_currency?: string;   
  timestamp: string; // ISO 8601 datetime string
  status: "open" | "closed" | "canceled" | "expired" | "rejected"; 
}

// Represents a completed arbitrage trade (both buy and sell legs)
export interface ArbitrageTrade {
  id: string; 
  opportunity_id?: string; 
  timestamp: string; // ISO 8601 datetime string
  pair: string; 
  symbol: string; // Add this property to match usage in App.tsx
  buy_trade: TradeLeg;
  sell_trade: TradeLeg;
  profit_percentage: number;
  profit_quote: number; 
  is_test_trade: boolean; 
  status: "pending" | "completed" | "failed" | "partially_filled";
}

// Represents a potential arbitrage opportunity
export interface ArbitrageOpportunity {
  id: string;
  timestamp: string; // ISO 8601 datetime string
  pair: string;
  profit_percentage: number;
  buy_exchange: string;
  sell_exchange: string;
  buy_price: number;
  sell_price: number;
  potential_trade_volume_quote?: number; 
}

// Represents an alert or system message
export interface AlertMessage {
  id?: string; 
  type: string; 
  message: string;
  timestamp: string; // ISO 8601 datetime string
  severity: "info" | "warning" | "error" | "critical";
  entity_name?: string;    
}

export interface FailsafeStatusData {
  disabled_pairs: Record<string, { reason: string; cooldown_until?: string | null; attempts?: number }>;
  disabled_exchanges: Record<string, { reason: string; cooldown_until?: string | null; attempts?: number }>;
  global_trading_halt: boolean;
  global_halt_reason?: string | null;
  global_halt_timestamp?: string | null;
  historical_high_balance_usdt?: number;
}

// Represents the overall status of the bot from the backend (part of WebSocket payload)
export interface BotStatusPayload {
  is_bot_running: boolean;
  current_mode: "idle" | "live" | "test_simulating" | "test_idle";
  connected_exchanges: string[];
  websocket_connected: boolean; 
  last_status_update_ts: string; // ISO 8601 datetime string
  active_alerts: AlertMessage[];
  failsafe_status: FailsafeStatusData;
  exchange_balances?: ExchangeBalance[]; // Add this optional property
  live_total_trades?: number;
  live_total_profit?: number;
}

// For test mode settings sent to backend
export interface TestModeSettings {
  usdt_capital_per_exchange: number; 
  asset_capital_usd_per_pair: number;  // MODIFIED: Name matches frontend and intent
  buffer_percentage?: number; 
  exchanges?: string[]; 
}

// Specific payload for test simulation status updates (part of WebSocket payload)
export interface TestSimulationStatusPayload {
  status: "IDLE" | "STARTING" | "RUNNING" | "STOPPING" | "STOPPED" | "ERROR" | "UNKNOWN" | "INITIALIZING";
  message?: string;
  active_since?: string | null; // ISO timestamp
  total_test_trades: number;
  total_test_profit: number;
  error_message?: string | null;
}

// Structure for the full payload received via WebSocket initial_status or bot_status_update
export interface FullStatusUpdatePayload {
  bot_status: BotStatusPayload;
  test_simulation_status: TestSimulationStatusPayload;
  recent_trades: ArbitrageTrade[];
  recent_opportunities: ArbitrageOpportunity[];
  exchange_balances: ExchangeBalance[];
}

// For WebSocket messages
export interface WebSocketMessage {
  type: "initial_status" | "bot_status_update" | "new_trade" | "new_opportunity" | "new_alert" | "exchange_connected" | "exchange_disconnected" | "pong";
  payload: FullStatusUpdatePayload | ArbitrageTrade | ArbitrageOpportunity | AlertMessage | { exchange: string } | { timestamp: string } | any; 
}

// For API responses that are simple success/failure messages
export interface ActionResponse {
  success: boolean;
  message: string;
  data?: any; 
}

// For connecting to an exchange
export interface ExchangeCredentials {
  exchange: string;
  api_key: string;
  api_secret: string;
  additional_params?: Record<string, any>; 
}

// For starting the bot
export interface StartBotRequest {
  mode: "live" | "test";
  test_settings?: TestModeSettings;
}

// For reactivating a failsafe
export interface ReactivateRequest {
  type: "pair" | "exchange" | "global";
  entity_name?: string; 
}

