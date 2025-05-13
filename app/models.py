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
    # spread_percentage: float = Field(..., description="Gross spread percentage before fees and slippage")
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
    opportunity_id: str = Field(..., description="ID of the ArbitrageOpportunity that led to this trade")
    buy_trade: IndividualTrade = Field(..., description="Details of the buy leg of the arbitrage")
    sell_trade: IndividualTrade = Field(..., description="Details of the sell leg of the arbitrage")
    symbol: str = Field(..., description="Trading pair symbol")
    profit_quote: float = Field(..., description="Net profit in quote currency after all fees")
    profit_percentage: float = Field(..., description="Net profit percentage relative to the initial investment (buy cost)")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Timestamp when the arbitrage trade cycle was completed/recorded")
    is_test_trade: bool = Field(default=False, description="Flag indicating if this was a simulated test trade")

# --- Bot Configuration & Status Models ---
class TestModeSettings(BaseModel):
    """Settings for running the bot in test/simulation mode."""
    # enabled: bool = Field(default=False, description="Whether test mode is active") # Implicitly handled by bot state
    usdt_cap: float = Field(default=1000.0, description="Simulated USDT capital per exchange")
    asset_cap: float = Field(default=10.0, description="Simulated capital for each base asset (e.g., BTC, ETH) per exchange, per pair")
    buffer_percentage: float = Field(default=0.0001, ge=0, le=0.05, description="Buffer to account for slippage/fees (e.g., 0.0001 for 0.01%)")
    exchanges: List[str] = Field(default_factory=list, description="List of exchanges to use in test mode")
    # Removed capital_per_pair as asset_cap is now per pair per exchange

class AlertMessage(BaseModel):
    """Model for system alerts and notifications."""
    id: str = Field(..., description="Unique ID for the alert")
    type: Literal[
        "connection_error", "api_error", "trade_execution_error", "partial_fill_warning", 
        "failsafe_triggered", "balance_low", "config_error", "info", "websocket_status"
    ] = Field(..., description="Type of the alert")
    severity: Literal["info", "warning", "error", "critical"] = Field(..., description="Severity of the alert")
    message: str = Field(..., description="Detailed alert message")
    entity_type: Optional[Literal["exchange", "pair", "global", "system"]] = Field(default=None, description="Type of entity related to the alert")
    entity_name: Optional[str] = Field(default=None, description="Name of the entity (e.g., exchange name, pair symbol)")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Timestamp of the alert")
    can_acknowledge: bool = Field(default=False, description="Whether this alert can be acknowledged by the user")
    is_acknowledged: bool = Field(default=False, description="Whether this alert has been acknowledged")

class FailsafeEntityStatus(BaseModel):
    """Status of a specific failsafe entity (pair or exchange)."""
    reason: str = Field(..., description="Reason for disablement")
    disabled_at: datetime = Field(..., description="Timestamp when disabled")
    cooldown_until: Optional[datetime] = Field(default=None, description="Timestamp until cooldown period ends")
    failure_count: int = Field(default=0, description="Recent failure count for this entity")

class FailsafeStatusData(BaseModel):
    """Comprehensive status of all failsafe mechanisms."""
    global_trading_halt: bool = Field(default=False, description="Whether global trading is halted")
    global_halt_reason: Optional[str] = Field(default=None, description="Reason for global halt")
    global_halt_timestamp: Optional[datetime] = Field(default=None, description="Timestamp of global halt")
    disabled_exchanges: Dict[str, FailsafeEntityStatus] = Field(default_factory=dict, description="Status of disabled exchanges")
    disabled_pairs: Dict[str, FailsafeEntityStatus] = Field(default_factory=dict, description="Status of disabled trading pairs")
    # historical_high_balance_usdt: float = Field(default=0.0, description="Historical high total USDT equivalent balance") # Potentially complex to maintain accurately

class TestSimulationStatusPayload(BaseModel):
    """Payload for test simulation status updates via WebSocket."""
    status: Literal["IDLE", "STARTING", "RUNNING", "STOPPING", "STOPPED", "ERROR"] = Field(default="IDLE")
    message: Optional[str] = Field(default=None)
    active_since: Optional[datetime] = Field(default=None)
    total_test_trades: int = Field(default=0)
    total_test_profit: float = Field(default=0.0)
    # Potentially add current settings if they can change mid-simulation (unlikely for now)

