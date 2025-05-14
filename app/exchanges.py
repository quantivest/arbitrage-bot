import ccxt.async_support as ccxt
import asyncio
import time
import json
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timezone # Added timezone for UTC awareness
from .models import Balance, ExchangeBalance, OrderBook, OrderBookEntry
from .config import settings
import logging
import base64 # For Kraken error check
import binascii # For Kraken error check

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
        
        current_time_micros = int(time.time() * 1_000_000) # More precise time
        if nonce_identifier not in self.gemini_nonces or self.gemini_nonces[nonce_identifier] < current_time_micros:
            self.gemini_nonces[nonce_identifier] = current_time_micros
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
            current_api_secret_for_ccxt = api_secret.strip()

            exchange_config = {
                "apiKey": current_api_key_for_ccxt,
                "secret": current_api_secret_for_ccxt, 
                "enableRateLimit": True,
            }

            if exchange_id_lower == "gemini":
                # Pass the function itself, CCXT handles calling it.
                exchange_config["nonce"] = lambda: self._get_gemini_nonce(current_api_key_for_ccxt)
                logger.info(f"Gemini exchange: Nonce function configured.")

            if additional_params:
                logger.info(f"Applying additional parameters for {exchange_id}: {additional_params}")
                exchange_config.update(additional_params)
            
            loggable_config = {k: v for k, v in exchange_config.items() if k not in ["secret", "apiKey"]}
            loggable_config["apiKey_present"] = bool(exchange_config.get("apiKey"))
            loggable_config["secret_present"] = bool(exchange_config.get("secret"))
            if "nonce" in loggable_config and callable(loggable_config["nonce"]):
                 loggable_config["nonce"] = "<function>" # Replace function with string for logging
            try:
                logger.debug(f"Exchange config for {exchange_id} (secrets masked): {json.dumps(loggable_config, indent=2)}")
            except TypeError as te_json:
                logger.error(f"Error serializing loggable_config for {exchange_id}: {te_json}. Config: {loggable_config}")
                # Fallback logging if json.dumps fails
                logger.debug(f"Exchange config for {exchange_id} (secrets masked, raw): {loggable_config}")

            logger.info(f"Initializing CCXT exchange class for {exchange_id}...")
            exchange = exchange_class(exchange_config)
            logger.info(f"CCXT exchange class for {exchange_id} initialized.")
            
            logger.info(f"Loading markets for {exchange_id}...")
            await exchange.load_markets()
            logger.info(f"Successfully loaded markets for {exchange_id}. Market count: {len(exchange.markets) if exchange.markets else 'N/A'}.")
            
            # Attempt a lightweight authenticated call to verify API keys properly
            logger.info(f"Attempting to fetch balances to verify API key for {exchange_id}...")
            try:
                # Fetch balance is a good test, but can be heavy. Some exchanges might have a lighter test.
                # For now, use fetch_balance, but only a small part of it.
                await exchange.fetch_balance(params={"limit": 1}) # Some exchanges might support limit here
                logger.info(f"API key for {exchange_id} appears valid after balance fetch attempt.")
            except ccxt.AuthenticationError as e_auth_verify:
                logger.error(f"API key verification failed for {exchange_id} during balance fetch: {e_auth_verify}", exc_info=True)
                await exchange.close() # Close the partially opened exchange
                return False, f"Authentication failed for {exchange_id}. Check API key and secret. Details: {e_auth_verify}"
            except Exception as e_verify: # Catch other errors during this verification step
                logger.warning(f"Could not fully verify API key for {exchange_id} via balance fetch (non-auth error): {e_verify}", exc_info=True)
                # Proceed with connection if load_markets succeeded, but with a warning.
                # The actual balance fetching later will show the error if it persists.

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
            if "Out-of-sequence nonce" in str(e) and exchange_id_lower == "gemini":
                return False, f"Gemini nonce error for {exchange_id}. Please try reconnecting. Details: {e}"
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
                # Always remove from local tracking regardless of close() success
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
        active_exchange_ids = list(self.exchanges.keys()) # Get a snapshot of currently connected exchanges
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
            elif result is None: # fetch_balances_for_exchange returned None, implying it handled its own error logging and update
                if ex_id not in self.exchange_balances or self.exchange_balances[ex_id].error is None:
                    # This case should ideally be covered by fetch_balances_for_exchange setting an error
                    logger.warning(f"fetch_balances_for_exchange for {ex_id} returned None but no error was set in exchange_balances. Setting a generic error.")
                    self.exchange_balances[ex_id] = ExchangeBalance(exchange=ex_id, balances={}, timestamp=datetime.now(timezone.utc), error="Failed to fetch balances, see logs.")
            # If result is an ExchangeBalance object, it was successful and already updated self.exchange_balances

        return {ex_id: self.exchange_balances[ex_id] for ex_id in active_exchange_ids if ex_id in self.exchange_balances}

    async def fetch_balances_for_exchange(self, exchange_id: str) -> Optional[ExchangeBalance]:
        if exchange_id not in self.exchanges:
            logger.warning(f"Cannot fetch balances: Exchange {exchange_id} not connected.")
            # Ensure an error state is recorded if we expect this exchange to be connected
            self.exchange_balances[exchange_id] = ExchangeBalance(exchange=exchange_id, balances={}, timestamp=datetime.now(timezone.utc), error="Not connected")
            return None
        exchange = self.exchanges[exchange_id]
        try:
            logger.debug(f"Fetching balances for {exchange_id}...")
            raw_balances = await exchange.fetch_balance()
            parsed_balances: Dict[str, Balance] = {}
            
            # Check if raw_balances itself is a dict, as expected by ccxt for most exchanges
            if not isinstance(raw_balances, dict):
                logger.error(f"Unexpected balance format from {exchange_id}. Expected dict, got {type(raw_balances)}. Data: {raw_balances}")
                self.exchange_balances[exchange_id] = ExchangeBalance(exchange=exchange_id, balances={}, timestamp=datetime.now(timezone.utc), error=f"Unexpected balance format: {type(raw_balances)}")
                return self.exchange_balances[exchange_id]

            # Iterate over 'free', 'used', 'total' at the top level if they exist (e.g. for aggregated balances)
            # More commonly, balances are per-currency, so we iterate raw_balances.items()
            for currency, amounts in raw_balances.items():
                if currency in ["info", "free", "used", "total"]: # Skip meta keys if they are at this level
                    continue
                
                # Handle cases where 'amounts' might not be a dictionary (e.g. Binance US returning int for zero balance)
                if isinstance(amounts, dict):
                    total_amount = amounts.get("total", 0.0) or 0.0
                    free_amount = amounts.get("free", 0.0) or 0.0
                    used_amount = amounts.get("used", 0.0) or 0.0
                elif isinstance(amounts, (int, float)):
                    # If amounts is a number, assume it's the total and free, with zero used.
                    # This is a guess based on the 'int' object error for Binance US.
                    logger.warning(f"Received numerical balance for {currency} on {exchange_id}: {amounts}. Assuming it's total/free.")
                    total_amount = float(amounts)
                    free_amount = float(amounts)
                    used_amount = 0.0
                else:
                    logger.warning(f"Skipping balance entry for {currency} on {exchange_id} due to unexpected type: {type(amounts)}")
                    continue

                if total_amount > 0 or currency.upper() == "USDT": # Keep USDT even if zero, and any other asset with balance
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
            logger.error(f"Network error fetching balances for {exchange_id}: {type(e).__name__} - {e}")
            self.exchange_balances[exchange_id] = ExchangeBalance(exchange=exchange_id, balances={}, timestamp=datetime.now(timezone.utc), error=f"Network error: {e}")
        except ccxt.AuthenticationError as e:
            logger.error(f"Authentication error fetching balances for {exchange_id}: {type(e).__name__} - {e}")
            self.exchange_balances[exchange_id] = ExchangeBalance(exchange=exchange_id, balances={}, timestamp=datetime.now(timezone.utc), error=f"Authentication error: {e}")
        except ccxt.ExchangeError as e:
            logger.error(f"Exchange error fetching balances for {exchange_id}: {type(e).__name__} - {e}")
            self.exchange_balances[exchange_id] = ExchangeBalance(exchange=exchange_id, balances={}, timestamp=datetime.now(timezone.utc), error=f"Exchange error: {e}")
        except Exception as e:
            logger.error(f"Unexpected error fetching balances for {exchange_id}: {type(e).__name__} - {e}", exc_info=True)
            self.exchange_balances[exchange_id] = ExchangeBalance(exchange=exchange_id, balances={}, timestamp=datetime.now(timezone.utc), error=f"An unexpected error occurred: {e}")
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
            timestamp_ms = ob_data.get("timestamp")
            dt_object = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc) if timestamp_ms else datetime.now(timezone.utc)
            return OrderBook(
                pair=pair,
                exchange=exchange_id,
                timestamp=dt_object,
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
            if not exchange.markets:
                logger.info(f"Markets not loaded for {exchange_id} to fetch taker fee, loading now...")
                await exchange.load_markets(reload=True)
            
            if pair and pair in exchange.markets and exchange.markets[pair].get("taker") is not None:
                fee = exchange.markets[pair]["taker"]
                if exchange_id not in self.taker_fees: self.taker_fees[exchange_id] = {}
                self.taker_fees[exchange_id][pair] = fee
                logger.info(f"Taker fee for {pair} on {exchange_id}: {fee}")
                return fee
            
            if exchange.fees and exchange.fees.get("trading") and exchange.fees["trading"].get("taker") is not None:
                fee = exchange.fees["trading"]["taker"]
                logger.info(f"General trading taker fee for {exchange_id}: {fee} (used as fallback or default)")
                # Store it generally if pair specific not found or pair not provided
                if exchange_id not in self.taker_fees: self.taker_fees[exchange_id] = {}
                if pair: 
                    self.taker_fees[exchange_id][pair] = fee
                else: # Store as a default for the exchange if no pair given
                    self.taker_fees[exchange_id]["_default_"] = fee
                return fee
            
            logger.warning(f"Could not determine taker fee for {exchange_id} (pair: {pair}). Using default from settings: {settings.DEFAULT_TAKER_FEE}")
            return settings.DEFAULT_TAKER_FEE # Fallback to a configured default

        except ccxt.NetworkError as e:
            logger.error(f"Network error fetching taker fee for {exchange_id}, pair {pair}: {type(e).__name__} - {e}")
        except ccxt.AuthenticationError as e: # Unlikely for fees, but good practice
            logger.error(f"Authentication error fetching taker fee for {exchange_id}, pair {pair}: {type(e).__name__} - {e}")
        except ccxt.ExchangeError as e:
            logger.error(f"Exchange error fetching taker fee for {exchange_id}, pair {pair}: {type(e).__name__} - {e}")
        except Exception as e:
            logger.error(f"Unexpected error fetching taker fee for {exchange_id}, pair {pair}: {type(e).__name__} - {e}", exc_info=True)
        
        logger.warning(f"Returning default taker fee {settings.DEFAULT_TAKER_FEE} for {exchange_id} (pair: {pair}) after error.")
        return settings.DEFAULT_TAKER_FEE

    def get_all_connected_exchanges(self) -> List[str]:
        return list(self.exchanges.keys())

