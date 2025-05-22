import ccxt.async_support as ccxt
import asyncio
import time
import json
from typing import Dict, List, Optional, Tuple, Any, Union
from datetime import datetime, timezone
from .models import Balance, ExchangeBalance, OrderBook, OrderBookEntry
from .config import settings
import logging
import base64 
import binascii 
import random

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
        
        current_time_ms = int(time.time() * 1000) # Milliseconds as integer
        
        previous_stored_nonce = self.gemini_nonces.get(nonce_identifier)
        
        if nonce_identifier not in self.gemini_nonces:
            self.gemini_nonces[nonce_identifier] = current_time_ms
            logger.info(f"Gemini nonce for '{nonce_identifier}': Initialized to current_time_ms {current_time_ms}.")
        elif self.gemini_nonces[nonce_identifier] < current_time_ms:
            self.gemini_nonces[nonce_identifier] = current_time_ms
            logger.info(f"Gemini nonce for '{nonce_identifier}': Updated to current_time_ms {current_time_ms} (was {previous_stored_nonce}).")
        else:
            self.gemini_nonces[nonce_identifier] += 1
            logger.info(f"Gemini nonce for '{nonce_identifier}': Incremented from {previous_stored_nonce} to {self.gemini_nonces[nonce_identifier]} (current_time_ms was {current_time_ms}).")
        
        new_nonce_val = self.gemini_nonces[nonce_identifier]
        return str(new_nonce_val)
    
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
            current_api_secret_for_ccxt = api_secret.strip()

            exchange_config = {
                "apiKey": current_api_key_for_ccxt,
                "secret": current_api_secret_for_ccxt, 
                "enableRateLimit": True,
            }

            if exchange_id_lower == "gemini":
                exchange_config["nonce"] = lambda: self._get_gemini_nonce(current_api_key_for_ccxt)
                logger.info(f"Gemini exchange: Nonce function configured.")
                exchange_config["options"] = {"adjustForTimeDifference": True}
                logger.info(f"Gemini exchange: adjustForTimeDifference enabled.")

            if additional_params:
                logger.info(f"Applying additional parameters for {exchange_id}: {additional_params}")
                exchange_config.update(additional_params)
            
            loggable_config = {k: v for k, v in exchange_config.items() if k not in ["secret", "apiKey"]}
            loggable_config["apiKey_present"] = bool(exchange_config.get("apiKey"))
            loggable_config["secret_present"] = bool(exchange_config.get("secret"))
            if "nonce" in loggable_config and callable(loggable_config["nonce"]):
                 loggable_config["nonce"] = "<function>"
            try:
                logger.debug(f"Exchange config for {exchange_id} (secrets masked): {json.dumps(loggable_config, indent=2)}")
            except TypeError as te_json:
                logger.error(f"Error serializing loggable_config for {exchange_id}: {te_json}. Config: {loggable_config}")
                logger.debug(f"Exchange config for {exchange_id} (secrets masked, raw): {loggable_config}")

            logger.info(f"Initializing CCXT exchange class for {exchange_id}...")
            exchange = exchange_class(exchange_config)
            logger.info(f"CCXT exchange class for {exchange_id} initialized.")
            
            logger.info(f"Loading markets for {exchange_id}...")
            await exchange.load_markets()
            logger.info(f"Successfully loaded markets for {exchange_id}. Market count: {len(exchange.markets) if exchange.markets else 'N/A'}.")
            
            logger.info(f"Attempting to fetch balances to verify API key for {exchange_id}...")
            try:
                await exchange.fetch_balance() 
                logger.info(f"API key for {exchange_id} appears valid after balance fetch attempt.")
            except ccxt.AuthenticationError as e_auth_verify:
                logger.error(f"API key verification failed for {exchange_id} during balance fetch: {e_auth_verify}", exc_info=True)
                await exchange.close()
                return False, f"Authentication failed for {exchange_id}. Check API key and secret. Details: {e_auth_verify}"
            except Exception as e_verify:
                logger.warning(f"Could not fully verify API key for {exchange_id} via balance fetch (non-auth error): {e_verify}", exc_info=True)

            self.exchanges[exchange_id] = exchange
            return True, f"Successfully connected to {exchange_id}."

        except ccxt.NetworkError as e:
            logger.error(f"Network error connecting to {exchange_id}: {type(e).__name__} - {e}", exc_info=True)
            return False, f"Network error connecting to {exchange_id}: {e}"
        except ccxt.AuthenticationError as e:
            logger.error(f"Authentication error connecting to {exchange_id}: {type(e).__name__} - {e}", exc_info=True)
            specific_msg = str(e)
            if exchange_id_lower == "kraken" and "padding" in specific_msg.lower():
                specific_msg = "Incorrect API secret format (padding error). Please ensure it is correct."
            elif exchange_id_lower == "bitstamp" and "invalid signature" in specific_msg.lower():
                specific_msg = "Invalid API signature. Ensure correct API key, secret, and customer ID/UID (if applicable for main account vs subaccount)."
            return False, f"Authentication failed for {exchange_id}. {specific_msg}"
        except ccxt.ExchangeError as e:
            logger.error(f"Exchange error connecting to {exchange_id}: {type(e).__name__} - {e}", exc_info=True)
            if "Invalid API Key" in str(e) or "InvalidSignature" in str(e):
                return False, f"Authentication failed for {exchange_id}. Check API key and secret. Details: {e}"
            if exchange_id_lower == "gemini" and ("nonce" in str(e).lower() or "InvalidNonce" in str(type(e))):
                return False, f"Gemini nonce error for {exchange_id}. Details: {e}"
            return False, f"Exchange error for {exchange_id}: {e}"
        except Exception as e:
            logger.error(f"Unexpected error connecting to {exchange_id}: {type(e).__name__} - {e}", exc_info=True)
            if isinstance(e, TypeError) and "is not JSON serializable" in str(e):
                 return False, f"Internal configuration error for {exchange_id}. Please report this. Details: {e}"
            return False, f"An unexpected error occurred while connecting to {exchange_id}. Please check logs for details."
    
    async def disconnect_exchange(self, exchange_id: str) -> Tuple[bool, str]:
        logger.info(f"Attempting to disconnect from exchange: {exchange_id}")
        if exchange_id in self.exchanges:
            try:
                await self.exchanges[exchange_id].close()
                logger.info(f"Successfully closed CCXT exchange object for {exchange_id}.")
            except Exception as e_close:
                logger.error(f"Error closing CCXT exchange object for {exchange_id}: {e_close}", exc_info=True)
            finally:
                del self.exchanges[exchange_id]
                if exchange_id in self.exchange_balances:
                    del self.exchange_balances[exchange_id]
                if exchange_id in self.taker_fees:
                    del self.taker_fees[exchange_id]
                logger.info(f"Removed {exchange_id} from active ExchangeManager lists.")
                return True, f"Successfully disconnected from {exchange_id}."
        else:
            logger.warning(f"Exchange {exchange_id} not found or not connected for disconnection.")
            return False, f"Exchange {exchange_id} not found or not connected."

    async def fetch_all_balances(self) -> Dict[str, ExchangeBalance]:
        logger.info("Fetching balances for all connected exchanges.")
        active_exchange_ids = list(self.exchanges.keys())
        results = await asyncio.gather(
            *[self.fetch_balances_for_exchange(ex_id) for ex_id in active_exchange_ids],
            return_exceptions=True
        )
        for i, ex_id in enumerate(active_exchange_ids):
            result = results[i]
            if isinstance(result, Exception):
                logger.error(f"Failed to fetch balances for {ex_id} (exception in gather): {result}", exc_info=result)
                error_message = f"Failed to fetch balances: {type(result).__name__} - {str(result)}"
                if ex_id not in self.exchange_balances or self.exchange_balances[ex_id].error is None:
                     self.exchange_balances[ex_id] = ExchangeBalance(exchange=ex_id, balances={}, timestamp=datetime.now(timezone.utc), error=error_message)
                else:
                    self.exchange_balances[ex_id].error = error_message
                    self.exchange_balances[ex_id].timestamp = datetime.now(timezone.utc)
            elif result is None:
                if ex_id not in self.exchange_balances or self.exchange_balances[ex_id].error is None:
                    logger.warning(f"fetch_balances_for_exchange for {ex_id} returned None but no error was set in exchange_balances. Setting a generic error.")
                    self.exchange_balances[ex_id] = ExchangeBalance(exchange=ex_id, balances={}, timestamp=datetime.now(timezone.utc), error="Failed to fetch balances, see logs.")
            # If result is an ExchangeBalance object, it was successful and already updated self.exchange_balances

        return {ex_id: self.exchange_balances[ex_id] for ex_id in active_exchange_ids if ex_id in self.exchange_balances}

    async def fetch_balances_for_exchange(self, exchange_id: str) -> Optional[ExchangeBalance]:
        if exchange_id not in self.exchanges:
            logger.warning(f"Cannot fetch balances: Exchange {exchange_id} not connected.")
            self.exchange_balances[exchange_id] = ExchangeBalance(exchange=exchange_id, balances={}, timestamp=datetime.now(timezone.utc), error="Not connected")
            return None
        
        exchange = self.exchanges[exchange_id]
        try:
            logger.debug(f"Fetching balances for {exchange_id}...")
            raw_balances = await exchange.fetch_balance()
            parsed_balances: Dict[str, Balance] = {}
            
            if not isinstance(raw_balances, dict):
                logger.error(f"Unexpected balance format from {exchange_id}. Expected dict, got {type(raw_balances)}. Data: {raw_balances}")
                self.exchange_balances[exchange_id] = ExchangeBalance(exchange=exchange_id, balances={}, timestamp=datetime.now(timezone.utc), error=f"Unexpected balance format: {type(raw_balances)}")
                return None

            for currency, amounts in raw_balances.items():
                if currency.lower() in ["info", "free", "used", "total", "timestamp", "datetime"]:
                    continue
                
                if isinstance(amounts, dict):
                    total_amount = amounts.get("total", 0.0) or 0.0
                    free_amount = amounts.get("free", 0.0) or 0.0
                    used_amount = amounts.get("used", 0.0) or 0.0
                elif isinstance(amounts, (int, float)):
                    logger.warning(f"Received numerical balance for {currency} on {exchange_id}: {amounts}. Assuming it is total/free.")
                    total_amount = float(amounts)
                    free_amount = float(amounts)
                    used_amount = 0.0
                else:
                    logger.warning(f"Skipping balance entry for {currency} on {exchange_id} due to unexpected type: {type(amounts)}")
                    continue

                if total_amount > 0 or currency.upper() == "USDT":
                    parsed_balances[currency] = Balance(
                        free=free_amount,
                        used=used_amount,
                        total=total_amount
                    )
            
            exchange_balance_obj = ExchangeBalance(
                exchange=exchange_id,
                balances=parsed_balances,
                timestamp=datetime.now(timezone.utc),
                error=None
            )
            self.exchange_balances[exchange_id] = exchange_balance_obj
            logger.info(f"Successfully fetched balances for {exchange_id}. Found {len(parsed_balances)} relevant assets.")
            return exchange_balance_obj
        except ccxt.NetworkError as e:
            err_str = str(e).lower()
            logger.error(f"Network error fetching balances for {exchange_id}: {type(e).__name__} - {e}", exc_info=True)
            error_msg_to_store = f"Network error: {e}"
            if "gemini" in exchange_id.lower() and ("invalidnonce" in err_str or "nonce" in err_str and ("not increased" in err_str or "out-of-sequence" in err_str)):
                logger.error(f"Gemini specific: NetworkError contained nonce issue for {exchange_id}: {e}")
                error_msg_to_store = f"Gemini nonce error (reported as NetworkError): {e}. Please try reconnecting."
            self.exchange_balances[exchange_id] = ExchangeBalance(exchange=exchange_id, balances={}, timestamp=datetime.now(timezone.utc), error=error_msg_to_store)
            return None
        except ccxt.AuthenticationError as e:
            logger.error(f"Authentication error fetching balances for {exchange_id}: {type(e).__name__} - {e}", exc_info=True)
            self.exchange_balances[exchange_id] = ExchangeBalance(exchange=exchange_id, balances={}, timestamp=datetime.now(timezone.utc), error=f"Authentication error: {e}")
            return None
        except ccxt.ExchangeError as e:
            logger.error(f"Exchange error fetching balances for {exchange_id}: {type(e).__name__} - {e}", exc_info=True)
            self.exchange_balances[exchange_id] = ExchangeBalance(exchange=exchange_id, balances={}, timestamp=datetime.now(timezone.utc), error=f"Exchange error: {e}")
            return None
        except Exception as e_unhandled:
            logger.error(f"Unhandled exception fetching balances for {exchange_id}: {type(e_unhandled).__name__} - {e_unhandled}", exc_info=True)
            self.exchange_balances[exchange_id] = ExchangeBalance(exchange=exchange_id, balances={}, timestamp=datetime.now(timezone.utc), error=f"Unexpected error: {e_unhandled}")
            return None

    async def fetch_order_book(self, exchange_id: str, symbol: str, limit: int = 20, max_retries: int = 3, initial_backoff: float = 0.5) -> Optional[OrderBook]:
        """Fetch order book for a symbol on an exchange with retry and backoff.
        
        Args:
            exchange_id: ID of the exchange to fetch order book from
            symbol: Trading pair symbol (e.g., BTC/USDT)
            limit: Limit the number of price levels returned
            max_retries: Maximum number of retry attempts
            initial_backoff: Initial backoff time in seconds (will increase exponentially)
            
        Returns:
            OrderBook object or None if fetching fails after all retries
        """
        if exchange_id not in self.exchanges:
            logger.warning(f"Cannot fetch order book: Exchange {exchange_id} not connected.")
            return None
        
        exchange = self.exchanges[exchange_id]
        backoff = initial_backoff
        attempts = 0
        
        while attempts <= max_retries:
            try:
                if attempts > 0:
                    logger.debug(f"Retry attempt {attempts}/{max_retries} for fetching order book for {symbol} on {exchange_id} with backoff {backoff:.2f}s")
                
                logger.debug(f"Fetching order book for {symbol} on {exchange_id} with limit {limit}...")
                raw_ob = await exchange.fetch_order_book(symbol, limit=limit)
                
                # Ensure bids and asks are sorted correctly (desc for bids, asc for asks by price)
                # CCXT usually returns them sorted, but good to be defensive.
                # Bids: highest price first. Asks: lowest price first.
                bids = sorted([OrderBookEntry(price=float(b[0]), amount=float(b[1])) for b in raw_ob.get("bids", [])], key=lambda x: x.price, reverse=True)
                asks = sorted([OrderBookEntry(price=float(a[0]), amount=float(a[1])) for a in raw_ob.get("asks", [])], key=lambda x: x.price)
                
                timestamp = None
                if raw_ob.get("timestamp") is not None:
                    try:
                        timestamp = datetime.fromtimestamp(raw_ob["timestamp"] / 1000, timezone.utc)
                    except (ValueError, TypeError, OverflowError) as e:
                        logger.warning(f"Error converting timestamp for {symbol} on {exchange_id}: {e}")
                        timestamp = datetime.now(timezone.utc)
                else:
                    timestamp = datetime.now(timezone.utc)

                order_book = OrderBook(
                    symbol=symbol,
                    bids=bids[:limit],  # Apply limit again after potential re-sorting
                    asks=asks[:limit],
                    timestamp=timestamp,
                    exchange=exchange_id
                )
                logger.debug(f"Successfully fetched order book for {symbol} on {exchange_id}. Top bid: {bids[0].price if bids else 'N/A'}, Top ask: {asks[0].price if asks else 'N/A'}")
                return order_book
                
            except Exception as e:
                attempts += 1
                if attempts <= max_retries:
                    jitter = random.uniform(0, 0.1 * backoff)  # Add up to 10% jitter
                    wait_time = backoff + jitter
                    logger.warning(f"Error fetching order book for {symbol} on {exchange_id} (attempt {attempts}/{max_retries}): {e}. Retrying in {wait_time:.2f}s", exc_info=True)
                    await asyncio.sleep(wait_time)
                    backoff *= 2  # Exponential backoff
                else:
                    logger.error(f"Failed to fetch order book for {symbol} on {exchange_id} after {max_retries} attempts: {e}", exc_info=True)
                    return None

    async def fetch_ticker(self, exchange_id: str, symbol: str) -> Optional[Dict[str, Any]]:
        if exchange_id not in self.exchanges:
            logger.warning(f"Cannot fetch ticker: Exchange {exchange_id} not connected.")
            return None
        exchange = self.exchanges[exchange_id]
        try:
            ticker = await exchange.fetch_ticker(symbol)
            return ticker
        except Exception as e:
            logger.error(f"Error fetching ticker for {symbol} on {exchange_id}: {e}", exc_info=True)
            return None

    async def create_order(self, exchange_id: str, symbol: str, type: str, side: str, amount: float, price: Optional[float] = None, params: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
        if exchange_id not in self.exchanges:
            logger.error(f"Cannot create order: Exchange {exchange_id} not connected.")
            return None
        exchange = self.exchanges[exchange_id]
        if not exchange.has.get("createOrder"):
            logger.error(f"Exchange {exchange_id} does not support createOrder.")
            return None
        try:
            order = await exchange.create_order(symbol, type, side, amount, price, params)
            logger.info(f"Order created on {exchange_id} for {symbol}: {order.get('id')}")
            return order
        except Exception as e:
            logger.error(f"Error creating order on {exchange_id} for {symbol}: {e}", exc_info=True)
            return None

    async def get_all_order_books_for_pairs(self, pairs: List[str], limit: int = 20, max_retries: int = 3) -> Dict[str, Dict[str, OrderBook]]:
        """Fetch order books for all connected exchanges for the given pairs.
        
        Args:
            pairs: List of trading pairs (e.g., ["BTC/USDT", "ETH/USDT"])
            limit: Depth limit for order book
            max_retries: Maximum number of retry attempts for each order book fetch
            
        Returns:
            Dictionary of dictionaries mapping {exchange_id -> {symbol -> OrderBook}}
        """
        logger.info(f"Fetching order books for {len(pairs)} pairs across {len(self.exchanges)} exchanges")
        all_order_books: Dict[str, Dict[str, OrderBook]] = {}
        
        for exchange_id in self.exchanges:
            all_order_books[exchange_id] = {}
            for symbol in pairs:
                try:
                    order_book = await self.fetch_order_book(exchange_id, symbol, limit, max_retries)
                    if order_book:
                        all_order_books[exchange_id][symbol] = order_book
                except Exception as e:
                    logger.error(f"Error fetching order book for {symbol} on {exchange_id}: {e}", exc_info=True)
        
        total_fetched = sum(len(books) for books in all_order_books.values())
        total_possible = len(self.exchanges) * len(pairs)
        logger.info(f"Fetched {total_fetched}/{total_possible} order books successfully")
        
        return all_order_books
        
    def get_exchange_fee_rate(self, exchange_id: str) -> Optional[float]:
        """Get the fee rate for an exchange using the 3-tier priority system:
        1. Real-time fetched taker fee from exchange markets
        2. Exchange-specific configured fee from settings
        3. Global default fee rate
        
        Args:
            exchange_id: The exchange ID to get the fee rate for
            
        Returns:
            The fee rate (e.g., 0.001 for 0.1%) or None if not available
        """
        try:
            if exchange_id in self.exchanges:
                exchange = self.exchanges[exchange_id]
                
                common_markets = ["BTC/USDT", "ETH/USDT", "BTC/USD"]
                for market_symbol in common_markets:
                    if market_symbol in exchange.markets:
                        market = exchange.markets[market_symbol]
                        if 'taker' in market:
                            logger.debug(f"Using real-time taker fee for {exchange_id}: {market['taker']}")
                            return market['taker']
                
                if hasattr(exchange, 'fees') and 'trading' in exchange.fees and 'taker' in exchange.fees['trading']:
                    logger.debug(f"Using exchange default taker fee for {exchange_id}: {exchange.fees['trading']['taker']}")
                    return exchange.fees['trading']['taker']
            
            if hasattr(settings, 'EXCHANGE_FEE_RATES') and exchange_id.lower() in settings.EXCHANGE_FEE_RATES:
                logger.debug(f"Using configured fee rate for {exchange_id}: {settings.EXCHANGE_FEE_RATES[exchange_id.lower()]}")
                return settings.EXCHANGE_FEE_RATES[exchange_id.lower()]
            
            logger.debug(f"Using global default fee rate for {exchange_id}: {settings.EXCHANGE_DEFAULT_FEE_RATE}")
            return settings.EXCHANGE_DEFAULT_FEE_RATE
            
        except Exception as e:
            logger.error(f"Error getting fee rate for {exchange_id}: {e}", exc_info=True)
            return settings.EXCHANGE_DEFAULT_FEE_RATE
            
    def get_exchange_slippage_percentage(self, exchange_id: str) -> float:
        """Get the slippage percentage for an exchange.
        
        Args:
            exchange_id: The exchange ID to get the slippage percentage for
            
        Returns:
            The slippage percentage (e.g., 0.0005 for 0.05%)
        """
        try:
            if hasattr(settings, 'EXCHANGE_SLIPPAGE_PERCENTAGES') and exchange_id.lower() in settings.EXCHANGE_SLIPPAGE_PERCENTAGES:
                return settings.EXCHANGE_SLIPPAGE_PERCENTAGES[exchange_id.lower()]
            
            return settings.DEFAULT_SLIPPAGE_PERCENTAGE
            
        except Exception as e:
            logger.error(f"Error getting slippage percentage for {exchange_id}: {e}", exc_info=True)
            return settings.DEFAULT_SLIPPAGE_PERCENTAGE
            
    def get_connected_exchanges_status(self) -> dict:
        """Get the connection status of all exchanges.
        
        Returns:
            A dictionary mapping exchange IDs to their connection status
        """
        result = {}
        for exchange_id, exchange in self.exchanges.items():
            try:
                result[exchange_id] = {
                    "connected": True,
                    "message": "Connected"
                }
            except Exception as e:
                result[exchange_id] = {
                    "connected": False,
                    "message": f"Error: {str(e)}"
                }
        return result
        
    async def get_all_balances(self) -> dict:
        """Get all balances for all connected exchanges.
        
        Returns:
            A dictionary mapping exchange IDs to their balances
        """
        return await self.fetch_all_balances()
        
    def get_exchange_error(self, exchange_id: str) -> str:
        """Get any error message for an exchange.
        
        Args:
            exchange_id: The exchange ID to get the error for
            
        Returns:
            The error message, or None if there is no error
        """
        return None
        
    def get_supported_exchanges(self) -> List[str]:
        """Get a list of all supported exchanges.
        
        Returns:
            A list of exchange IDs that are supported by the bot
        """
        return ["binanceus", "kraken", "gemini", "bitstamp", "coinbase", "kucoin"]

exchange_manager = ExchangeManager()

