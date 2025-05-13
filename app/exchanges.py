import ccxt.async_support as ccxt
import asyncio
import time
import base64
import hashlib
import hmac
import json
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from .models import Balance, ExchangeBalance, OrderBook, OrderBookEntry
from .config import settings

class ExchangeManager:
    """Manages connections to cryptocurrency exchanges."""
    
    def __init__(self):
        self.exchanges = {}
        self.exchange_balances = {}
        self.order_books = {}
        self.taker_fees = {}
        self.gemini_nonces = {} # MODIFICATION 1: Initialize here

    # MODIFICATION 2: Define _get_gemini_nonce method
    def _get_gemini_nonce(self, api_key: str) -> str:
        """Generates a strictly increasing nonce for Gemini API calls."""
        current_api_key_for_nonce = api_key.strip()
        # Ensure consistency: if api_key might have "account-", it should be handled before this point
        # or this function should be aware. Assuming api_key here is the one for signing.

        nonce_key_suffix = current_api_key_for_nonce[-8:] if len(current_api_key_for_nonce) >= 8 else current_api_key_for_nonce
        nonce_key = f"gemini_{nonce_key_suffix}"

        if nonce_key not in self.gemini_nonces:
            self.gemini_nonces[nonce_key] = int(time.time() * 1000000) # Using microseconds for higher initial granularity
            print(f"Initialized Gemini nonce for key ending with ...{nonce_key_suffix}: {self.gemini_nonces[nonce_key]}")
        else:
            self.gemini_nonces[nonce_key] += 1
        
        nonce_value = str(self.gemini_nonces[nonce_key])
        # print(f"Generated Gemini nonce for key ...{nonce_key_suffix}: {nonce_value}") # Verbose
        return nonce_value
    
    async def connect_exchange(self, exchange_id: str, api_key: str, api_secret: str, additional_params: Optional[Dict] = None) -> bool:
        """Connect to an exchange with API credentials."""
        try:
            api_key_to_use = api_key.strip() if api_key else ""
            api_secret_to_use = api_secret.strip() if api_secret else ""
            
            key_was_trimmed = False
            original_key_for_retry = api_key_to_use
            effective_api_key_for_gemini_nonce = api_key_to_use # Key for nonce generation

            if exchange_id == "gemini":
                if api_key_to_use.startswith("account-"):
                    api_key_to_use = api_key_to_use[8:]
                    key_was_trimmed = True
                    print(f"Gemini API key auto-trimmed from 'account-XXXX' format to 'XXXX' format for ccxt.")
                effective_api_key_for_gemini_nonce = api_key_to_use # This stripped key is used for nonce
                print(f"Setting up Gemini connection with API key (for ccxt): {'*' * (len(api_key_to_use) - 4) + api_key_to_use[-4:] if len(api_key_to_use) >= 4 else '****'}")
            
            if exchange_id not in settings.EXCHANGE_API_KEYS:
                settings.EXCHANGE_API_KEYS[exchange_id] = {}
            
            settings.EXCHANGE_API_KEYS[exchange_id]['api_key'] = api_key_to_use
            settings.EXCHANGE_API_KEYS[exchange_id]['api_secret'] = api_secret_to_use
            
            if additional_params:
                settings.EXCHANGE_API_KEYS[exchange_id].update(additional_params)
            
            exchange_class = getattr(ccxt, exchange_id)
            exchange_params = {
                'apiKey': api_key_to_use,
                'secret': api_secret_to_use,
            }
            
            if exchange_id == "gemini":
                exchange_params['urls'] = {
                    'api': 'https://api.gemini.com',
                    'public': 'https://api.gemini.com',
                    'private': 'https://api.gemini.com'
                }
                exchange_params['options'] = {
                    'recvWindow': 60000,
                    'adjustForTimeDifference': True,
                    'createMarketBuyOrderRequiresPrice': False,
                    'enableRateLimit': True,
                    'rateLimit': 500
                }
                # MODIFICATION 3: Use the class method for nonce, capturing the correct key
                final_key_for_nonce_lambda = effective_api_key_for_gemini_nonce
                exchange_params['nonce'] = lambda key=final_key_for_nonce_lambda: self._get_gemini_nonce(key)

            if additional_params:
                exchange_params.update(additional_params)
                
            exchange = exchange_class(exchange_params)
            
            if exchange_id == "gemini":
                try:
                    print(f"Testing Gemini connection with ccxt's built-in methods (using key: {'*' * (len(api_key_to_use) - 4) + api_key_to_use[-4:] if len(api_key_to_use) >= 4 else '****'})...")
                    await self._test_gemini_connection(exchange, api_key_to_use, api_secret_to_use)
                except Exception as gemini_error:
                    print(f"Gemini ccxt connection test failed: {str(gemini_error)}")
                    if key_was_trimmed:
                        print(f"Retrying Gemini connection with original untrimmed key ('{original_key_for_retry[:8]}...') for ccxt...")
                        exchange_params_retry = exchange_params.copy()
                        exchange_params_retry['apiKey'] = original_key_for_retry
                        final_key_for_nonce_lambda_retry = original_key_for_retry # Nonce based on untrimmed key
                        exchange_params_retry['nonce'] = lambda key=final_key_for_nonce_lambda_retry: self._get_gemini_nonce(key)
                        
                        exchange = exchange_class(exchange_params_retry)
                        try:
                            await self._test_gemini_connection(exchange, original_key_for_retry, api_secret_to_use)
                            settings.EXCHANGE_API_KEYS[exchange_id]['api_key'] = original_key_for_retry
                            print(f"Gemini connection successful with untrimmed key for ccxt.")
                        except Exception as retry_error:
                            print(f"Gemini connection also failed with untrimmed key for ccxt: {str(retry_error)}")
                            raise retry_error
                    else:
                        raise gemini_error
            else:
                await self._test_connection(exchange)
            
            self.exchanges[exchange_id] = exchange
            await self.fetch_taker_fee(exchange_id)
            return True
        except Exception as e:
            key_that_failed = api_key.strip() if api_key else ""
            if exchange_id == "gemini":
                # Determine which key was active during failure for logging
                if "untrimmed key" in str(e).lower(): key_that_failed = original_key_for_retry
                else: key_that_failed = api_key_to_use
                masked_key = "****" + key_that_failed[-4:] if len(key_that_failed) >= 4 else "****"
                print(f"Error connecting to Gemini: API key attempted: {masked_key}, Key was trimmed in initial attempt: {key_was_trimmed}")
                print(f"Full Gemini error: {str(e)}")
                if "Out-of-sequence nonce" in str(e): print("Gemini nonce error detected.")
                elif "InvalidSignature" in str(e): print("Gemini signature error detected.")
                elif "InvalidApiKey" in str(e): print("Gemini API key error detected.")
                elif "MissingApikeyHeader" in str(e) or "MissingPayloadHeader" in str(e) or "MissingSignatureHeader" in str(e): print("Gemini authentication header error.")
            else:
                print(f"Error connecting to {exchange_id}: {str(e)}")
            return False
    
    async def _test_connection(self, exchange) -> bool:
        """Test connection to exchange."""
        if exchange.has['fetchBalance']:
            await exchange.fetch_balance()
            return True
        return False
        
    async def _test_gemini_connection(self, exchange, api_key_for_custom_req: str, api_secret_for_custom_req: str) -> bool:
        """Test Gemini connection. Prefers ccxt's fetch_balance if available."""
        try:
            if exchange.has['fetchBalance']:
                print(f"Attempting Gemini balance fetch via ccxt exchange.fetch_balance()...")
                balance_data = await exchange.fetch_balance()
                print(f"Gemini ccxt balance fetch successful: {len(balance_data.keys())} currencies found")
                return True
            
            # Fallback to custom request if fetchBalance is not supported by ccxt for this exchange object
            print(f"ccxt's exchange.has['fetchBalance'] is false for Gemini. Proceeding with custom Gemini auth test.")
            endpoint = '/v1/balances'
            # api_key_for_custom_req is the key without 
