from pydantic_settings import BaseSettings
from typing import Dict, List, Optional
import os
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    """Application settings."""
    # User-specified trading pairs
    USER_DEFINED_PAIRS: List[str] = [
        "BTC/USDT",
        "ETH/USDT",
        "SOL/USDT",
        "ADA/USDT",
        "XRP/USDT",
        "LTC/USDT",
        "DOT/USDT",
        "LINK/USDT",
        "BNB/USDT", # Changed from MATIC to BNB as per user request
        "DOGE/USDT"
    ]
    # TRADING_PAIRS will now alias USER_DEFINED_PAIRS for consistency in the bot
    TRADING_PAIRS: List[str] = USER_DEFINED_PAIRS
    
    SUPPORTED_EXCHANGES: List[str] = [
        "binanceus", "kraken", "gemini", "bitstamp"
    ]
    
    BUFFER_PERCENTAGE: float = 0.0001  # 0.01% default buffer (0.0001 for backend calculations)
    
    EXCHANGE_API_KEYS: Dict[str, Dict[str, str]] = {}
    
    # Test Mode Default Capitals
    TEST_MODE_DEFAULT_CAPITAL_USDT: float = 5000.0  # Increased from 1000.0 to ensure sufficient test capital
    TEST_MODE_DEFAULT_CAPITAL_ASSET: float = 50.0     # Increased from 10.0 to ensure sufficient test assets

    # Bot operational parameters
    SCAN_INTERVAL_SECONDS: float = 1.0  # Interval for scanning arbitrage opportunities
    ORDER_BOOK_STALENESS_THRESHOLD_SECONDS: int = 5 # Max age of order book to be considered valid
    ORDER_BOOK_DEPTH_FOR_LIQUIDITY: int = 5 # Number of order book levels to sum for liquidity check
    
    EXCHANGE_DEFAULT_FEE_RATE: float = 0.001 # Default 0.1% fee rate as fallback when exchange doesn't report fees
    EXCHANGE_FEE_RATES: Dict[str, float] = {
        "binanceus": 0.001,  # 0.1% taker fee
        "kraken": 0.0026,    # 0.26% taker fee
        "gemini": 0.0035,    # 0.35% taker fee
        "bitstamp": 0.005,   # 0.5% taker fee
    }
    
    DEFAULT_SLIPPAGE_PERCENTAGE: float = 0.0005 # Default 0.05% slippage if not calculable
    EXCHANGE_SLIPPAGE_PERCENTAGES: Dict[str, float] = {
        "binanceus": 0.0004, # 0.04% slippage
        "kraken": 0.0005,    # 0.05% slippage
        "gemini": 0.0006,    # 0.06% slippage
        "bitstamp": 0.0007,  # 0.07% slippage
    }
    
    MIN_PROFIT_PERCENTAGE_THRESHOLD: float = 0.0002 # Minimum 0.02% profit after all costs to execute trade
    MIN_TRADE_AMOUNT_BASE: float = 0.00001 # Minimum trade amount in base currency (e.g., 0.00001 BTC)
    MIN_TRADE_AMOUNT_QUOTE: float = 10.0 # Minimum trade amount in quote currency (e.g., 10 USDT)
    MAX_TRADE_AMOUNT_QUOTE: float = 750.0 # Maximum trade amount for a single leg in quote currency (e.g., 750 USDT)

    # Failsafe parameters
    FAILSAFE_PAIR_MAX_FAILURES: int = 5 # Max failures for a specific pair on an exchange before disabling it
    FAILSAFE_EXCHANGE_MAX_FAILURES: int = 10 # Max total failures for an exchange before disabling it
    FAILSAFE_COOLDOWN_MINUTES_PAIR: int = 5 # Cooldown period for disabled pairs
    FAILSAFE_COOLDOWN_MINUTES_EXCHANGE: int = 10 # Cooldown period for disabled exchanges
    FAILSAFE_GLOBAL_HALT_RECOVERY_CHECK_INTERVAL_SECONDS: int = 60 # Check for global halt recovery every minute

    # WebSocket settings
    WEBSOCKET_BROADCAST_INTERVAL_SECONDS: float = 2.0 # Interval for broadcasting status updates via WebSocket
    MAX_ALERTS_WEBSOCKET: int = 10 # Max alerts to send in initial websocket status
    MAX_ALERTS_STORED: int = 50 # Max alerts to store in memory
    MAX_RECENT_ALERTS_TO_STORE: int = 50 # Alias for MAX_ALERTS_STORED for backward compatibility
    MAX_RECENT_TRADES_TO_DISPLAY: int = 50 # Max trades to display in UI
    TEST_MODE_TRADE_INTERVAL_ITERATIONS: int = 10 # How many main loop iterations before a test trade is simulated
    ORDER_BOOK_DEPTH: int = 20 # How many levels of bids/asks to fetch for order books

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()

# Ensure TRADING_PAIRS is correctly aliased after settings object creation
settings.TRADING_PAIRS = settings.USER_DEFINED_PAIRS

