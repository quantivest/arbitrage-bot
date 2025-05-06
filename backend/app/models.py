from pydantic import BaseModel
from typing import Dict, List, Optional, Union
from datetime import datetime

class ExchangeCredentials(BaseModel):
    """Model for exchange API credentials."""
    exchange: str
    api_key: str
    api_secret: str
    additional_params: Optional[Dict[str, str]] = None

class Balance(BaseModel):
    """Model for asset balance."""
    free: float
    used: float
    total: float

class ExchangeBalance(BaseModel):
    """Model for exchange balances."""
    exchange: str
    balances: Dict[str, Balance]

class OrderBookEntry(BaseModel):
    """Model for order book entry."""
    price: float
    amount: float

class OrderBook(BaseModel):
    """Model for order book."""
    exchange: str
    symbol: str
    bids: List[OrderBookEntry]
    asks: List[OrderBookEntry]
    timestamp: datetime

class ArbitrageOpportunity(BaseModel):
    """Model for arbitrage opportunity."""
    buy_exchange: str
    sell_exchange: str
    symbol: str
    buy_price: float
    sell_price: float
    spread_percentage: float
    potential_profit_percentage: float
    max_trade_amount: float
    timestamp: datetime

class Trade(BaseModel):
    """Model for executed trade."""
    id: str
    exchange: str
    symbol: str
    side: str  # "buy" or "sell"
    amount: float
    price: float
    cost: float
    fee: float
    timestamp: datetime
    is_test: bool = False

class ArbitrageTrade(BaseModel):
    """Model for arbitrage trade pair."""
    id: str
    buy_trade: Trade
    sell_trade: Trade
    profit: float
    profit_percentage: float
    timestamp: datetime
    is_test: bool = False

class TestModeSettings(BaseModel):
    """Model for test mode settings."""
    enabled: bool = False
    capital_per_pair: Dict[str, float] = {}  # e.g. {"BTC/USDT": 10.0}
    buffer_percentage: float = 0.0001  # 0.01%
    exchanges: List[str] = []

class BotStatus(BaseModel):
    """Model for bot status."""
    running: bool = False
    test_mode: bool = False
    connected_exchanges: List[str] = []
    last_update: Optional[datetime] = None
    error: Optional[str] = None
