from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Union, Literal, Any
from datetime import datetime
from enum import Enum as PyEnum

# --- Exchange & Balance Models ---
class ExchangeCredentials(BaseModel):
    """Credentials for connecting to an exchange."""
    exchange: str = Field(..., description="Name of the exchange (e.g., binance, kraken)")
    api_key: str = Field(..., description="API key for the exchange")
    api_secret: str = Field(..., description="API secret for the exchange")
    additional_params: Optional[Dict[str, str]] = Field(default=None, description="Optional additional parameters (e.g., password for some exchanges)")

class Balance(BaseModel):
    """Represents the balance of a single asset on an exchange."""
    free: float = Field(..., description="Available balance not tied up in orders")
    used: float = Field(..., description="Balance currently used in open orders")
    total: float = Field(..., description="Total balance (free + used)")

class ExchangeBalance(BaseModel):
    """Represents all asset balances for a single connected exchange."""
    exchange: str = Field(..., description="Name of the exchange")
    balances: Dict[str, Balance] = Field(..., description="Dictionary of asset symbols to their Balance objects")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Timestamp of when the balance was last fetched")
    error: Optional[str] = Field(default=None, description="Error message if fetching balances failed for this exchange")

# --- Order Book & Opportunity Models ---
class OrderBookEntry(BaseModel):
    """A single entry (price level) in an order book."""
    price: float = Field(..., description="Price level")
    amount: float = Field(..., description="Quantity available at this price level")

class OrderBook(BaseModel):
    """Represents the order book for a specific trading pair on an exchange."""
    exchange: str = Field(..., description="Name of the exchange")
    symbol: str = Field(..., description="Trading pair symbol (e.g., BTC/USDT)")
    bids: List[OrderBookEntry] = Field(..., description="List of bid entries, sorted highest to lowest price")
    asks: List[OrderBookEntry] = Field(..., description="List of ask entries, sorted lowest to highest price")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Timestamp of when the order book was fetched")

class ArbitrageOpportunity(BaseModel):
    """Details of a potential arbitrage opportunity found between two exchanges."""
    id: str = Field(..., description="Unique identifier for the opportunity")
    buy_exchange: str = Field(..., description="Exchange to buy on")
    sell_exchange: str = Field(..., description="Exchange to sell on")
    symbol: str = Field(..., description="Trading pair symbol")
    buy_price: float = Field(..., description="Price to buy at")
    sell_price: float = Field(..., description="Price to sell at")
    potential_profit_percentage: float = Field(..., description="Estimated profit percentage after considering fees and buffer")
    max_tradeable_amount_base: float = Field(..., description="Maximum amount of base currency tradeable for this opportunity")
    max_tradeable_amount_quote: float = Field(..., description="Maximum amount of quote currency tradeable for this opportunity")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Timestamp when the opportunity was identified")
    source: Literal["live", "test"] = Field(default="live", description="Indicates if opportunity is from live or test data")

# --- Trade Models ---
class Trade(BaseModel):
    """Model for executed trade."""
    id: str = Field(..., description="Exchange-provided order ID or internal ID")
    exchange: str = Field(..., description="Name of the exchange")
    symbol: str = Field(..., description="Trading pair symbol")
    side: str = Field(..., description="Trade side (buy or sell)")
    amount: float = Field(..., description="Amount of base currency traded")
    price: float = Field(..., description="Average execution price")
    cost: float = Field(..., description="Total cost of the trade in quote currency (amount * price)")
    fee: float = Field(..., description="Fee paid for the trade")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Timestamp of trade execution or recording")
    is_test: bool = Field(default=False, description="Flag indicating if this was a simulated test trade")

class IndividualTrade(BaseModel):
    """Details of a single buy or sell trade executed as part of an arbitrage."""
    id: str = Field(..., description="Exchange-provided order ID or internal ID")
    exchange: str = Field(..., description="Name of the exchange")
    symbol: str = Field(..., description="Trading pair symbol")
    side: Literal["buy", "sell"] = Field(..., description="Trade side")
    amount: float = Field(..., description="Amount of base currency traded")
    price: float = Field(..., description="Average execution price")
    cost: float = Field(..., description="Total cost of the trade in quote currency (amount * price)")
    fee_amount: float = Field(..., description="Fee paid for the trade in quote currency (or base if specified by fee_currency)")
    fee_currency: Optional[str] = Field(default=None, description="Currency in which the fee was paid")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Timestamp of trade execution or recording")
    status: str = Field(default="filled", description="Status of the trade (e.g., open, filled, partially_filled, canceled)")

