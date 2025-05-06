import ccxt
import asyncio
import time
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
            if exchange_id not in settings.EXCHANGE_API_KEYS:
                settings.EXCHANGE_API_KEYS[exchange_id] = {}
            
            settings.EXCHANGE_API_KEYS[exchange_id]['api_key'] = api_key
            settings.EXCHANGE_API_KEYS[exchange_id]['api_secret'] = api_secret
            
            if additional_params:
                settings.EXCHANGE_API_KEYS[exchange_id].update(additional_params)
            
            exchange_class = getattr(ccxt, exchange_id)
            exchange = exchange_class({
                'apiKey': api_key,
                'secret': api_secret,
                **(additional_params or {})
            })
            
            await self._test_connection(exchange)
            
            self.exchanges[exchange_id] = exchange
            
            await self.fetch_taker_fee(exchange_id)
            
            return True
        except Exception as e:
            print(f"Error connecting to {exchange_id}: {str(e)}")
            return False
    
    async def _test_connection(self, exchange) -> bool:
        """Test connection to exchange."""
        if exchange.has['fetchBalance']:
            await exchange.fetch_balance()
            return True
        return False
    
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
        
        for ex_id in exchanges_to_fetch:
            if ex_id in self.exchanges:
                try:
                    exchange = self.exchanges[ex_id]
                    balance_data = await exchange.fetch_balance()
                    
                    balances = {}
                    for asset in ['BTC', 'ETH', 'SOL', 'USDT']:
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
                except Exception as e:
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
