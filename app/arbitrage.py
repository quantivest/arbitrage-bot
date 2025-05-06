import asyncio
import time
import uuid
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from .models import ArbitrageOpportunity, ArbitrageTrade, Trade, OrderBook
from .exchanges import exchange_manager
from .config import settings

class ArbitrageBot:
    """Spot-to-spot arbitrage bot."""
    
    def __init__(self):
        self.running = False
        self.test_mode = False
        self.opportunities = []
        self.trades = []
        self.test_balances = {}  # For test mode
        self.buffer_percentage = settings.BUFFER_PERCENTAGE
    
    def start(self, test_mode: bool = False, test_settings: Dict = None):
        """Start the arbitrage bot."""
        self.running = True
        self.test_mode = test_mode
        
        if test_mode and test_settings:
            self._initialize_test_balances(test_settings)
            
            if 'buffer_percentage' in test_settings:
                self.buffer_percentage = test_settings['buffer_percentage']
        
        asyncio.create_task(self._main_loop())
    
    def stop(self):
        """Stop the arbitrage bot."""
        self.running = False
    
    def _initialize_test_balances(self, test_settings: Dict):
        """Initialize test balances for all exchanges."""
        self.test_balances = {}
        
        exchanges = test_settings.get('exchanges', [])
        if not exchanges:
            exchanges = list(exchange_manager.exchanges.keys())
        
        capital_per_pair = test_settings.get('capital_per_pair', {})
        
        default_capital = settings.TEST_MODE_DEFAULT_CAPITAL
        
        for exchange in exchanges:
            self.test_balances[exchange] = {
                'BTC': {'free': 0.0, 'used': 0.0, 'total': 0.0},
                'ETH': {'free': 0.0, 'used': 0.0, 'total': 0.0},
                'SOL': {'free': 0.0, 'used': 0.0, 'total': 0.0},
                'USDT': {'free': 0.0, 'used': 0.0, 'total': 0.0}
            }
        
        for pair in settings.TRADING_PAIRS:
            base, quote = pair.split('/')
            
            capital = capital_per_pair.get(pair, default_capital)
            
            approx_prices = {
                'BTC/USDT': 50000,
                'ETH/USDT': 3000,
                'SOL/USDT': 100
            }
            
            base_amount = capital / approx_prices.get(pair, 1)
            
            for i, exchange in enumerate(exchanges):
                if i % 2 == 0:  # Even exchanges get base asset
                    self.test_balances[exchange][base]['free'] += base_amount
                    self.test_balances[exchange][base]['total'] += base_amount
                else:  # Odd exchanges get quote asset
                    self.test_balances[exchange][quote]['free'] += capital
                    self.test_balances[exchange][quote]['total'] += capital
    
    async def _main_loop(self):
        """Main arbitrage detection and execution loop."""
        while self.running:
            try:
                exchanges = list(exchange_manager.exchanges.keys())
                
                if len(exchanges) >= 2:
                    for pair in settings.TRADING_PAIRS:
                        await self._scan_arbitrage_opportunities(pair, exchanges)
                
                await asyncio.sleep(1)
            except Exception as e:
                print(f"Error in arbitrage main loop: {str(e)}")
                await asyncio.sleep(5)  # Sleep longer on error
    
    async def _scan_arbitrage_opportunities(self, pair: str, exchanges: List[str]):
        """Scan for arbitrage opportunities for a specific pair across exchanges."""
        order_books = {}
        
        for exchange in exchanges:
            order_book = await exchange_manager.fetch_order_book(exchange, pair)
            if order_book:
                order_books[exchange] = order_book
        
        if len(order_books) < 2:
            return
        
        for buy_exchange in exchanges:
            for sell_exchange in exchanges:
                if buy_exchange == sell_exchange:
                    continue
                
                if buy_exchange not in order_books or sell_exchange not in order_books:
                    continue
                
                buy_price = order_books[buy_exchange].asks[0].price if order_books[buy_exchange].asks else None
                sell_price = order_books[sell_exchange].bids[0].price if order_books[sell_exchange].bids else None
                
                if not buy_price or not sell_price:
                    continue
                
                spread = (sell_price - buy_price) / buy_price
                
                buy_fee = exchange_manager.get_taker_fee(buy_exchange, pair)
                sell_fee = exchange_manager.get_taker_fee(sell_exchange, pair)
                
                buy_slippage = self._calculate_slippage(order_books[buy_exchange].asks, 'buy')
                sell_slippage = self._calculate_slippage(order_books[sell_exchange].bids, 'sell')
                
                total_cost = buy_fee + sell_fee + buy_slippage + sell_slippage + self.buffer_percentage
                
                if spread > total_cost:
                    max_amount = self._calculate_max_trade_amount(
                        buy_exchange, sell_exchange, pair, 
                        order_books[buy_exchange], order_books[sell_exchange]
                    )
                    
                    if max_amount > 0:
                        opportunity = ArbitrageOpportunity(
                            buy_exchange=buy_exchange,
                            sell_exchange=sell_exchange,
                            symbol=pair,
                            buy_price=buy_price,
                            sell_price=sell_price,
                            spread_percentage=spread * 100,
                            potential_profit_percentage=(spread - total_cost) * 100,
                            max_trade_amount=max_amount,
                            timestamp=datetime.now()
                        )
                        
                        self.opportunities.append(opportunity)
                        
                        await self._execute_arbitrage(opportunity)
    
    def _calculate_slippage(self, orders: List, side: str) -> float:
        """Calculate estimated slippage based on order book depth."""
        if not orders or len(orders) < 2:
            return 0.01  # Default 1% if not enough orders
        
        if side == 'buy':
            slippage = (orders[1].price - orders[0].price) / orders[0].price
        else:
            slippage = (orders[0].price - orders[1].price) / orders[0].price
        
        return max(0.001, slippage)  # Minimum 0.1% slippage
    
    def _calculate_max_trade_amount(self, buy_exchange: str, sell_exchange: str, pair: str, 
                                   buy_order_book: OrderBook, sell_order_book: OrderBook) -> float:
        """Calculate maximum trade amount based on liquidity and balances."""
        base, quote = pair.split('/')
        
        buy_liquidity = sum(order.amount for order in buy_order_book.asks[:5])
        sell_liquidity = sum(order.amount for order in sell_order_book.bids[:5])
        
        if self.test_mode:
            buy_quote_balance = self.test_balances.get(buy_exchange, {}).get(quote, {}).get('free', 0)
            sell_base_balance = self.test_balances.get(sell_exchange, {}).get(base, {}).get('free', 0)
        else:
            buy_exchange_balance = exchange_manager.exchange_balances.get(buy_exchange, None)
            sell_exchange_balance = exchange_manager.exchange_balances.get(sell_exchange, None)
            
            buy_quote_balance = buy_exchange_balance.balances[quote].free if buy_exchange_balance and quote in buy_exchange_balance.balances else 0
            sell_base_balance = sell_exchange_balance.balances[base].free if sell_exchange_balance and base in sell_exchange_balance.balances else 0
        
        buy_price = buy_order_book.asks[0].price if buy_order_book.asks else 0
        max_buy_amount = buy_quote_balance / buy_price if buy_price > 0 else 0
        
        return min(max_buy_amount, sell_base_balance, buy_liquidity, sell_liquidity)
    
    async def _execute_arbitrage(self, opportunity: ArbitrageOpportunity):
        """Execute an arbitrage trade if conditions are met."""
        if not self.running:
            return
        
        try:
            buy_order = await exchange_manager.execute_trade(
                opportunity.buy_exchange,
                opportunity.symbol,
                'buy',
                opportunity.max_trade_amount,
                opportunity.buy_price,
                self.test_mode
            )
            
            if not buy_order:
                return
            
            sell_order = await exchange_manager.execute_trade(
                opportunity.sell_exchange,
                opportunity.symbol,
                'sell',
                opportunity.max_trade_amount,
                opportunity.sell_price,
                self.test_mode
            )
            
            if not sell_order:
                return
            
            buy_trade = Trade(
                id=buy_order['id'],
                exchange=opportunity.buy_exchange,
                symbol=opportunity.symbol,
                side='buy',
                amount=float(buy_order['amount']),
                price=float(buy_order['price']),
                cost=float(buy_order['cost']),
                fee=float(buy_order['fee']['cost']) if 'fee' in buy_order and buy_order['fee'] else 0.0,
                timestamp=datetime.fromtimestamp(buy_order['timestamp'] / 1000) if 'timestamp' in buy_order else datetime.now(),
                is_test=self.test_mode
            )
            
            sell_trade = Trade(
                id=sell_order['id'],
                exchange=opportunity.sell_exchange,
                symbol=opportunity.symbol,
                side='sell',
                amount=float(sell_order['amount']),
                price=float(sell_order['price']),
                cost=float(sell_order['cost']),
                fee=float(sell_order['fee']['cost']) if 'fee' in sell_order and sell_order['fee'] else 0.0,
                timestamp=datetime.fromtimestamp(sell_order['timestamp'] / 1000) if 'timestamp' in sell_order else datetime.now(),
                is_test=self.test_mode
            )
            
            profit = sell_trade.cost - buy_trade.cost - sell_trade.fee - buy_trade.fee
            profit_percentage = profit / buy_trade.cost * 100
            
            arbitrage_trade = ArbitrageTrade(
                id=str(uuid.uuid4()),
                buy_trade=buy_trade,
                sell_trade=sell_trade,
                profit=profit,
                profit_percentage=profit_percentage,
                timestamp=datetime.now(),
                is_test=self.test_mode
            )
            
            self.trades.append(arbitrage_trade)
            
            if self.test_mode:
                self._update_test_balances(buy_trade, sell_trade)
            
            return arbitrage_trade
        except Exception as e:
            print(f"Error executing arbitrage: {str(e)}")
            return None
    
    def _update_test_balances(self, buy_trade: Trade, sell_trade: Trade):
        """Update test balances after a trade."""
        base, quote = buy_trade.symbol.split('/')
        
        if buy_trade.exchange in self.test_balances:
            self.test_balances[buy_trade.exchange][quote]['free'] -= buy_trade.cost + buy_trade.fee
            self.test_balances[buy_trade.exchange][quote]['total'] -= buy_trade.cost + buy_trade.fee
            
            self.test_balances[buy_trade.exchange][base]['free'] += buy_trade.amount
            self.test_balances[buy_trade.exchange][base]['total'] += buy_trade.amount
        
        if sell_trade.exchange in self.test_balances:
            self.test_balances[sell_trade.exchange][base]['free'] -= sell_trade.amount
            self.test_balances[sell_trade.exchange][base]['total'] -= sell_trade.amount
            
            self.test_balances[sell_trade.exchange][quote]['free'] += sell_trade.cost - sell_trade.fee
            self.test_balances[sell_trade.exchange][quote]['total'] += sell_trade.cost - sell_trade.fee
    
    def get_recent_opportunities(self, limit: int = 50) -> List[ArbitrageOpportunity]:
        """Get recent arbitrage opportunities."""
        return sorted(self.opportunities, key=lambda x: x.timestamp, reverse=True)[:limit]
    
    def get_recent_trades(self, limit: int = 50, is_test: bool = None) -> List[ArbitrageTrade]:
        """Get recent arbitrage trades."""
        if is_test is not None:
            filtered_trades = [t for t in self.trades if t.is_test == is_test]
        else:
            filtered_trades = self.trades
        
        return sorted(filtered_trades, key=lambda x: x.timestamp, reverse=True)[:limit]
    
    def get_test_balances(self) -> Dict:
        """Get current test balances."""
        return self.test_balances

arbitrage_bot = ArbitrageBot()
