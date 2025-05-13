import asyncio
import time
import uuid
import traceback
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from .models import ArbitrageOpportunity, ArbitrageTrade, Trade, OrderBook, AlertType, FailsafeStatus, OrderBookEntry, ExchangeBalanceUpdate, BotStatusUpdate, TestSimulationStatusPayload, FailsafeStatusUpdate, AlertMessage, ExchangeConnectionStatus, OrderStatus, OrderType, OrderSide # MODIFICATION: Added more model imports
from .exchanges import exchange_manager
from .config import settings

class ArbitrageBot:
    """Spot-to-spot arbitrage bot."""
    
    def __init__(self):
        self.running = False
        self.test_mode = False
        self._main_loop_task: Optional[asyncio.Task] = None
        self.opportunities: List[ArbitrageOpportunity] = []
        self.trades: List[ArbitrageTrade] = [] # Holds both live and test trades; frontend filters by mode
        self.test_balances: Dict[str, Dict[str, Dict[str, float]]] = {} 
        self.buffer_percentage = settings.BUFFER_PERCENTAGE
        self.failsafe_status = FailsafeStatus(
            disabled_pairs={},
            disabled_exchanges={},
            global_trading_halt=False, # MODIFICATION: Renamed for clarity
            global_halt_reason=None,
            global_halt_timestamp=None,
            historical_high_balance_usdt=0.0, # MODIFICATION: Track overall USDT high
            pair_failure_counts={},
            exchange_failure_counts={}
        )
        self.alerts: List[AlertMessage] = [] # MODIFICATION: Use AlertMessage type
        self.max_trade_amount_quote = 750.0  # Hard cap of $750 USDT per trade leg
        self.websocket_queues: List[asyncio.Queue] = [] # MODIFICATION: For WebSocket updates
        self.current_test_settings: Optional[Dict] = None # MODIFICATION: Store current test settings
        self.test_simulation_active_since: Optional[datetime] = None # MODIFICATION
        print(f"ArbitrageBot initialized. Default buffer: {self.buffer_percentage*100:.4f}%, Max trade leg: ${self.max_trade_amount_quote}")

    def add_websocket_queue(self, queue: asyncio.Queue):
        self.websocket_queues.append(queue)

    def remove_websocket_queue(self, queue: asyncio.Queue):
        if queue in self.websocket_queues:
            self.websocket_queues.remove(queue)

    async def _broadcast_to_websockets(self, message: Dict):
        for queue in self.websocket_queues:
            await queue.put(message)

    async def _broadcast_bot_status(self):
        status_update = BotStatusUpdate(
            is_running=self.running,
            is_test_mode=self.test_mode,
            active_exchanges=list(exchange_manager.exchanges.keys()),
            supported_exchanges=settings.SUPPORTED_EXCHANGES,
            trading_pairs=settings.USER_DEFINED_PAIRS
        ).model_dump()
        await self._broadcast_to_websockets({"type": "bot_status", "data": status_update})

    async def _broadcast_test_simulation_status(self, status: str, message: Optional[str] = None, total_trades: Optional[int] = None, total_profit: Optional[float] = None):
        payload = TestSimulationStatusPayload(
            status=status,
            message=message,
            active_since=self.test_simulation_active_since.isoformat() if self.test_simulation_active_since and (status == "RUNNING" or status == "STARTING") else None,
            total_test_trades=total_trades if total_trades is not None else len([t for t in self.trades if t.is_test_trade]),
            total_test_profit=total_profit if total_profit is not None else sum(t.profit_quote for t in self.trades if t.is_test_trade)
        ).model_dump()
        await self._broadcast_to_websockets({"type": "test_simulation_status", "data": payload})

    async def _broadcast_failsafe_status(self):
        status_update = FailsafeStatusUpdate(**self.failsafe_status.model_dump()).model_dump()
        await self._broadcast_to_websockets({"type": "failsafe_status", "data": status_update})

    async def _broadcast_alert(self, alert: AlertMessage):
        self.alerts.insert(0, alert) # Add to beginning for recency
        self.alerts = self.alerts[:50] # Keep last 50 alerts
        await self._broadcast_to_websockets({"type": "alert", "data": alert.model_dump()})

    async def _broadcast_new_trade(self, trade: ArbitrageTrade):
        await self._broadcast_to_websockets({"type": "new_trade", "data": trade.model_dump()})

    async def _broadcast_exchange_balances(self, exchange_id: str, balances: Dict[str, Dict[str, float]], error: Optional[str] = None):
        balance_update = ExchangeBalanceUpdate(
            exchange=exchange_id,
            balances=balances,
            timestamp=datetime.now().isoformat(),
            error=error
        ).model_dump()
        await self._broadcast_to_websockets({"type": "exchange_balance", "data": balance_update})

    async def _broadcast_exchange_connection_status(self, exchange_id: str, connected: bool, message: Optional[str] = None):
        status_update = ExchangeConnectionStatus(
            exchange_name=exchange_id,
            is_connected=connected,
            message=message
        ).model_dump()
        await self._broadcast_to_websockets({"type": "exchange_connection_status", "data": status_update})

    async def start(self, test_mode: bool = False, test_settings: Optional[Dict] = None):
        print(f"Attempting to start arbitrage bot. Current state: running={self.running}, test_mode={self.test_mode}. Requested: test_mode={test_mode}")
        
        if self.running:
            print("Bot is already running. Stopping first to ensure clean start.")
            await self.stop() # MODIFICATION: Make stop awaitable if it has async cleanup

        self.running = True
        self.test_mode = test_mode
        self.opportunities = [] 
        self.trades = [] 
        # self.alerts = [] # Alerts should persist across runs unless explicitly cleared by user action
        
        if self.test_mode and test_settings:
            self.current_test_settings = test_settings
            print(f"Initializing test balances with settings: {test_settings}")
            self._initialize_test_balances(test_settings)
            if isinstance(test_settings.get("buffer_percentage"), (int, float)):
                new_buffer = test_settings["buffer_percentage"]
                if self.buffer_percentage != new_buffer:
                    self.buffer_percentage = new_buffer
                    print(f"Test Mode: Buffer percentage overridden to {self.buffer_percentage*100:.4f}%")
            else:
                self.buffer_percentage = settings.BUFFER_PERCENTAGE # Fallback to default if not provided
                print(f"Test Mode: Using default buffer percentage: {self.buffer_percentage*100:.4f}%")
            self.test_simulation_active_since = datetime.now()
            await self._broadcast_test_simulation_status("STARTING", "Test simulation initializing...")
        else:
            self.current_test_settings = None
            self.buffer_percentage = settings.BUFFER_PERCENTAGE
            self.test_simulation_active_since = None # Not a test simulation
            print(f"Live Mode: Using buffer percentage: {self.buffer_percentage*100:.4f}%")

        loop = asyncio.get_event_loop()
        if self._main_loop_task and not self._main_loop_task.done():
            print("Warning: Previous main loop task was still active. Attempting to cancel.")
            self._main_loop_task.cancel()
            try:
                await self._main_loop_task # Wait for cancellation to complete
            except asyncio.CancelledError:
                print("Previous main loop task successfully cancelled.")
        
        self._main_loop_task = loop.create_task(self._main_loop())
        await self._broadcast_bot_status()
        if self.test_mode:
            await self._broadcast_test_simulation_status("RUNNING", "Test simulation active.")
        print(f"Bot main loop task created. Bot started successfully in {"test" if self.test_mode else "live"} mode with {len(settings.TRADING_PAIRS)} trading pairs: {settings.TRADING_PAIRS}")
    
    async def stop(self):
        print(f"Attempting to stop arbitrage bot. Current state: running={self.running}, test_mode={self.test_mode}")
        is_test_before_stop = self.test_mode
        self.running = False 
        if self._main_loop_task and not self._main_loop_task.done():
            print("Cancelling main loop task...")
            self._main_loop_task.cancel()
            try:
                await self._main_loop_task
                print("Main loop task successfully awaited after cancellation.")
            except asyncio.CancelledError:
                print("Main loop task successfully cancelled (caught CancelledError).")
            except Exception as e:
                print(f"Error awaiting main loop task cancellation: {e}")
        self._main_loop_task = None
        
        # Reset test mode specific states
        if is_test_before_stop:
            await self._broadcast_test_simulation_status("STOPPED", "Test simulation stopped by user.")
            self.test_simulation_active_since = None
            # self.current_test_settings = None # Keep settings for potential restart with same config

        await self._broadcast_bot_status() # Broadcast final stopped status
        print("Arbitrage bot stopped. Running flag set to False, main loop task processed.")
    
    def _initialize_test_balances(self, test_settings: Dict):
        self.test_balances = {}
        exchanges_to_init = test_settings.get("exchanges", list(exchange_manager.exchanges.keys()))
        usdt_capital_per_exchange = test_settings.get("usdt_cap", settings.TEST_MODE_DEFAULT_CAPITAL_USDT)
        base_asset_capital_per_exchange = test_settings.get("asset_cap", settings.TEST_MODE_DEFAULT_CAPITAL_ASSET)

        print(f"Initializing test balances for exchanges: {exchanges_to_init}")
        print(f"USDT capital per exchange: ${usdt_capital_per_exchange}")
        print(f"Base asset capital (for each of {len(settings.USER_DEFINED_PAIRS)} pairs) per exchange: {base_asset_capital_per_exchange} units of base asset")

        for exchange_id in exchanges_to_init:
            self.test_balances[exchange_id] = {
                "USDT": {"free": float(usdt_capital_per_exchange), "used": 0.0, "total": float(usdt_capital_per_exchange)}
            }
            for pair_str in settings.USER_DEFINED_PAIRS:
                base_currency, _ = pair_str.split("/")
                if base_currency not in self.test_balances[exchange_id]:
                    self.test_balances[exchange_id][base_currency] = {
                        "free": float(base_asset_capital_per_exchange),
                        "used": 0.0,
                        "total": float(base_asset_capital_per_exchange)
                    }
        print(f"Test balances initialized. Example for {exchanges_to_init[0] if exchanges_to_init else 'N/A'}: {self.test_balances.get(exchanges_to_init[0] if exchanges_to_init else None)}")

    async def _main_loop(self):
        print(f"Main loop started. Bot running: {self.running}, Test mode: {self.test_mode}")
        loop_iterations = 0
        
        while self.running:
            loop_iterations += 1
            start_time_iteration = time.perf_counter()
            try:
                if loop_iterations % 60 == 0: # Log less frequently
                    print(f"Main loop iter: {loop_iterations}, Running: {self.running}, Mode: {"Test" if self.test_mode else "Live"}, Opps: {len(self.opportunities)}, Trades: {len(self.trades)}")
                
                connected_exchanges = list(exchange_manager.exchanges.keys())
                if len(connected_exchanges) < 2:
                    if loop_iterations % 10 == 1: 
                        print(f"Insufficient exchanges connected ({len(connected_exchanges)}). Need at least 2. Skipping scan.")
                        alert_msg = AlertMessage(type="system_warning", message="Insufficient exchanges connected. Need at least 2.", severity="warning", entity_name="system")
                        await self._broadcast_alert(alert_msg)
                    await asyncio.sleep(5) 
                    continue
                
                # Check and reactivate failsafes periodically
                if loop_iterations % 12 == 0: # Every ~minute if scan interval is 5s
                    await self._check_and_reactivate_failsafes()

                for pair in settings.USER_DEFINED_PAIRS:
                    if not self.running: break 
                    await self._scan_arbitrage_opportunities(pair, connected_exchanges)
                
                if not self.running: break
                await asyncio.sleep(settings.SCAN_INTERVAL_SECONDS)

            except asyncio.CancelledError:
                print("Main loop task cancelled.")
                self.running = False 
                break
            except Exception as e:
                error_msg = f"Critical Error in arbitrage main loop (iter {loop_iterations}): {str(e)}"
                print(error_msg)
                print(traceback.format_exc())
                alert = AlertMessage(type="system_error", message=error_msg[:200], severity="critical", entity_name="main_loop")
                await self._broadcast_alert(alert)
                await asyncio.sleep(10) 
            finally:
                end_time_iteration = time.perf_counter()
                if loop_iterations % 60 == 0:
                     print(f"Main loop iteration {loop_iterations} took {end_time_iteration - start_time_iteration:.4f} seconds.")

        self.running = False 
        print(f"Main loop exited. Bot running: {self.running}, Test mode: {self.test_mode}")
        if self.test_mode:
             await self._broadcast_test_simulation_status("STOPPED", "Simulation loop ended.")

    async def _check_and_reactivate_failsafes(self):
        now = datetime.now()
        changed = False
        for pair, data in list(self.failsafe_status.disabled_pairs.items()):
            if data.cooldown_until and now >= datetime.fromisoformat(data.cooldown_until):
                del self.failsafe_status.disabled_pairs[pair]
                msg = f"Pair {pair} automatically reactivated after cooldown."
                print(msg)
                alert = AlertMessage(type="pair_reactivated", message=msg, severity="info", entity_name=pair)
                await self._broadcast_alert(alert)
                changed = True
        
        for ex, data in list(self.failsafe_status.disabled_exchanges.items()):
            if data.cooldown_until and now >= datetime.fromisoformat(data.cooldown_until):
                del self.failsafe_status.disabled_exchanges[ex]
                msg = f"Exchange {ex} automatically reactivated after cooldown."
                print(msg)
                alert = AlertMessage(type="exchange_reactivated", message=msg, severity="info", entity_name=ex)
                await self._broadcast_alert(alert)
                changed = True
        
        if self.failsafe_status.global_trading_halt and self.failsafe_status.global_halt_reason == "manual_reactivation_pending":
            # This state means it was halted and needs manual reactivation, auto-check doesn't apply here
            pass 

        if changed:
            await self._broadcast_failsafe_status()

    async def reactivate_failsafe(self, reactivation_type: str, entity_name: Optional[str] = None):
        changed = False
        if reactivation_type == "global" and self.failsafe_status.global_trading_halt:
            self.failsafe_status.global_trading_halt = False
            self.failsafe_status.global_halt_reason = None
            self.failsafe_status.global_halt_timestamp = None
            msg = "Global trading manually reactivated."
            print(msg)
            alert = AlertMessage(type="global_trading_reactivated", message=msg, severity="warning", entity_name="system")
            await self._broadcast_alert(alert)
            changed = True
        elif reactivation_type == "exchange" and entity_name and entity_name in self.failsafe_status.disabled_exchanges:
            del self.failsafe_status.disabled_exchanges[entity_name]
            msg = f"Exchange {entity_name} manually reactivated."
            print(msg)
            alert = AlertMessage(type="exchange_reactivated", message=msg, severity="info", entity_name=entity_name)
            await self._broadcast_alert(alert)
            changed = True
        elif reactivation_type == "pair" and entity_name and entity_name in self.failsafe_status.disabled_pairs:
            del self.failsafe_status.disabled_pairs[entity_name]
            msg = f"Pair {entity_name} manually reactivated."
            print(msg)
            alert = AlertMessage(type="pair_reactivated", message=msg, severity="info", entity_name=entity_name)
            await self._broadcast_alert(alert)
            changed = True
        
        if changed:
            await self._broadcast_failsafe_status()
        else:
            print(f"No change made for failsafe reactivation: type={reactivation_type}, entity={entity_name}")

    def _update_failure_count(self, type: str, entity_name: str, reason: str):
        now = datetime.now()
        changed = False
        if type == "pair":
            self.failsafe_status.pair_failure_counts[entity_name] = self.failsafe_status.pair_failure_counts.get(entity_name, 0) + 1
            if self.failsafe_status.pair_failure_counts[entity_name] >= settings.FAILSAFE_PAIR_MAX_FAILURES:
                cooldown = timedelta(minutes=settings.FAILSAFE_COOLDOWN_MINUTES_PAIR)
                self.failsafe_status.disabled_pairs[entity_name] = {
                    "reason": reason,
                    "timestamp": now.isoformat(),
                    "cooldown_until": (now + cooldown).isoformat()
                }
                msg = f"Pair {entity_name} disabled due to excessive failures ({reason}). Cooldown: {settings.FAILSAFE_COOLDOWN_MINUTES_PAIR}m."
                print(msg)
                alert = AlertMessage(type="pair_disabled", message=msg, severity="warning", entity_name=entity_name)
                asyncio.create_task(self._broadcast_alert(alert)) # MODIFICATION: Use create_task for broadcast from sync context
                changed = True
        elif type == "exchange":
            self.failsafe_status.exchange_failure_counts[entity_name] = self.failsafe_status.exchange_failure_counts.get(entity_name, 0) + 1
            if self.failsafe_status.exchange_failure_counts[entity_name] >= settings.FAILSAFE_EXCHANGE_MAX_FAILURES:
                cooldown = timedelta(minutes=settings.FAILSAFE_COOLDOWN_MINUTES_EXCHANGE)
                self.failsafe_status.disabled_exchanges[entity_name] = {
                    "reason": reason,
                    "timestamp": now.isoformat(),
                    "cooldown_until": (now + cooldown).isoformat()
                }
                msg = f"Exchange {entity_name} disabled due to excessive failures ({reason}). Cooldown: {settings.FAILSAFE_COOLDOWN_MINUTES_EXCHANGE}m."
                print(msg)
                alert = AlertMessage(type="exchange_disabled", message=msg, severity="critical", entity_name=entity_name)
                asyncio.create_task(self._broadcast_alert(alert))
                changed = True
        
        if changed:
            asyncio.create_task(self._broadcast_failsafe_status())

    def _trigger_global_halt(self, reason: str):
        if not self.failsafe_status.global_trading_halt:
            self.failsafe_status.global_trading_halt = True
            self.failsafe_status.global_halt_reason = reason
            self.failsafe_status.global_halt_timestamp = datetime.now().isoformat()
            msg = f"GLOBAL TRADING HALTED. Reason: {reason}. Manual reactivation required."
            print(msg)
            alert = AlertMessage(type="global_trading_halted", message=msg, severity="critical", entity_name="system")
            asyncio.create_task(self._broadcast_alert(alert))
            asyncio.create_task(self._broadcast_failsafe_status())

    async def _scan_arbitrage_opportunities(self, pair: str, exchanges: List[str]):
        if self.failsafe_status.global_trading_halt:
            return
        if pair in self.failsafe_status.disabled_pairs:
            return
        
        order_books: Dict[str, OrderBook] = {}
        fetch_tasks = []
        valid_exchanges_for_pair_scan = []

        for exchange_id in exchanges:
            if exchange_id in self.failsafe_status.disabled_exchanges:
                continue
            valid_exchanges_for_pair_scan.append(exchange_id)
            fetch_tasks.append(exchange_manager.fetch_order_book(exchange_id, pair))
        
        if len(valid_exchanges_for_pair_scan) < 2: return

        fetched_order_books_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        for i, result in enumerate(fetched_order_books_results):
            exchange_id = valid_exchanges_for_pair_scan[i]
            if isinstance(result, Exception):
                print(f"Error fetching order book for {pair} on {exchange_id}: {result}")
                self._update_failure_count("pair", f"{pair}@{exchange_id}", f"OB fetch error: {str(result)[:50]}")
                continue
            if result:
                book_time = datetime.fromisoformat(result.timestamp)
                if datetime.now() - book_time > timedelta(seconds=settings.ORDER_BOOK_STALENESS_THRESHOLD_SECONDS):
                    print(f"Order book for {pair} on {exchange_id} is stale. Skipping.")
                    continue
                order_books[exchange_id] = result
        
        if len(order_books) < 2: return
        
        for buy_exchange_id in order_books.keys():
            for sell_exchange_id in order_books.keys():
                if buy_exchange_id == sell_exchange_id: continue

                buy_ob = order_books[buy_exchange_id]
                sell_ob = order_books[sell_exchange_id]

                if not buy_ob.asks or not sell_ob.bids: continue
                if not buy_ob.asks[0] or not sell_ob.bids[0]: continue # Ensure first level exists

                buy_price = buy_ob.asks[0].price
                sell_price = sell_ob.bids[0].price

                if not buy_price or not sell_price or buy_price <= 0: continue

                spread = (sell_price - buy_price) / buy_price
                buy_fee = exchange_manager.get_taker_fee(buy_exchange_id, pair)
                sell_fee = exchange_manager.get_taker_fee(sell_exchange_id, pair)
                buy_slippage = settings.DEFAULT_SLIPPAGE_PERCENTAGE 
                sell_slippage = settings.DEFAULT_SLIPPAGE_PERCENTAGE
                total_cost_percentage = buy_fee + sell_fee + buy_slippage + sell_slippage + self.buffer_percentage
                potential_profit_percentage = spread - total_cost_percentage

                if potential_profit_percentage > settings.MIN_PROFIT_PERCENTAGE_THRESHOLD:
                    max_tradeable_amount_base = self._calculate_max_trade_amount(
                        buy_exchange_id, sell_exchange_id, pair, buy_ob, sell_ob, buy_price, sell_price
                    )
                    
                    if max_tradeable_amount_base > settings.MIN_TRADE_AMOUNT_BASE:
                        opportunity = ArbitrageOpportunity(
                            id=str(uuid.uuid4()),
                            buy_exchange=buy_exchange_id,
                            sell_exchange=sell_exchange_id,
                            symbol=pair,
                            buy_price=buy_price,
                            sell_price=sell_price,
                            spread_percentage=spread * 100,
                            potential_profit_percentage=potential_profit_percentage * 100,
                            max_trade_amount_base=max_tradeable_amount_base,
                            timestamp=datetime.now().isoformat()
                        )
                        # self.opportunities.append(opportunity) # Store if needed, but primary action is execution
                        print(f"Found opportunity: {opportunity.symbol} Buy {buy_exchange_id}@{buy_price:.8f}, Sell {sell_exchange_id}@{sell_price:.8f}, Profit: {potential_profit_percentage*100:.4f}%, Amount: {max_tradeable_amount_base:.8f}")
                        await self._execute_arbitrage(opportunity)
    
    def _calculate_max_trade_amount(self, buy_ex: str, sell_ex: str, pair: str, buy_ob: OrderBook, sell_ob: OrderBook, buy_price: float, sell_price: float) -> float:
        base_currency, quote_currency = pair.split("/")
        
        # Liquidity at best price
        buy_liquidity_base = buy_ob.asks[0].amount if buy_ob.asks else 0
        sell_liquidity_base = sell_ob.bids[0].amount if sell_ob.bids else 0
        
        # Consider deeper liquidity if needed (summing up to N levels)
        # For now, using best price liquidity

        # Balance checks
        if self.test_mode:
            buy_exchange_quote_balance = self.test_balances.get(buy_ex, {}).get(quote_currency, {}).get("free", 0)
            sell_exchange_base_balance = self.test_balances.get(sell_ex, {}).get(base_currency, {}).get("free", 0)
        else:
            buy_exchange_quote_balance = exchange_manager.get_balance(buy_ex, quote_currency)
            sell_exchange_base_balance = exchange_manager.get_balance(sell_ex, base_currency)

        # Max amount based on available quote currency to buy
        max_buy_from_balance_base = buy_exchange_quote_balance / buy_price if buy_price > 0 else 0
        # Max amount based on available base currency to sell
        max_sell_from_balance_base = sell_exchange_base_balance

        # Smallest of all constraints
        max_amount_base = min(
            buy_liquidity_base,
            sell_liquidity_base,
            max_buy_from_balance_base,
            max_sell_from_balance_base
        )
        
        # Apply global max trade amount cap (in quote currency, so convert max_amount_base)
        max_amount_base_from_cap = self.max_trade_amount_quote / buy_price if buy_price > 0 else 0
        max_amount_base = min(max_amount_base, max_amount_base_from_cap)
        
        return max(0, max_amount_base) # Ensure non-negative

    async def _execute_arbitrage(self, opportunity: ArbitrageOpportunity):
        if self.failsafe_status.global_trading_halt:
            print(f"Trade execution skipped for {opportunity.symbol} due to global halt.")
            return

        print(f"Attempting to execute arbitrage: {opportunity.symbol} Buy {opportunity.buy_exchange}@{opportunity.buy_price}, Sell {opportunity.sell_exchange}@{opportunity.sell_price}, Amount: {opportunity.max_trade_amount_base}")
        
        trade_amount_base = opportunity.max_trade_amount_base
        trade_amount_quote = trade_amount_base * opportunity.buy_price # Approximate quote value for buy leg

        if trade_amount_quote > self.max_trade_amount_quote:
            # This check should ideally be redundant if _calculate_max_trade_amount is correct
            print(f"Trade amount ${trade_amount_quote:.2f} exceeds max cap ${self.max_trade_amount_quote:.2f}. Adjusting.")
            trade_amount_base = self.max_trade_amount_quote / opportunity.buy_price
            trade_amount_quote = self.max_trade_amount_quote
            if trade_amount_base < settings.MIN_TRADE_AMOUNT_BASE:
                print(f"Adjusted trade amount {trade_amount_base} is below minimum. Skipping trade.")
                return

        buy_order_id = None
        sell_order_id = None
        buy_trade_details: Optional[Trade] = None
        sell_trade_details: Optional[Trade] = None
        error_messages = []

        try:
            # Execute buy order
            print(f"Executing BUY on {opportunity.buy_exchange} for {trade_amount_base} {opportunity.symbol.split('/')[0]} at ~{opportunity.buy_price}")
            if self.test_mode:
                buy_order_id = f"test_buy_{uuid.uuid4()}"
                # Simulate fill
                self.test_balances[opportunity.buy_exchange][opportunity.symbol.split("/")[1]]["free"] -= trade_amount_quote
                self.test_balances[opportunity.buy_exchange][opportunity.symbol.split("/")[0]]["free"] += trade_amount_base * (1 - exchange_manager.get_taker_fee(opportunity.buy_exchange, opportunity.symbol))
                buy_trade_details = Trade(
                    id=buy_order_id,
                    exchange=opportunity.buy_exchange,
                    symbol=opportunity.symbol,
                    type=OrderType.market, # Assuming market for simplicity in test
                    side=OrderSide.buy,
                    price=opportunity.buy_price, # Actual fill price might differ
                    amount=trade_amount_base,
                    cost=trade_amount_quote,
                    fee_amount=trade_amount_quote * exchange_manager.get_taker_fee(opportunity.buy_exchange, opportunity.symbol),
                    fee_currency=opportunity.symbol.split("/")[1],
                    timestamp=datetime.now().isoformat(),
                    status=OrderStatus.closed # Simulate filled
                )
                print(f"Test BUY executed: {buy_trade_details}")
            else:
                # Actual buy order
                buy_order_result = await exchange_manager.create_market_buy_order(
                    opportunity.buy_exchange, opportunity.symbol, trade_amount_base
                )
                if buy_order_result and buy_order_result.get("id"):
                    buy_order_id = buy_order_result["id"]
                    # TODO: Fetch actual filled details if create_market_buy_order doesn't return them
                    # For now, assume it's filled at opportunity price for simplicity of example
                    buy_trade_details = Trade(
                        id=buy_order_id,
                        exchange=opportunity.buy_exchange,
                        symbol=opportunity.symbol,
                        type=OrderType.market,
                        side=OrderSide.buy,
                        price=buy_order_result.get("price", opportunity.buy_price), 
                        amount=buy_order_result.get("filled", trade_amount_base),
                        cost=buy_order_result.get("cost", trade_amount_quote),
                        fee_amount=buy_order_result.get("fee", {}).get("cost", trade_amount_quote * exchange_manager.get_taker_fee(opportunity.buy_exchange, opportunity.symbol)),
                        fee_currency=buy_order_result.get("fee", {}).get("currency", opportunity.symbol.split("/")[1]),
                        timestamp=datetime.now().isoformat(), # Use order timestamp if available
                        status=OrderStatus.closed # Assuming filled
                    )
                    print(f"Live BUY executed: {buy_trade_details}")
                else:
                    error_messages.append(f"Buy order failed on {opportunity.buy_exchange}: {buy_order_result.get('info', 'Unknown error') if buy_order_result else 'No result'}")
                    self._update_failure_count("exchange", opportunity.buy_exchange, f"Buy order fail: {opportunity.symbol}")
                    self._update_failure_count("pair", f"{opportunity.symbol}@{opportunity.buy_exchange}", "Buy order fail")

            if not buy_trade_details: # If buy failed, don't proceed to sell
                raise Exception("Buy leg failed, aborting arbitrage.")

            # Execute sell order
            print(f"Executing SELL on {opportunity.sell_exchange} for {buy_trade_details.amount} {opportunity.symbol.split('/')[0]} at ~{opportunity.sell_price}")
            if self.test_mode:
                sell_order_id = f"test_sell_{uuid.uuid4()}"
                # Simulate fill
                sell_amount_quote = buy_trade_details.amount * opportunity.sell_price
                self.test_balances[opportunity.sell_exchange][opportunity.symbol.split("/")[0]]["free"] -= buy_trade_details.amount
                self.test_balances[opportunity.sell_exchange][opportunity.symbol.split("/")[1]]["free"] += sell_amount_quote * (1 - exchange_manager.get_taker_fee(opportunity.sell_exchange, opportunity.symbol))
                sell_trade_details = Trade(
                    id=sell_order_id,
                    exchange=opportunity.sell_exchange,
                    symbol=opportunity.symbol,
                    type=OrderType.market,
                    side=OrderSide.sell,
                    price=opportunity.sell_price,
                    amount=buy_trade_details.amount,
                    cost=sell_amount_quote,
                    fee_amount=sell_amount_quote * exchange_manager.get_taker_fee(opportunity.sell_exchange, opportunity.symbol),
                    fee_currency=opportunity.symbol.split("/")[1],
                    timestamp=datetime.now().isoformat(),
                    status=OrderStatus.closed
                )
                print(f"Test SELL executed: {sell_trade_details}")
            else:
                # Actual sell order
                sell_order_result = await exchange_manager.create_market_sell_order(
                    opportunity.sell_exchange, opportunity.symbol, buy_trade_details.amount # Sell the amount we actually bought
                )
                if sell_order_result and sell_order_result.get("id"):
                    sell_order_id = sell_order_result["id"]
                    sell_trade_details = Trade(
                        id=sell_order_id,
                        exchange=opportunity.sell_exchange,
                        symbol=opportunity.symbol,
                        type=OrderType.market,
                        side=OrderSide.sell,
                        price=sell_order_result.get("price", opportunity.sell_price),
                        amount=sell_order_result.get("filled", buy_trade_details.amount),
                        cost=sell_order_result.get("cost", buy_trade_details.amount * sell_order_result.get("price", opportunity.sell_price)),
                        fee_amount=sell_order_result.get("fee", {}).get("cost", buy_trade_details.amount * sell_order_result.get("price", opportunity.sell_price) * exchange_manager.get_taker_fee(opportunity.sell_exchange, opportunity.symbol)),
                        fee_currency=sell_order_result.get("fee", {}).get("currency", opportunity.symbol.split("/")[1]),
                        timestamp=datetime.now().isoformat(),
                        status=OrderStatus.closed
                    )
                    print(f"Live SELL executed: {sell_trade_details}")
                else:
                    error_messages.append(f"Sell order failed on {opportunity.sell_exchange}: {sell_order_result.get('info', 'Unknown error') if sell_order_result else 'No result'}")
                    self._update_failure_count("exchange", opportunity.sell_exchange, f"Sell order fail: {opportunity.symbol}")
                    self._update_failure_count("pair", f"{opportunity.symbol}@{opportunity.sell_exchange}", "Sell order fail")
                    # TODO: Handle sell leg failure (e.g., market sell remaining base asset, log critical alert)
                    # This is a critical situation if buy succeeded but sell failed.
                    crit_msg = f"CRITICAL: Buy succeeded for {buy_trade_details.amount} {opportunity.symbol} on {opportunity.buy_exchange}, but SELL FAILED on {opportunity.sell_exchange}. Manual intervention may be required."
                    print(crit_msg)
                    alert = AlertMessage(type="critical_trade_failure", message=crit_msg, severity="critical", entity_name=opportunity.symbol)
                    await self._broadcast_alert(alert)
                    self._trigger_global_halt(f"Sell leg failed for {opportunity.symbol} on {opportunity.sell_exchange} after buy succeeded.")

            if not sell_trade_details: # If sell failed
                 raise Exception("Sell leg failed.")

            # Calculate actual profit
            profit_quote = (sell_trade_details.cost - sell_trade_details.fee_amount) - (buy_trade_details.cost + buy_trade_details.fee_amount)
            profit_percentage = (profit_quote / (buy_trade_details.cost + buy_trade_details.fee_amount)) * 100 if (buy_trade_details.cost + buy_trade_details.fee_amount) > 0 else 0
            
            arbitrage_trade = ArbitrageTrade(
                id=str(uuid.uuid4()),
                opportunity_id=opportunity.id,
                symbol=opportunity.symbol,
                buy_trade=buy_trade_details,
                sell_trade=sell_trade_details,
                profit_quote=profit_quote,
                profit_percentage=profit_percentage,
                timestamp=datetime.now().isoformat(),
                is_test_trade=self.test_mode
            )
            self.trades.append(arbitrage_trade)
            await self._broadcast_new_trade(arbitrage_trade)
            print(f"Arbitrage executed successfully: {arbitrage_trade.symbol}, Profit: ${profit_quote:.2f} ({profit_percentage:.4f}%)")
            
            if self.test_mode:
                await self._broadcast_test_simulation_status("RUNNING", f"Trade executed for {opportunity.symbol}")
            else: # Live mode, update historical high balance if applicable
                current_total_usdt = sum(ex_bal.get("USDT", {}).get("total", 0) for ex_bal in (await exchange_manager.fetch_all_balances(list(exchange_manager.exchanges.keys()))).values())
                if current_total_usdt > self.failsafe_status.historical_high_balance_usdt:
                    self.failsafe_status.historical_high_balance_usdt = current_total_usdt
                    await self._broadcast_failsafe_status()

        except Exception as e:
            exec_error_msg = f"Error executing arbitrage for {opportunity.symbol}: {str(e)}"
            print(exec_error_msg)
            print(traceback.format_exc())
            error_messages.append(str(e))
            alert = AlertMessage(type="trade_execution_error", message=exec_error_msg[:200], severity="error", entity_name=opportunity.symbol)
            await self._broadcast_alert(alert)
            # Increment failure counts for involved exchanges/pairs if not already done
            if "Buy leg failed" not in str(e) and opportunity.buy_exchange: # Avoid double counting if buy already failed
                self._update_failure_count("exchange", opportunity.buy_exchange, f"Exec error: {opportunity.symbol}")
                self._update_failure_count("pair", f"{opportunity.symbol}@{opportunity.buy_exchange}", "Exec error")
            if "Sell leg failed" not in str(e) and opportunity.sell_exchange:
                self._update_failure_count("exchange", opportunity.sell_exchange, f"Exec error: {opportunity.symbol}")
                self._update_failure_count("pair", f"{opportunity.symbol}@{opportunity.sell_exchange}", "Exec error")

        finally:
            # Update balances via WebSocket after trade attempt (success or fail)
            if not self.test_mode:
                # For live mode, fetch and broadcast updated balances for involved exchanges
                try:
                    buy_ex_bal = await exchange_manager.fetch_balances(opportunity.buy_exchange)
                    await self._broadcast_exchange_balances(opportunity.buy_exchange, buy_ex_bal)
                    sell_ex_bal = await exchange_manager.fetch_balances(opportunity.sell_exchange)
                    await self._broadcast_exchange_balances(opportunity.sell_exchange, sell_ex_bal)
                except Exception as bal_e:
                    print(f"Error fetching/broadcasting post-trade balances: {bal_e}")
            else:
                # For test mode, broadcast the simulated balances
                await self._broadcast_exchange_balances(opportunity.buy_exchange, self.test_balances.get(opportunity.buy_exchange, {}))
                await self._broadcast_exchange_balances(opportunity.sell_exchange, self.test_balances.get(opportunity.sell_exchange, {}))

    # ... (other methods like get_status, get_trades, etc. can be added or refined)
    async def get_current_status(self) -> dict:
        return {
            "is_running": self.running,
            "is_test_mode": self.test_mode,
            "active_exchanges": list(exchange_manager.exchanges.keys()),
            "supported_exchanges": settings.SUPPORTED_EXCHANGES,
            "trading_pairs": settings.USER_DEFINED_PAIRS,
            "buffer_percentage": self.buffer_percentage * 100,
            "max_trade_amount_quote": self.max_trade_amount_quote,
            "opportunities_found_session": len(self.opportunities),
            "trades_executed_session": len(self.trades),
            "alerts_session": len(self.alerts),
            "failsafe_status": self.failsafe_status.model_dump(),
            "test_simulation_status": TestSimulationStatusPayload(
                status="RUNNING" if self.running and self.test_mode else "IDLE" if not self.running and self.test_mode else "N/A",
                message="Simulation active" if self.running and self.test_mode else "Simulation idle",
                active_since=self.test_simulation_active_since.isoformat() if self.test_simulation_active_since and self.running and self.test_mode else None,
                total_test_trades=len([t for t in self.trades if t.is_test_trade]),
                total_test_profit=sum(t.profit_quote for t in self.trades if t.is_test_trade)
            ).model_dump() if self.test_mode else None,
            "current_test_settings": self.current_test_settings if self.test_mode else None
        }

arbitrage_bot = ArbitrageBot()

