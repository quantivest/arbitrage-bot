from pydantic_settings import BaseSettings
from typing import Dict, List, Optional
import os
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    """Application settings."""
    TRADING_PAIRS: List[str] = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
    
    SUPPORTED_EXCHANGES: List[str] = [
        "binanceus", "coinbase", "kraken", "gemini", 
        "bitstamp", "pionex", "margex"
    ]
    
    BUFFER_PERCENTAGE: float = 0.0001  # 0.01% default buffer
    
    EXCHANGE_API_KEYS: Dict[str, Dict[str, str]] = {}
    
    TEST_MODE_DEFAULT_CAPITAL: float = 10.0  # Default $10 per pair
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
