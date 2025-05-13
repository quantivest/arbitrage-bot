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
    TEST_MODE_DEFAULT_CAPITAL_USDT: float = 1000.0  # Default $1000 USDT per exchange in test mode
    TEST_MODE_DEFAULT_CAPITAL_ASSET: float = 10.0     # Default 10 units of each base asset per exchange in test mode

    # Bot operational parameters
    SCAN_INTERVAL_SECONDS: float = 1.0  # Interval for scanning arbitrage opportunities
    ORDER_BOOK_STALENESS_THRESHOLD_SECONDS: int = 5 # Max age of order book to be considered valid
    ORDER_BOOK_DEPTH_FOR_LIQUIDITY: int = 5 # Number of order book levels to sum for liquidity check
    DEFAULT_SLIPPAGE_PERCENTAGE: float = 0.0005 # Default 0.05% slippage if not calculable
    MIN_PROFIT_PERCENTAGE_THRESHOLD: float = 0.0002 # Minimum 0.02% profit after all costs to execute trade
    MIN_TRADE_AMOUNT_BASE: float = 0.00001 # Minimum trade amount in base currency (e.g., 0.00001 BTC)
    # MAX_TRADE_AMOUNT_QUOTE is handled by arbitrage_bot.max_trade_amount = 750.0 (USDT)

    # Failsafe parameters
    FAILSAFE_PAIR_MAX_FAILURES: int = 5 # Max failures for a specific pair on an exchange before disabling it
    FAILSAFE_EXCHANGE_MAX_FAILURES: int = 10 # Max total failures for an exchange before disabling it
    FAILSAFE_COOLDOWN_MINUTES_PAIR: int = 5 # Cooldown period for disabled pairs
    FAILSAFE_COOLDOWN_MINUTES_EXCHANGE: int = 10 # Cooldown period for disabled exchanges

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()

# Ensure TRADING_PAIRS is correctly aliased after settings object creation
settings.TRADING_PAIRS = settings.USER_DEFINED_PAIRS

