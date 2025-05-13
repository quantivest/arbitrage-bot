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
    
    async def connect_exchange(self, exchange_id: str, api_key: str, api_secret: str, additional_params: Optional[Dict] = None) -> bool:
        """Connect to an exchange with API credentials."""
        try:
            api_key = api_key.strip() if api_key else ""
            api_secret = api_secret.strip() if api_secret else ""
            
            key_was_trimmed = False
            original_key = api_key
            
            if exchange_id == "gemini":
                if api_key.startswith("account-"):
                    api_key = api_key[8:]  # Remove "account-" prefix
                    key_was_trimmed = True
                    print(f"Gemini API key auto-trimmed from 'account-XXXX' format to 'XXXX' format")
                print(f"Setting up Gemini connection with API key: {'*' * (len(api_key) - 4) + api_key[-4:] if len(api_key) >= 4 else '****'}")
            
            if exchange_id not in settings.EXCHANGE_API_KEYS:
                settings.EXCHANGE_API_KEYS[exchange_id] = {}
            
            settings.EXCHANGE_API_KEYS[exchange_id]['api_key'] = api_key
            settings.EXCHANGE_API_KEYS[exchange_id]['api_secret'] = api_secret
            
            if additional_params:
                settings.EXCHANGE_API_KEYS[exchange_id].update(additional_params)
            
            exchange_class = getattr(ccxt, exchange_id)
            exchange_params = {
                'apiKey': api_key,
                'secret': api_secret,
            }
            
            if exchange_id == "gemini":
                exchange_params['urls'] = {
                    'api': 'https://api.gemini.com',
                    'public': 'https://api.gemini.com',
                    'private': 'https://api.gemini.com'
                }
                exchange_params['options'] = {
                    'recvWindow': 60000,  # Longer window for requests
                    'adjustForTimeDifference': True,  # Adjust for time difference
                    'createMarketBuyOrderRequiresPrice': False,
                    'enableRateLimit': True,  # Enable rate limiting
                    'rateLimit': 500  # 500ms between requests (2 requests per second)
                }
                if not hasattr(self, 'gemini_nonces'):
                    self.gemini_nonces = {}
                
                api_key_for_nonce = api_key.strip() if api_key else ""
                nonce_key = f"gemini_{api_key_for_nonce[-8:]}" if len(api_key_for_nonce) >= 8 else f"gemini_{api_key_for_nonce}"
                
                def get_gemini_nonce():
                    if nonce_key not in self.gemini_nonces:
                        self.gemini_nonces[nonce_key] = int(time.time() * 1000)
                        print(f"Initialized Gemini nonce for key {nonce_key}: {self.gemini_nonces[nonce_key]}")
                    else:
                        self.gemini_nonces[nonce_key] += 1
                    
                    nonce_value = str(self.gemini_nonces[nonce_key])
                    print(f"Generated Gemini nonce: {nonce_value}")
                    return nonce_value
                
                exchange_params['nonce'] = get_gemini_nonce
            
            if additional_params:
                exchange_params.update(additional_params)
                
            exchange = exchange_class(exchange_params)
            
            if exchange_id == "gemini":
                try:
                    print(f"Testing Gemini connection with custom authentication check...")
                    await self._test_gemini_connection(exchange, api_key, api_secret)
                except Exception as gemini_error:
                    print(f"Gemini custom authentication test failed: {str(gemini_error)}")
                    if key_was_trimmed:
                        print(f"Retrying Gemini connection with original untrimmed key...")
                        exchange_params['apiKey'] = original_key
                        exchange = exchange_class(exchange_params)
                        try:
                            await self._test_gemini_connection(exchange, original_key, api_secret)
                            settings.EXCHANGE_API_KEYS[exchange_id]['api_key'] = original_key
                            print(f"Gemini connection successful with untrimmed key")
                        except Exception as retry_error:
                            print(f"Gemini connection failed with untrimmed key: {str(retry_error)}")
                            raise retry_error
            else:
                await self._test_connection(exchange)
            
            self.exchanges[exchange_id] = exchange
            
            await self.fetch_taker_fee(exchange_id)
            
            return True
        except Exception as e:
            if exchange_id == "gemini":
                masked_key = "****" + api_key[-4:] if len(api_key) >= 4 else "****"
                print(f"Error connecting to Gemini: API key used: {masked_key}, Key was trimmed: {key_was_trimmed}")
                print(f"Full Gemini error: {str(e)}")
                
                if "Out-of-sequence nonce" in str(e):
                    print("Gemini nonce error detected. This usually happens when the nonce is not strictly increasing.")
                elif "InvalidSignature" in str(e):
                    print("Gemini signature error detected. This could be due to incorrect API secret or payload formatting.")
                elif "InvalidApiKey" in str(e):
                    print("Gemini API key error detected. The API key may be invalid or not have the required permissions.")
                elif "MissingApikeyHeader" in str(e) or "MissingPayloadHeader" in str(e) or "MissingSignatureHeader" in str(e):
                    print("Gemini authentication header error. Required headers are missing.")
            else:
                print(f"Error connecting to {exchange_id}: {str(e)}")
            return False
    
    async def _test_connection(self, exchange) -> bool:
        """Test connection to exchange."""
        if exchange.has['fetchBalance']:
            await exchange.fetch_balance()
            return True
        return False
        
    async def _test_gemini_connection(self, exchange, api_key, api_secret) -> bool:
        """Test Gemini connection with custom authentication."""
        try:
            if exchange.has['fetchBalance']:
                balance_data = await exchange.fetch_balance()
                print(f"Gemini balance fetch successful: {len(balance_data.keys())} currencies found")
                return True
                
            endpoint = '/v1/balances'
            nonce = str(int(time.time() * 1000))
            
            payload = {
                'request': endpoint,
                'nonce': nonce
            }
            
            encoded_payload = base64.b64encode(json.dumps(payload).encode())
            signature = hmac.new(api_secret.encode(), encoded_payload, hashlib.sha384).hexdigest()
            
            headers = {
                'Content-Type': 'text/plain',
                'X-GEMINI-APIKEY': api_key,
                'X-GEMINI-PAYLOAD': encoded_payload.decode(),
                'X-GEMINI-SIGNATURE': signature,
                'Cache-Control': 'no-cache'
            }
            
            url = 'https://api.gemini.com' + endpoint
            print(f"Testing Gemini connection with custom request to {url}")
            
            response = await exchange.fetch(url, 'POST', headers, body=encoded_payload)
            print(f"Gemini custom test response: {response[:100]}..." if len(str(response)) > 100 else response)
            
            return True
        except Exception as e:
            print(f"Gemini custom test failed: {str(e)}")
            raise e
    
    async def disconnect_exchange(self, exchange_id: str) -> bool:
        """Disconnect from an exchange."""
        if exchange_id in self.exchanges:
            del self.exchanges[exchange_id]
            if exchange_id in settings.EXCHANGE_API_KEYS:
                del settings.EXCHANGE_API_KEYS[exchange_id]
            return True
        return False
    
    async def fetch_balances(self, exchange_id: str = None) -> List[ExchangeBalance]:
        """Fetch balances from one or all connected exchanges."""
        results = []
        
        exchanges_to_fetch = [exchange_id] if exchange_id else self.exchanges.keys()
        print(f"Fetching balances for exchanges: {exchanges_to_fetch}")
        
        assets = set(['USDT'])  # Always include USDT
        for pair in settings.TRADING_PAIRS:
            base, quote = pair.split('/')
            assets.add(base)
            assets.add(quote)
        
        for ex_id in exchanges_to_fetch:
            if ex_id in self.exchanges:
                try:
                    print(f"Fetching balance for {ex_id}...")
                    exchange = self.exchanges[ex_id]
                    
                    if ex_id == "gemini":
                        print(f"Using special handling for Gemini balance fetch...")
                        try:
                            balance_data = await exchange.fetch_balance()
                            print(f"Gemini standard balance fetch successful: {len(balance_data.keys())} currencies found")
                        except Exception as gemini_error:
                            print(f"Gemini standard balance fetch failed: {str(gemini_error)}")
                            
                            try:
                                print("Attempting custom Gemini balance fetch...")
                                
                                api_key = settings.EXCHANGE_API_KEYS[ex_id]['api_key']
                                api_secret = settings.EXCHANGE_API_KEYS[ex_id]['api_secret']
                                
                                if not api_key.startswith("account-"):
                                    print("Adding 'account-' prefix for Gemini API key in custom balance fetch")
                                    api_key = f"account-{api_key}"
                                
                                endpoint = '/v1/balances'
                                nonce = str(int(time.time() * 1000))
                                
                                payload = {
                                    'request': endpoint,
                                    'nonce': nonce
                                }
                                
                                encoded_payload = base64.b64encode(json.dumps(payload).encode())
                                signature = hmac.new(api_secret.encode(), encoded_payload, hashlib.sha384).hexdigest()
                                
                                headers = {
                                    'Content-Type': 'text/plain',
                                    'X-GEMINI-APIKEY': api_key,
                                    'X-GEMINI-PAYLOAD': encoded_payload.decode(),
                                    'X-GEMINI-SIGNATURE': signature,
                                    'Cache-Control': 'no-cache'
                                }
                                
                                url = 'https://api.gemini.com' + endpoint
                                print(f"Sending custom Gemini balance request to {url}")
                                
                                response = await exchange.fetch(url, 'POST', headers, body=encoded_payload)
                                print(f"Gemini custom balance response: {response[:100]}..." if len(str(response)) > 100 else response)
                                
                                balance_data = {'info': response}
                                for item in response:
                                    currency = item['currency']
                                    balance_data[currency] = {
                                        'free': float(item['available']),
                                        'used': float(item['amount']) - float(item['available']),
                                        'total': float(item['amount'])
                                    }
                                
                                print(f"Gemini custom balance fetch successful: {len(balance_data.keys())-1} currencies found")
                            except Exception as custom_error:
                                print(f"Gemini custom balance fetch also failed: {str(custom_error)}")
                                raise custom_error
                    else:
                        balance_data = await exchange.fetch_balance()
                    
                    balances = {}
                    for asset in assets:
                        if asset in balance_data:
                            balances[asset] = Balance(
                                free=float(balance_data[asset]['free']),
                                used=float(balance_data[asset]['used']),
                                total=float(balance_data[asset]['total'])
                            )
                        else:
                            balances[asset] = Balance(free=0.0, used=0.0, total=0.0)
                    
                    exchange_balance = ExchangeBalance(exchange=ex_id, balances=balances)
                    self.exchange_balances[ex_id] = exchange_balance
                    results.append(exchange_balance)
                    print(f"Successfully fetched balance for {ex_id}")
                except Exception as e:
                    if ex_id == "gemini":
                        print(f"Error fetching balance from Gemini: {str(e)}")
                        if "Out-of-sequence nonce" in str(e):
                            print("Gemini nonce error in balance fetch. This usually happens when the nonce is not strictly increasing.")
                        elif "InvalidSignature" in str(e):
                            print("Gemini signature error in balance fetch. This could be due to incorrect API secret or payload formatting.")
                        elif "InvalidApiKey" in str(e):
                            print("Gemini API key error in balance fetch. The API key may be invalid or not have the required permissions.")
                        elif "MissingApikeyHeader" in str(e) or "MissingPayloadHeader" in str(e) or "MissingSignatureHeader" in str(e):
                            print("Gemini authentication header error in balance fetch. Required headers are missing.")
                    else:
                        print(f"Error fetching balance from {ex_id}: {str(e)}")
        
        return results
    
    async def fetch_order_book(self, exchange_id: str, symbol: str, limit: int = 20) -> Optional[OrderBook]:
        """Fetch order book from an exchange."""
        if exchange_id in self.exchanges:
            try:
                exchange = self.exchanges[exchange_id]
                order_book_data = await exchange.fetch_order_book(symbol, limit)
                
                bids = [OrderBookEntry(price=price, amount=amount) for price, amount in order_book_data['bids']]
                asks = [OrderBookEntry(price=price, amount=amount) for price, amount in order_book_data['asks']]
                
                order_book = OrderBook(
                    exchange=exchange_id,
                    symbol=symbol,
                    bids=bids,
                    asks=asks,
                    timestamp=datetime.fromtimestamp(order_book_data['timestamp'] / 1000)
                )
                
                key = f"{exchange_id}_{symbol}"
                self.order_books[key] = order_book
                return order_book
            except Exception as e:
                print(f"Error fetching order book from {exchange_id} for {symbol}: {str(e)}")
        
        return None
    
    async def fetch_taker_fee(self, exchange_id: str, symbol: str = None) -> float:
        """Fetch taker fee from an exchange."""
        if exchange_id in self.exchanges:
            try:
                exchange = self.exchanges[exchange_id]
                
                if symbol and exchange.has['fetchMarkets']:
                    markets = await exchange.fetch_markets()
                    for market in markets:
                        if market['symbol'] == symbol and 'taker' in market:
                            self.taker_fees[f"{exchange_id}_{symbol}"] = market['taker']
                            return market['taker']
                
                if hasattr(exchange, 'fees') and 'trading' in exchange.fees and 'taker' in exchange.fees['trading']:
                    fee = exchange.fees['trading']['taker']
                    self.taker_fees[exchange_id] = fee
                    return fee
                
                default_fee = 0.001  # 0.1%
                self.taker_fees[exchange_id] = default_fee
                return default_fee
            except Exception as e:
                print(f"Error fetching taker fee from {exchange_id}: {str(e)}")
                
                default_fee = 0.001  # 0.1%
                self.taker_fees[exchange_id] = default_fee
                return default_fee
        
        return 0.001  # Default 0.1%
    
    def get_taker_fee(self, exchange_id: str, symbol: str = None) -> float:
        """Get cached taker fee or fetch if not available."""
        key = f"{exchange_id}_{symbol}" if symbol else exchange_id
        
        if key in self.taker_fees:
            return self.taker_fees[key]
        
        return 0.001  # 0.1%
    
    async def execute_trade(self, exchange_id: str, symbol: str, side: str, amount: float, price: float = None, is_test: bool = False) -> Optional[Dict]:
        """Execute a trade on an exchange."""
        if not is_test and exchange_id in self.exchanges:
            try:
                exchange = self.exchanges[exchange_id]
                
                if side.lower() == 'buy':
                    order = await exchange.create_limit_buy_order(symbol, amount, price) if price else await exchange.create_market_buy_order(symbol, amount)
                else:
                    order = await exchange.create_limit_sell_order(symbol, amount, price) if price else await exchange.create_market_sell_order(symbol, amount)
                
                return order
            except Exception as e:
                print(f"Error executing trade on {exchange_id} for {symbol}: {str(e)}")
        
        if is_test:
            timestamp = int(time.time() * 1000)
            return {
                'id': f"test_{timestamp}",
                'symbol': symbol,
                'side': side,
                'amount': amount,
                'price': price or 0.0,
                'cost': amount * (price or 0.0),
                'fee': {
                    'cost': amount * (price or 0.0) * self.get_taker_fee(exchange_id, symbol),
                    'currency': symbol.split('/')[1]
                },
                'timestamp': timestamp,
                'datetime': datetime.fromtimestamp(timestamp / 1000).isoformat(),
                'status': 'closed',
                'info': {'test': True}
            }
        
        return None

exchange_manager = ExchangeManager()
