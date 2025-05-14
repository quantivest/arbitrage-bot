import ccxt.async_support as ccxt
import asyncio
import time
import json # Added for pretty printing dicts in logs
from typing import Dict, List, Optional, Tuple, Any
from .models import Balance, ExchangeBalance, OrderBook, OrderBookEntry
from .config import settings
import logging

logger = logging.getLogger(__name__)

class ExchangeManager:
    """Manages connections to cryptocurrency exchanges and fetches market data."""
    
    def __init__(self):
        self.exchanges: Dict[str, ccxt.Exchange] = {}
        self.exchange_balances: Dict[str, ExchangeBalance] = {}
        self.taker_fees: Dict[str, Dict[str, float]] = {}
        self.gemini_nonces: Dict[str, int] = {}
        logger.info("ExchangeManager initialized.")

    def _get_gemini_nonce(self, api_key_for_nonce_logic: str) -> str:
        """Generates a strictly increasing nonce for Gemini API calls, keyed by a portion of the API key."""
        nonce_identifier = api_key_for_nonce_logic[-8:] if len(api_key_for_nonce_logic) >= 8 else api_key_for_nonce_logic
        
        if nonce_identifier not in self.gemini_nonces:
            self.gemini_nonces[nonce_identifier] = int(time.time() * 1000000) 
            logger.info(f"Initialized Gemini nonce for key ending ...{nonce_identifier} to {self.gemini_nonces[nonce_identifier]}")
        else:
            self.gemini_nonces[nonce_identifier] += 1
        return str(self.gemini_nonces[nonce_identifier])
    
    async def connect_exchange(self, exchange_id: str, api_key: str, api_secret: str, additional_params: Optional[Dict] = None) -> Tuple[bool, str]:
        logger.info(f"Attempting to connect to exchange: {exchange_id}")
        if not api_key or not api_secret:
            msg = f"API key or secret is missing for {exchange_id}."
            logger.error(msg)
            return False, msg

        try:
            exchange_id_lower = exchange_id.lower()
            logger.debug(f"Connecting to {exchange_id_lower} (original ID: {exchange_id})")
            if not hasattr(ccxt, exchange_id_lower):
                msg = f"Exchange {exchange_id} is not supported by CCXT."
                logger.error(msg)
                return False, msg

            exchange_class = getattr(ccxt, exchange_id_lower)
            current_api_key_for_ccxt = api_key.strip()

            exchange_config = {
                "apiKey": current_api_key_for_ccxt,
                "secret": api_secret.strip(), # Keep secret for CCXT, but don't log it directly
                "enableRateLimit": True,
            }

            if exchange_id_lower == "gemini":
                exchange_config["nonce"] = lambda: self._get_gemini_nonce(current_api_key_for_ccxt)
                logger.info(f"Gemini exchange: Nonce function configured.")

            if additional_params:
                logger.info(f"Applying additional parameters for {exchange_id}: {additional_params}")
                exchange_config.update(additional_params)
            
            # Log config without sensitive details for debugging
            loggable_config = {k: v for k, v in exchange_config.items() if k != "secret" and k != "apiKey"}
            loggable_config["apiKey_present"] = bool(exchange_config.get("apiKey"))
            loggable_config["secret_present"] = bool(exchange_config.get("secret"))
            logger.debug(f"Exchange config for {exchange_id} (secrets masked): {json.dumps(loggable_config, indent=2)}")
            
            logger.info(f"Initializing CCXT exchange class for {exchange_id}...")
            exchange = exchange_class(exchange_config)
            logger.info(f"CCXT exchange class for {exchange_id} initialized.")
            
            logger.info(f"Loading markets for {exchange_id}...")
            await exchange.load_markets()
            logger.info(f"Successfully loaded markets for {exchange_id}. Market count: {len(exchange.markets) if exchange.markets else 'N/A'}. Connection appears stable.")
            
            self.exchanges[exchange_id] = exchange
            return True, f"Successfully connected to {exchange_id}."

        except ccxt.NetworkError as e:
            logger.error(f"Network error connecting to {exchange_id}: {type(e).__name__} - {e}", exc_info=True)
            return False, f"Network error connecting to {exchange_id}: {e}"
        except ccxt.AuthenticationError as e: # More specific than just ExchangeError for auth issues
            logger.error(f"Authentication error connecting to {exchange_id}: {type(e).__name__} - {e}", exc_info=True)
            return False, f"Authentication failed for {exchange_id}. Check API key and secret. Details: {e}"
        except ccxt.ExchangeError as e:
            logger.error(f"Exchange error connecting to {exchange_id}: {type(e).__name__} - {e}", exc_info=True)
            if "Invalid API Key" in str(e) or "InvalidSignature" in str(e):
                return False, f"Authentication failed for {exchange_id}. Check API key and secret. Details: {e}"
            if "Out-of-sequence nonce" in str(e) and exchange_id_lower == "gemini":
                return False, f"Gemini nonce error for {exchange_id}. Please try reconnecting. Details: {e}"
            return False, f"Exchange error for {exchange_id}: {e}"
        except Exception as e:
            logger.error(f"Unexpected error connecting to {exchange_id}: {type(e).__name__} - {e}", exc_info=True)
            return False, f"An unexpected error occurred while connecting to {exchange_id}. Please check logs for details."
    
    async def disconnect_exchange(self, exchange_id: str) -> Tuple[bool, str]:
        logger.info(f"Attempting to disconnect from exchange: {exchange_id}")
        if exchange_id in self.exchanges:
            try:
                await self.exchanges[exchange_id].close()
                del self.exchanges[exchange_id]
                if exchange_id in self.exchange_balances:
                    del self.exchange_balances[exchange_id]
                if exchange_id in self.taker_fees:
                    del self.taker_fees[exchange_id]
                logger.info(f"Successfully disconnected from {exchange_id}.")
                return True, f"Successfully disconnected from {exchange_id}."
            except Exception as e:
                logger.error(f"Error closing connection to {exchange_id}: {e}", exc_info=True)
                # Still remove from active list even if close() fails
                if exchange_id in self.exchanges: del self.exchanges[exchange_id]
                if exchange_id in self.exchange_balances: del self.exchange_balances[exchange_id]
                if exchange_id in self.taker_fees: del self.taker_fees[exchange_id]
                return False, f"Error closing connection to {exchange_id}, but removed from active list."
        else:
            logger.warning(f"Exchange {exchange_id} not found or not connected.")
            return False, f"Exchange {exchange_id} not found or not connected."

    async def fetch_all_balances(self) -> Dict[str, ExchangeBalance]:
        logger.info("Fetching balances for all connected exchanges.")
        results = await asyncio.gather(
            *[self.fetch_balances_for_exchange(ex_id) for ex_id in self.exchanges.keys()],
            return_exceptions=True
        )
        for i, ex_id in enumerate(list(self.exchanges.keys())): # Use list copy in case exchanges dict changes
            if isinstance(results[i], Exception):
                logger.error(f"Failed to fetch balances for {ex_id}: {results[i]}")
                if ex_id not in self.exchange_balances:
                     self.exchange_balances[ex_id] = ExchangeBalance(exchange=ex_id, balances={}, timestamp=datetime.utcnow(), error=str(results[i]))
                else:
                    self.exchange_balances[ex_id].error = str(results[i])
                    self.exchange_balances[ex_id].timestamp = datetime.utcnow()
            # If result is None (meaning fetch_balances_for_exchange handled its own error reporting and returned None)
            # it might already be updated in self.exchange_balances by that method.
            elif results[i] is None and ex_id not in self.exchange_balances:
                 self.exchange_balances[ex_id] = ExchangeBalance(exchange=ex_id, balances={}, timestamp=datetime.utcnow(), error="Failed to fetch balances, see logs.")

        return self.exchange_balances

    async def fetch_balances_for_exchange(self, exchange_id: str) -> Optional[ExchangeBalance]:
        if exchange_id not in self.exchanges:
            logger.warning(f"Cannot fetch balances: Exchange {exchange_id} not connected.")
            return None
        exchange = self.exchanges[exchange_id]
        try:
            logger.debug(f"Fetching balances for {exchange_id}...")
            raw_balances = await exchange.fetch_balance()
            parsed_balances: Dict[str, Balance] = {}
            for currency, amounts in raw_balances.items():
                if amounts and amounts.get("total") is not None and (amounts["total"] > 0 or currency.upper() == "USDT"):
                    parsed_balances[currency] = Balance(
                        free=amounts.get("free", 0.0) or 0.0,
                        used=amounts.get("used", 0.0) or 0.0,
                        total=amounts.get("total", 0.0) or 0.0
                    )
            
            exchange_balance_obj = ExchangeBalance(
                exchange=exchange_id,
                balances=parsed_balances,
                timestamp=datetime.utcnow(), # Ensure this is imported: from datetime import datetime
                error=None
            )
            self.exchange_balances[exchange_id] = exchange_balance_obj
            logger.info(f"Successfully fetched balances for {exchange_id}. Found {len(parsed_balances)} relevant assets.")
            return exchange_balance_obj
        except ccxt.NetworkError as e:
            logger.error(f"Network error fetching balances for {exchange_id}: {type(e).__name__} - {e}")
            self.exchange_balances[exchange_id] = ExchangeBalance(exchange=exchange_id, balances={}, timestamp=datetime.utcnow(), error=f"Network error: {e}")
        except ccxt.AuthenticationError as e:
            logger.error(f"Authentication error fetching balances for {exchange_id}: {type(e).__name__} - {e}")
            self.exchange_balances[exchange_id] = ExchangeBalance(exchange=exchange_id, balances={}, timestamp=datetime.utcnow(), error=f"Authentication error: {e}")
        except ccxt.ExchangeError as e:
            logger.error(f"Exchange error fetching balances for {exchange_id}: {type(e).__name__} - {e}")
            self.exchange_balances[exchange_id] = ExchangeBalance(exchange=exchange_id, balances={}, timestamp=datetime.utcnow(), error=f"Exchange error: {e}")
        except Exception as e:
            logger.error(f"Unexpected error fetching balances for {exchange_id}: {type(e).__name__} - {e}", exc_info=True)
            self.exchange_balances[exchange_id] = ExchangeBalance(exchange=exchange_id, balances={}, timestamp=datetime.utcnow(), error=f"An unexpected error occurred: {e}")
        return self.exchange_balances.get(exchange_id)

    def get_balance(self, exchange_id: str, currency: str) -> Optional[Balance]:
        ex_balance = self.exchange_balances.get(exchange_id)
        if ex_balance and ex_balance.balances:
            return ex_balance.balances.get(currency)
        return None

    async def fetch_ticker(self, exchange_id: str, pair: str) -> Optional[Dict[str, Any]]:
        if exchange_id not in self.exchanges:
            logger.warning(f"Cannot fetch ticker: Exchange {exchange_id} not connected.")
            return None
        exchange = self.exchanges[exchange_id]
        try:
            if not exchange.has.get("fetchTicker"):
                logger.warning(f"Exchange {exchange_id} does not support fetchTicker for {pair}.")
                return None
            logger.debug(f"Fetching ticker for {pair} on {exchange_id}...")
            ticker = await exchange.fetch_ticker(pair)
            return ticker
        except ccxt.NetworkError as e:
            logger.error(f"Network error fetching ticker for {pair} on {exchange_id}: {type(e).__name__} - {e}")
        except ccxt.AuthenticationError as e:
            logger.error(f"Authentication error fetching ticker for {pair} on {exchange_id}: {type(e).__name__} - {e}")
        except ccxt.ExchangeError as e:
            logger.error(f"Exchange error fetching ticker for {pair} on {exchange_id}: {type(e).__name__} - {e}")
        except Exception as e:
            logger.error(f"Unexpected error fetching ticker for {pair} on {exchange_id}: {type(e).__name__} - {e}", exc_info=True)
        return None

    async def fetch_order_book(self, exchange_id: str, pair: str, limit: int = 25) -> Optional[OrderBook]:
        if exchange_id not in self.exchanges:
            logger.warning(f"Cannot fetch order book: Exchange {exchange_id} not connected.")
            return None
        exchange = self.exchanges[exchange_id]
        try:
            if not exchange.has.get("fetchOrderBook"):
                logger.warning(f"Exchange {exchange_id} does not support fetchOrderBook for {pair}.")
                return None
            logger.debug(f"Fetching order book for {pair} on {exchange_id} (limit {limit})...")
            ob_data = await exchange.fetch_order_book(pair, limit)
            # Ensure datetime is imported: from datetime import datetime
            return OrderBook(
                pair=pair,
                exchange=exchange_id,
                timestamp=datetime.fromtimestamp(ob_data["timestamp"] / 1000) if ob_data.get("timestamp") else datetime.utcnow(),
                bids=[OrderBookEntry(price=entry[0], quantity=entry[1]) for entry in ob_data.get("bids", [])],
                asks=[OrderBookEntry(price=entry[0], quantity=entry[1]) for entry in ob_data.get("asks", [])]
            )
        except ccxt.NetworkError as e:
            logger.error(f"Network error fetching order book for {pair} on {exchange_id}: {type(e).__name__} - {e}")
        except ccxt.AuthenticationError as e:
            logger.error(f"Authentication error fetching order book for {pair} on {exchange_id}: {type(e).__name__} - {e}")
        except ccxt.ExchangeError as e:
            logger.error(f"Exchange error fetching order book for {pair} on {exchange_id}: {type(e).__name__} - {e}")
        except Exception as e:
            logger.error(f"Unexpected error fetching order book for {pair} on {exchange_id}: {type(e).__name__} - {e}", exc_info=True)
        return None

    async def fetch_taker_fee(self, exchange_id: str, pair: Optional[str] = None) -> Optional[float]:
        if exchange_id not in self.exchanges:
            logger.warning(f"Cannot fetch taker fee: Exchange {exchange_id} not connected.")
            return None
        exchange = self.exchanges[exchange_id]
        try:
            # Ensure markets are loaded if not already
            if not exchange.markets:
                logger.info(f"Markets not loaded for {exchange_id}, loading now...")
                await exchange.load_markets(reload=True)
            
            # Try to get specific fee for the pair
            if pair and pair in exchange.markets and exchange.markets[pair].get("taker") is not None:
                fee = exchange.markets[pair]["taker"]
                if exchange_id not in self.taker_fees: self.taker_fees[exchange_id] = {}
                self.taker_fees[exchange_id][pair] = fee
                logger.info(f"Taker fee for {pair} on {exchange_id}: {fee}")
                return fee
            
            # Fallback: Try to find a general taker fee if specific pair fee is not available
            # This part is heuristic and might need adjustment based on CCXT structure for various exchanges
            if exchange.fees and exchange.fees.get("trading") and exchange.fees["trading"].get("taker") is not None:
                general_fee = exchange.fees["trading"]["taker"]
                logger.info(f"Using general trading taker fee for {exchange_id} (pair: {pair}): {general_fee}")
                if exchange_id not in self.taker_fees: self.taker_fees[exchange_id] = {}
                self.taker_fees[exchange_id][pair or "default"] = general_fee
                return general_fee

            # Fallback to settings if no fee found via CCXT
            default_fee = settings.EXCHANGE_DEFAULT_TAKER_FEE.get(exchange_id.lower(), 0.001) # Use lower for settings lookup
            logger.warning(f"Could not find specific or general taker fee for {pair or 'any pair'} on {exchange_id}. Using default from settings: {default_fee}")
            if exchange_id not in self.taker_fees: self.taker_fees[exchange_id] = {}
            self.taker_fees[exchange_id][pair or "default"] = default_fee
            return default_fee
            
        except Exception as e:
            logger.error(f"Error fetching taker fee for {exchange_id} (pair: {pair}): {type(e).__name__} - {e}", exc_info=True)
            default_fee = settings.EXCHANGE_DEFAULT_TAKER_FEE.get(exchange_id.lower(), 0.001)
            logger.warning(f"Using default taker fee {default_fee} for {exchange_id} due to error.")
            if exchange_id not in self.taker_fees: self.taker_fees[exchange_id] = {}
            self.taker_fees[exchange_id][pair or "default"] = default_fee
            return default_fee

exchange_manager = ExchangeManager()
# Ensure datetime is available for models if not already globally available
from datetime import datetime