class ArbitrageTrade(BaseModel):
    """Represents a completed arbitrage cycle, consisting of a buy and a sell trade."""
    id: str = Field(..., description="Unique identifier for the arbitrage trade cycle")
    opportunity_id: Optional[str] = Field(default=None, description="ID of the ArbitrageOpportunity that led to this trade") 
    buy_trade: IndividualTrade = Field(..., description="Details of the buy leg of the arbitrage")
    sell_trade: IndividualTrade = Field(..., description="Details of the sell leg of the arbitrage")
    symbol: str = Field(..., description="Trading pair symbol")
    profit_quote: float = Field(..., description="Net profit in quote currency after all fees")
    profit_percentage: float = Field(..., description="Net profit percentage relative to the initial investment (buy cost)")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Timestamp when the arbitrage trade cycle was completed/recorded")
    is_test_trade: bool = Field(default=False, description="Flag indicating if this was a simulated test trade")
    status: str = Field(default="completed", description="Status of the arbitrage trade (e.g. pending, completed, failed)") 

# --- Bot Configuration & Status Models ---
class TestModeSettings(BaseModel):
    """Settings for running the bot in test/simulation mode."""
    usdt_capital_per_exchange: float = Field(default=1000.0, description="Simulated USDT capital per exchange")
    asset_capital_usd_per_pair: float = Field(default=100.0, description="Simulated USD capital for each base asset (e.g., BTC, ETH) per exchange, per pair")
    buffer_percentage: Optional[float] = Field(default=0.01, ge=0, le=5.0, description="Buffer to account for slippage/fees (e.g., 0.01 for 0.01%)") 
    exchanges: Optional[List[str]] = Field(default_factory=list, description="List of exchanges to use in test mode, if empty use all connected")

class AlertMessage(BaseModel):
    """Model for system alerts and notifications."""
    id: Optional[str] = Field(default=None, description="Unique ID for the alert, can be generated if not provided")
    type: str = Field(..., description="Type of the alert, e.g. system_error, trade_executed")
    severity: Literal["info", "warning", "error", "critical"] = Field(..., description="Severity of the alert")
    message: str = Field(..., description="Detailed alert message")
    entity_name: Optional[str] = Field(default=None, description="Name of the entity (e.g., exchange name, pair symbol)")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Timestamp of the alert")

class FailsafeEntityStatus(BaseModel):
    """Status of a specific failsafe entity (pair or exchange)."""
    reason: str = Field(..., description="Reason for disablement")
    disabled_at: datetime = Field(..., description="Timestamp when disabled")
    cooldown_until: Optional[datetime] = Field(default=None, description="Timestamp until cooldown period ends")
    failure_count: int = Field(default=0, description="Recent failure count for this entity")

# This is the FailsafeStatus model as used in arbitrage.py
class FailsafeStatus(BaseModel):
    """Comprehensive status of all failsafe mechanisms, matching arbitrage.py initialization."""
    disabled_pairs: Dict[str, FailsafeEntityStatus] = Field(default_factory=dict)
    disabled_exchanges: Dict[str, FailsafeEntityStatus] = Field(default_factory=dict)
    global_trading_halt: bool = Field(default=False)
    global_halt_reason: Optional[str] = Field(default=None)
    global_halt_timestamp: Optional[datetime] = Field(default=None)
    historical_high_balance_usdt: float = Field(default=0.0) # Field from arbitrage.py
    pair_failure_counts: Dict[str, int] = Field(default_factory=dict) # Field from arbitrage.py
    exchange_failure_counts: Dict[str, int] = Field(default_factory=dict) # Field from arbitrage.py

class FailsafeStatusData(BaseModel):
    """Data structure for FailsafeStatus when used in other contexts like BotStatusPayload."""
    global_trading_halt: bool = Field(default=False, description="Whether global trading is halted")
    global_halt_reason: Optional[str] = Field(default=None, description="Reason for global halt")
    global_halt_timestamp: Optional[datetime] = Field(default=None, description="Timestamp of global halt")
    disabled_exchanges: Dict[str, FailsafeEntityStatus] = Field(default_factory=dict, description="Status of disabled exchanges")
    disabled_pairs: Dict[str, FailsafeEntityStatus] = Field(default_factory=dict, description="Status of disabled trading pairs")

class TestSimulationStatusPayload(BaseModel):
    """Payload for test simulation status updates via WebSocket."""
    status: Literal["IDLE", "STARTING", "RUNNING", "STOPPING", "STOPPED", "ERROR", "UNKNOWN"] = Field(default="IDLE")
    message: Optional[str] = Field(default=None)
    active_since: Optional[datetime] = Field(default=None)
    total_test_trades: int = Field(default=0)
    total_test_profit: float = Field(default=0.0)

