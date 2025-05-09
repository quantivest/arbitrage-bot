import asyncio
import time
import uuid
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from .models import ArbitrageOpportunity, ArbitrageTrade, Trade, OrderBook, AlertType, FailsafeStatus
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
        self.failsafe_status = FailsafeStatus(
            disabled_pairs={},
            disabled_exchanges={},
            global_halt=False,
            global_halt_timestamp=None,
            historical_high_balance={},
            pair_failure_counts={},
            exchange_failure_counts={}
        )
        self.alerts = []
        self.trades_blocked = 0
        self.failsafes_triggered = 0
        self.max_trade_amount = 750.0  # Hard cap of $750 per trade leg
    
    def start(self, test_mode: bool = False, test_settings: Dict = None):
        """Start the arbitrage bot."""
        print(f"Starting arbitrage bot in {'test' if test_mode else 'live'} mode")
        
        if self.running:
            print("Bot was already running, resetting state")
            self.stop()
        
        self.running = True
        self.test_mode = test_mode
        
        if test_mode and test_settings:
            print(f"Initializing test balances with settings: {test_settings}")
            self._initialize_test_balances(test_settings)
            
            if 'buffer_percentage' in test_settings:
                self.buffer_percentage = test_settings['buffer_percentage']
                print(f"Set buffer percentage to {self.buffer_percentage}")
        
        loop = asyncio.get_event_loop()
        loop.create_task(self._main_loop())
        
        print(f"Bot started successfully in {'test' if test_mode else 'live'} mode with {len(settings.TRADING_PAIRS)} trading pairs")
    
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
                'USDT': {'free': 0.0, 'used': 0.0, 'total': 0.0}
            }
            
            for pair in settings.TRADING_PAIRS:
                base, _ = pair.split('/')
                if base not in self.test_balances[exchange]:
                    self.test_balances[exchange][base] = {'free': 0.0, 'used': 0.0, 'total': 0.0}
        
        approx_prices = {
            'BTC/USDT': 50000,
            'ETH/USDT': 3000,
            'SOL/USDT': 100,
            'AVAX/USDT': 30,
            'ADA/USDT': 0.5,
            'LINK/USDT': 15,
            'MATIC/USDT': 1,
            'DOGE/USDT': 0.1,
            'ATOM/USDT': 10,
            'NEAR/USDT': 5
        }
        
        for pair in settings.TRADING_PAIRS:
            base, quote = pair.split('/')
            
            capital = capital_per_pair.get(list(capital_per_pair.keys())[0], default_capital) if capital_per_pair else default_capital
            
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
        if pair in self.failsafe_status.disabled_pairs:
            disabled_time = datetime.fromisoformat(self.failsafe_status.disabled_pairs[pair])
            if datetime.now() - disabled_time > timedelta(minutes=5):
                del self.failsafe_status.disabled_pairs[pair]
                self.alerts.append(AlertType(
                    type="pair_disabled",
                    message=f"Pair {pair} automatically reactivated after 5-minute timeout",
                    timestamp=datetime.now(),
                    entity=pair,
                    can_reactivate=False
                ))
            else:
                return
        
        order_books = {}
        
        for exchange in exchanges:
            if exchange in self.failsafe_status.disabled_exchanges:
                disabled_time = datetime.fromisoformat(self.failsafe_status.disabled_exchanges[exchange])
                if datetime.now() - disabled_time > timedelta(minutes=5):
                    del self.failsafe_status.disabled_exchanges[exchange]
                    self.alerts.append(AlertType(
                        type="exchange_disabled",
                        message=f"Exchange {exchange} automatically reactivated after 5-minute timeout",
                        timestamp=datetime.now(),
                        entity=exchange,
                        can_reactivate=False
                    ))
                else:
                    continue
            
            order_book = await exchange_manager.fetch_order_book(exchange, pair)
            if order_book:
                book_time = datetime.fromisoformat(order_book.timestamp)
                if datetime.now() - book_time > timedelta(seconds=2):
                    continue
                
                order_books[exchange] = order_book
        
        if len(order_books) < 2:
            return
        
        if self.failsafe_status.global_halt:
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
        
        if opportunity.symbol in self.failsafe_status.disabled_pairs:
            self.trades_blocked += 1
            return
        
        if (opportunity.buy_exchange in self.failsafe_status.disabled_exchanges or 
            opportunity.sell_exchange in self.failsafe_status.disabled_exchanges):
            self.trades_blocked += 1
            return
        
        if self.failsafe_status.global_halt:
            self.trades_blocked += 1
            return
        
        trade_amount = opportunity.max_trade_amount
        if not self.test_mode:
            trade_amount = min(trade_amount, self.max_trade_amount / opportunity.buy_price)
        
        buy_fee = exchange_manager.get_taker_fee(opportunity.buy_exchange, opportunity.symbol)
        sell_fee = exchange_manager.get_taker_fee(opportunity.sell_exchange, opportunity.symbol)
        
        buy_order_book = await exchange_manager.fetch_order_book(opportunity.buy_exchange, opportunity.symbol)
        sell_order_book = await exchange_manager.fetch_order_book(opportunity.sell_exchange, opportunity.symbol)
        
        if not buy_order_book or not sell_order_book:
            return
        
        buy_book_time = datetime.fromisoformat(buy_order_book.timestamp)
        sell_book_time = datetime.fromisoformat(sell_order_book.timestamp)
        if (datetime.now() - buy_book_time > timedelta(seconds=2) or 
            datetime.now() - sell_book_time > timedelta(seconds=2)):
            return
        
        current_buy_price = buy_order_book.asks[0].price if buy_order_book.asks else None
        current_sell_price = sell_order_book.bids[0].price if sell_order_book.bids else None
        
        if not current_buy_price or not current_sell_price:
            return
        
        current_spread = (current_sell_price - current_buy_price) / current_buy_price
        buy_slippage = self._calculate_slippage(buy_order_book.asks, 'buy')
        sell_slippage = self._calculate_slippage(sell_order_book.bids, 'sell')
        total_cost = buy_fee + sell_fee + buy_slippage + sell_slippage + self.buffer_percentage
        
        if current_spread <= total_cost:
            self.trades_blocked += 1
            return
        
        try:
            buy_order = await exchange_manager.execute_trade(
                opportunity.buy_exchange,
                opportunity.symbol,
                'buy',
                trade_amount,
                current_buy_price,
                self.test_mode
            )
            
            if not buy_order:
                self._increment_failure_count(opportunity.buy_exchange, opportunity.symbol)
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
            
            sell_order = await exchange_manager.execute_trade(
                opportunity.sell_exchange,
                opportunity.symbol,
                'sell',
                trade_amount,
                current_sell_price,
                self.test_mode
            )
            
            if not sell_order:
                buy_time = datetime.fromisoformat(str(buy_trade.timestamp))
                if datetime.now() - buy_time <= timedelta(seconds=2):
                    latest_sell_book = await exchange_manager.fetch_order_book(opportunity.sell_exchange, opportunity.symbol)
                    if latest_sell_book and latest_sell_book.bids:
                        latest_sell_price = latest_sell_book.bids[0].price
                        latest_spread = (latest_sell_price - buy_trade.price) / buy_trade.price
                        if latest_spread > total_cost:
                            sell_order = await exchange_manager.execute_trade(
                                opportunity.sell_exchange,
                                opportunity.symbol,
                                'sell',
                                trade_amount,
                                latest_sell_price,
                                self.test_mode
                            )
                
                if not sell_order:
                    self._increment_failure_count(opportunity.sell_exchange, opportunity.symbol)
                    
                    self.alerts.append(AlertType(
                        type="partial_fill",
                        message=f"Partial fill: Buy executed on {opportunity.buy_exchange} but sell failed on {opportunity.sell_exchange} for {opportunity.symbol}",
                        timestamp=datetime.now(),
                        entity=opportunity.symbol,
                        can_reactivate=False
                    ))
                    
                    self.failsafes_triggered += 1
                    return
            
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
            
            expected_profit_percentage = (current_spread - total_cost) * 100
            profit_mismatch = abs(profit_percentage - expected_profit_percentage)
            
            if profit_mismatch > 0.5:
                self.failsafe_status.disabled_pairs[opportunity.symbol] = datetime.now().isoformat()
                self.alerts.append(AlertType(
                    type="pair_disabled",
                    message=f"Profit mismatch for {opportunity.symbol}: Expected {expected_profit_percentage:.2f}%, got {profit_percentage:.2f}%. Pair disabled for 5 minutes.",
                    timestamp=datetime.now(),
                    entity=opportunity.symbol,
                    can_reactivate=True
                ))
                self.failsafes_triggered += 1
            
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
            
            # Update test balances if in test mode
            if self.test_mode:
                self._update_test_balances(buy_trade, sell_trade)
            else:
                self._update_historical_high_balance()
            
            if opportunity.symbol in self.failsafe_status.pair_failure_counts:
                self.failsafe_status.pair_failure_counts[opportunity.symbol] = 0
            if opportunity.buy_exchange in self.failsafe_status.exchange_failure_counts:
                self.failsafe_status.exchange_failure_counts[opportunity.buy_exchange] = 0
            if opportunity.sell_exchange in self.failsafe_status.exchange_failure_counts:
                self.failsafe_status.exchange_failure_counts[opportunity.sell_exchange] = 0
            
            return arbitrage_trade
        except Exception as e:
            print(f"Error executing arbitrage: {str(e)}")
            self._increment_failure_count(opportunity.buy_exchange, opportunity.symbol)
            self._increment_failure_count(opportunity.sell_exchange, opportunity.symbol)
            
            self.alerts.append(AlertType(
                type="trade_error",
                message=f"Error executing trade: {str(e)}",
                timestamp=datetime.now(),
                entity=None,
                can_reactivate=False
            ))
            
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
    
    def _increment_failure_count(self, exchange: str, pair: str):
        """Increment failure count for exchange and pair."""
        if pair in self.failsafe_status.pair_failure_counts:
            self.failsafe_status.pair_failure_counts[pair] += 1
        else:
            self.failsafe_status.pair_failure_counts[pair] = 1
        
        if exchange in self.failsafe_status.exchange_failure_counts:
            self.failsafe_status.exchange_failure_counts[exchange] += 1
        else:
            self.failsafe_status.exchange_failure_counts[exchange] = 1
        
        if self.failsafe_status.pair_failure_counts[pair] >= 2:
            if pair not in self.failsafe_status.disabled_pairs:
                self.failsafe_status.disabled_pairs[pair] = datetime.now().isoformat()
                self.alerts.append(AlertType(
                    type="pair_disabled",
                    message=f"Pair {pair} disabled due to multiple failures",
                    timestamp=datetime.now(),
                    entity=pair,
                    can_reactivate=True
                ))
                self.failsafes_triggered += 1
        
        if self.failsafe_status.exchange_failure_counts[exchange] >= 3:
            if exchange not in self.failsafe_status.disabled_exchanges:
                self.failsafe_status.disabled_exchanges[exchange] = datetime.now().isoformat()
                self.alerts.append(AlertType(
                    type="exchange_disabled",
                    message=f"Exchange {exchange} disabled due to multiple failures",
                    timestamp=datetime.now(),
                    entity=exchange,
                    can_reactivate=True
                ))
                self.failsafes_triggered += 1
    
    def _update_historical_high_balance(self):
        """Update historical high balance tracking and check for capital drop."""
        if self.test_mode:
            return
        
        current_balances = {}
        for exchange_id, exchange_balance in exchange_manager.exchange_balances.items():
            for currency, balance in exchange_balance.balances.items():
                if currency not in current_balances:
                    current_balances[currency] = 0
                current_balances[currency] += balance.total
        
        for currency, total in current_balances.items():
            if currency not in self.failsafe_status.historical_high_balance:
                self.failsafe_status.historical_high_balance[currency] = total
            elif total > self.failsafe_status.historical_high_balance[currency]:
                self.failsafe_status.historical_high_balance[currency] = total
        
        for currency, high_balance in self.failsafe_status.historical_high_balance.items():
            if currency in current_balances:
                current_balance = current_balances[currency]
                if high_balance > 0 and current_balance > 0:
                    drop_percentage = (high_balance - current_balance) / high_balance
                    if drop_percentage > 0.02:  # >2% drop
                        if not self.failsafe_status.global_halt:
                            self.failsafe_status.global_halt = True
                            self.failsafe_status.global_halt_timestamp = datetime.now().isoformat()
                            self.alerts.append(AlertType(
                                type="global_halt",
                                message=f"Global halt triggered: {currency} balance dropped by {drop_percentage*100:.2f}% from historical high",
                                timestamp=datetime.now(),
                                entity=None,
                                can_reactivate=True
                            ))
                            self.failsafes_triggered += 1
    
    def reactivate_pair(self, pair: str) -> bool:
        """Reactivate a disabled trading pair."""
        if pair in self.failsafe_status.disabled_pairs:
            del self.failsafe_status.disabled_pairs[pair]
            if pair in self.failsafe_status.pair_failure_counts:
                self.failsafe_status.pair_failure_counts[pair] = 0
            
            self.alerts.append(AlertType(
                type="pair_disabled",
                message=f"Pair {pair} manually reactivated",
                timestamp=datetime.now(),
                entity=pair,
                can_reactivate=False
            ))
            return True
        return False
    
    def reactivate_exchange(self, exchange: str) -> bool:
        """Reactivate a disabled exchange."""
        if exchange in self.failsafe_status.disabled_exchanges:
            del self.failsafe_status.disabled_exchanges[exchange]
            if exchange in self.failsafe_status.exchange_failure_counts:
                self.failsafe_status.exchange_failure_counts[exchange] = 0
            
            self.alerts.append(AlertType(
                type="exchange_disabled",
                message=f"Exchange {exchange} manually reactivated",
                timestamp=datetime.now(),
                entity=exchange,
                can_reactivate=False
            ))
            return True
        return False
    
    def reactivate_global(self) -> bool:
        """Reactivate global trading after halt."""
        if self.failsafe_status.global_halt:
            self.failsafe_status.global_halt = False
            self.failsafe_status.global_halt_timestamp = None
            
            self.alerts.append(AlertType(
                type="global_halt",
                message="Global trading manually reactivated",
                timestamp=datetime.now(),
                entity=None,
                can_reactivate=False
            ))
            return True
        return False
    
    def get_failsafe_status(self) -> FailsafeStatus:
        """Get current failsafe status."""
        return self.failsafe_status
    
    def get_alerts(self, limit: int = 50) -> List[AlertType]:
        """Get recent alerts."""
        return sorted(self.alerts, key=lambda x: x.timestamp, reverse=True)[:limit]
    
    def get_test_balances(self) -> Dict:
        """Get current test balances."""
        return self.test_balances

arbitrage_bot = ArbitrageBot()