class BotStatusPayload(BaseModel):
    """Comprehensive status of the bot, typically sent via WebSocket or API."""
    is_bot_running: bool = Field(..., description="Overall status of whether the bot's main loop is active (live or test)")
    current_mode: Literal["idle", "live", "test_simulating"] = Field(default="idle", description="Current operational mode of the bot")
    # test_simulation_status: TestSimulationStatusPayload = Field(default_factory=TestSimulationStatusPayload, description="Specific status of test simulation if active") # Replaced by current_mode and specific test data
    connected_exchanges: List[str] = Field(default_factory=list, description="List of currently connected and verified exchanges")
    websocket_connected: bool = Field(default=False, description="Frontend WebSocket connection status to backend")
    last_status_update_ts: datetime = Field(default_factory=datetime.utcnow, description="Timestamp of this status payload generation")
    active_alerts: List[AlertMessage] = Field(default_factory=list, description="List of current active, unacknowledged alerts")
    failsafe_status: FailsafeStatusData = Field(default_factory=FailsafeStatusData, description="Current status of failsafe mechanisms")
    # Optional: High-level performance summary for live mode if running
    live_total_trades: Optional[int] = Field(default=None)
    live_total_profit: Optional[float] = Field(default=None)

# --- API Request/Response Models (Examples, can be more specific per endpoint) ---
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
    entity_name: Optional[str] = None # Required if type is pair or exchange

class OrderStatus(str, PyEnum):
    """Order status enum."""
    open = "open"
    closed = "closed"
    canceled = "canceled"
    expired = "expired"
    rejected = "rejected"
    partially_filled = "partially_filled"

class OrderType(str, PyEnum):
    """Order type enum."""
    market = "market"
    limit = "limit"

class OrderSide(str, PyEnum):
    """Order side enum."""
    buy = "buy"
    sell = "sell"

# --- Alert & Status Models ---
class AlertType(str, PyEnum):
    """Alert type enum."""
    connection_error = "connection_error"
    api_error = "api_error"
    trade_execution_error = "trade_execution_error"
    partial_fill_warning = "partial_fill_warning"
    failsafe_triggered = "failsafe_triggered"
    balance_low = "balance_low"
    config_error = "config_error"
    info = "info"
    websocket_status = "websocket_status"

class FailsafeStatus(BaseModel):
    """Comprehensive status of all failsafe mechanisms."""
    global_trading_halt: bool = Field(default=False, description="Whether global trading is halted")
    global_halt_reason: Optional[str] = Field(default=None, description="Reason for global halt")
    global_halt_timestamp: Optional[datetime] = Field(default=None, description="Timestamp of global halt")
    disabled_exchanges: Dict[str, FailsafeEntityStatus] = Field(default_factory=dict, description="Status of disabled exchanges")
    disabled_pairs: Dict[str, FailsafeEntityStatus] = Field(default_factory=dict, description="Status of disabled trading pairs")

class ExchangeBalanceUpdate(BaseModel):
    """Model for exchange balance updates sent via WebSocket."""
    type: Literal["exchange_balance_update"] = "exchange_balance_update"
    exchange_balances: List[ExchangeBalance] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class BotStatusUpdate(BaseModel):
    """Model for bot status updates sent via WebSocket."""
    type: Literal["bot_status_update"] = "bot_status_update"
    is_bot_running: bool
    current_mode: Literal["idle", "live", "test_simulating"]
    connected_exchanges: List[str] = Field(default_factory=list)
    websocket_connected: bool = False
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class FailsafeStatusUpdate(BaseModel):
    """Model for failsafe status updates sent via WebSocket."""
    type: Literal["failsafe_status_update"] = "failsafe_status_update"
    global_trading_halt: bool
    global_halt_reason: Optional[str] = None
    global_halt_timestamp: Optional[datetime] = None
    disabled_exchanges: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    disabled_pairs: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class ExchangeConnectionStatus(BaseModel):
    """Model for exchange connection status updates sent via WebSocket."""
    type: Literal["exchange_connection_status"] = "exchange_connection_status"
    exchange: str
    connected: bool
    error: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