class BotStatusPayload(BaseModel):
    """Comprehensive status of the bot, typically sent via WebSocket or API."""
    is_bot_running: bool = Field(..., description="Overall status of whether the bot's main loop is active (live or test)")
    current_mode: Literal["idle", "live", "test_simulating"] = Field(default="idle", description="Current operational mode of the bot")
    connected_exchanges: List[str] = Field(default_factory=list, description="List of currently connected and verified exchanges")
    websocket_connected: bool = Field(default=False, description="Frontend WebSocket connection status to backend")
    last_status_update_ts: datetime = Field(default_factory=datetime.utcnow, description="Timestamp of this status payload generation")
    active_alerts: List[AlertMessage] = Field(default_factory=list, description="List of current active, unacknowledged alerts")
    failsafe_status: FailsafeStatusData = Field(default_factory=FailsafeStatusData, description="Current status of failsafe mechanisms, uses FailsafeStatusData for broader compatibility")
    live_total_trades: Optional[int] = Field(default=None)
    live_total_profit: Optional[float] = Field(default=None)

class FullStatusUpdatePayload(BaseModel):
    """Structure for the full payload received via WebSocket initial_status or bot_status_update."""
    bot_status: BotStatusPayload
    test_simulation_status: TestSimulationStatusPayload
    recent_trades: List[ArbitrageTrade]
    recent_opportunities: List[ArbitrageOpportunity]
    exchange_balances: List[ExchangeBalance]

# --- API Request/Response Models ---
class StartBotRequest(BaseModel):
    """Request model for starting the bot."""
    mode: Literal["live", "test"] = Field(..., description="Mode to start the bot in")
    test_settings: Optional[TestModeSettings] = Field(default=None, description="Settings required if mode is 'test'")

class ActionResponse(BaseModel):
    """Generic response for actions like start/stop."""
    success: bool = Field(..., description="Whether the action was successful")
    message: str = Field(..., description="Message detailing the result of the action")
    data: Optional[Dict] = Field(default=None, description="Optional additional data")

class ReactivateRequest(BaseModel):
    type: Literal["pair", "exchange", "global"]
    entity_name: Optional[str] = None 

class OrderStatus(str, PyEnum):
    OPEN = "open"
    CLOSED = "closed"
    CANCELED = "canceled"
    EXPIRED = "expired"
    REJECTED = "rejected"
    PARTIALLY_FILLED = "partially_filled"

class OrderType(str, PyEnum):
    MARKET = "market"
    LIMIT = "limit"

class OrderSide(str, PyEnum):
    BUY = "buy"
    SELL = "sell"

class AlertType(str, PyEnum):
    CONNECTION_ERROR = "connection_error"
    API_ERROR = "api_error"
    TRADE_EXECUTION_ERROR = "trade_execution_error"
    PARTIAL_FILL_WARNING = "partial_fill_warning"
    FAILSAFE_TRIGGERED = "failsafe_triggered"
    BALANCE_LOW = "balance_low"
    CONFIG_ERROR = "config_error"
    INFO = "info"
    WEBSOCKET_STATUS = "websocket_status"
    CRITICAL_ERROR = "critical_error"
    SYSTEM_WARNING = "system_warning"
    DATA_FETCH_ERROR = "data_fetch_error"
    TRADING_ERROR = "trading_error"
    TRADE_EXECUTED = "trade_executed"
    SYSTEM_ERROR = "system_error" 

class ExchangeBalanceUpdate(BaseModel):
    type: Literal["exchange_balance_update"] = "exchange_balance_update"
    exchange_balances: List[ExchangeBalance] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class BotStatusUpdate(BaseModel):
    type: Literal["bot_status_update"] = "bot_status_update"
    is_bot_running: bool
    current_mode: Literal["idle", "live", "test_simulating"]
    connected_exchanges: List[str] = Field(default_factory=list)
    websocket_connected: bool = False
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class FailsafeStatusUpdate(BaseModel):
    type: Literal["failsafe_status_update"] = "failsafe_status_update"
    global_trading_halt: bool
    global_halt_reason: Optional[str] = None
    global_halt_timestamp: Optional[datetime] = None
    disabled_exchanges: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    disabled_pairs: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class ExchangeConnectionStatus(BaseModel):
    type: Literal["exchange_connection_status"] = "exchange_connection_status"
    exchange: str
    connected: bool
    error: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)

