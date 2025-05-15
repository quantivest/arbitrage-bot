import asyncio
import time
import uuid
import traceback
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta, timezone
from .models import (
    ArbitrageOpportunity, ArbitrageTrade, Trade, OrderBook, AlertType, \
    FailsafeStatus, FailsafeStatusData, OrderBookEntry, ExchangeBalanceUpdate, BotStatusUpdate, \
    TestSimulationStatusPayload, FailsafeStatusUpdate, AlertMessage, \
    ExchangeConnectionStatus, OrderStatus, OrderType, OrderSide, TestModeSettings
)
from .exchanges import exchange_manager
from .config import settings
import logging

logger = logging.getLogger(__name__)

class ArbitrageBot:
    """Spot-to-spot arbitrage bot."""
    
    def __init__(self):
        self.running = False
        self.current_mode: str = "idle"  # Can be "idle", "live", "test_simulating", "test_idle"
        self._main_loop_task: Optional[asyncio.Task] = None
        self.opportunities: List[ArbitrageOpportunity] = []
        self.trades: List[ArbitrageTrade] = []
        self.test_balances: Dict[str, Dict[str, Dict[str, float]]] = {} # Stores virtual balances for test mode
        self.buffer_percentage = settings.BUFFER_PERCENTAGE
        self._failsafe_status_internal = FailsafeStatus(
            disabled_pairs={},
            disabled_exchanges={},
            global_trading_halt=False,
            global_halt_reason=None,
            global_halt_timestamp=None,
            historical_high_balance_usdt=0.0,
            pair_failure_counts={},
            exchange_failure_counts={}
        )
        self.alerts: List[AlertMessage] = []
        self.max_trade_amount_quote = settings.MAX_TRADE_AMOUNT_QUOTE
        self.min_trade_amount_quote = settings.MIN_TRADE_AMOUNT_QUOTE
        self.current_test_settings: Optional[TestModeSettings] = None
        self.test_simulation_active_since: Optional[datetime] = None
        self.test_simulation_error_message: Optional[str] = None
        self.live_total_trades = 0
        self.live_total_profit = 0.0
        logger.info(f"ArbitrageBot initialized. Default buffer: {self.buffer_percentage*100:.4f}%, Min trade: ${self.min_trade_amount_quote}, Max trade leg: ${self.max_trade_amount_quote}")
        
    def _set_test_error_message(self, error):
        """Safely set test simulation error message, ensuring it's always a string."""
        self.test_simulation_error_message = str(error) if error is not None else None
        logger.error(f"Test simulation error: {self.test_simulation_error_message}")

    @property
    def is_running(self) -> bool:
        return self.running

    @property
    def is_test_mode(self) -> bool:
        return self.current_mode in ["test_simulating", "test_idle"]

    @property
    def is_actively_simulating_test_mode(self) -> bool:
        return self.current_mode == "test_simulating" and self.running

    async def get_recent_opportunities(self, limit: int = 10) -> List[ArbitrageOpportunity]:
        return self.opportunities[:limit]

    async def get_recent_trades(self, limit: int = 10, is_test_trade: Optional[bool] = None) -> List[ArbitrageTrade]:
        if is_test_trade is None:
            return self.trades[:limit]
        return [t for t in self.trades if t.is_test_trade == is_test_trade][:limit]

    async def get_alerts(self, limit: int = 10) -> List[AlertMessage]:
        return self.alerts[:limit]

    async def get_failsafe_status(self) -> FailsafeStatusData:
        return FailsafeStatusData(
            global_trading_halt=self._failsafe_status_internal.global_trading_halt,
            global_halt_reason=self._failsafe_status_internal.global_halt_reason,
            global_halt_timestamp=self._failsafe_status_internal.global_halt_timestamp,
            disabled_exchanges=self._failsafe_status_internal.disabled_exchanges,
            disabled_pairs=self._failsafe_status_internal.disabled_pairs
        )

    async def get_test_simulation_status(self) -> TestSimulationStatusPayload:
        status_str = "IDLE"
        message_str = "Test simulation (dry run) is not active."
        if self.is_actively_simulating_test_mode:
            status_str = "RUNNING"
            message_str = "Test simulation (dry run) is active, scanning for real opportunities with virtual balances."
        elif self.current_mode == "test_idle" and not self.running: # Stopped after a test run
             status_str = "IDLE"
             message_str = "Test simulation (dry run) stopped."
        elif self.test_simulation_error_message:
            status_str = "ERROR"
            message_str = str(self.test_simulation_error_message) if self.test_simulation_error_message is not None else "Unknown error occurred"
        
        return TestSimulationStatusPayload(
            status=status_str,
            message=message_str,
            active_since=self.test_simulation_active_since.isoformat() if self.test_simulation_active_since and status_str == "RUNNING" else None,
            total_test_trades=len([t for t in self.trades if t.is_test_trade]),
            total_test_profit=sum(t.profit_quote for t in self.trades if t.is_test_trade),
            error_message=str(self.test_simulation_error_message) if status_str == "ERROR" and self.test_simulation_error_message is not None else None
        )

    async def start(self, mode: str, test_settings_data: Optional[Dict] = None) -> Tuple[bool, str]:
        logger.info(f"Attempting to start bot. Current state: running={self.running}, mode={self.current_mode}. Requested mode: {mode}")
        self.test_simulation_error_message = None  # Reset any previous error messages
        
        if self.running:
            logger.info("Bot is already running. Stopping first to ensure clean start.")
            await self.stop()

        if mode == "live":
            self.current_mode = "live"
            self.current_test_settings = None
            self.buffer_percentage = settings.BUFFER_PERCENTAGE
            logger.info(f"Live Mode: Using buffer percentage: {self.buffer_percentage*100:.4f}%")
        elif mode == "test" and test_settings_data:
            logger.info(f"Attempting to start Test Mode (Dry Run) with settings: {test_settings_data}")
            try:
                self.current_test_settings = TestModeSettings(**test_settings_data)
                logger.info(f"TestModeSettings parsed successfully: {self.current_test_settings}")
            except Exception as e:
                error_detail = f"Invalid test settings provided: {e}. Data: {test_settings_data}"
                logger.error(error_detail, exc_info=True)
                self._set_test_error_message(error_detail)
                self.current_mode = "test_idle"
                return False, error_detail
            
            self.current_mode = "test_simulating"
            logger.info(f"Initializing test balances for Dry Run with settings: {self.current_test_settings}")
            init_success, init_msg = await self._initialize_test_balances(self.current_test_settings)
            if not init_success:
                logger.error(f"Failed to initialize test balances for Dry Run: {init_msg}")
                self._set_test_error_message(f"Failed to initialize test balances for Dry Run: {init_msg}")
                self.current_mode = "test_idle"
                return False, self.test_simulation_error_message
            
            if self.current_test_settings.buffer_percentage is not None:
                self.buffer_percentage = self.current_test_settings.buffer_percentage / 100.0 
            else:
                self.buffer_percentage = settings.BUFFER_PERCENTAGE
            logger.info(f"Test Mode (Dry Run): Buffer percentage set to {self.buffer_percentage*100:.4f}%")
            self.test_simulation_active_since = datetime.now(timezone.utc)
        else:
            err_msg = "Invalid mode or missing test settings for test mode."
            logger.error(err_msg)
            return False, err_msg

        self.running = True
        self.opportunities = [] 

        loop = asyncio.get_event_loop()
        if self._main_loop_task and not self._main_loop_task.done():
            logger.warning("Warning: Previous main loop task was still active. Attempting to cancel.")
            self._main_loop_task.cancel()
            try:
                await self._main_loop_task
            except asyncio.CancelledError:
                logger.info("Previous main loop task successfully cancelled.")
        
        self._main_loop_task = loop.create_task(self._main_loop())
        logger.info(f"Bot started successfully in {self.current_mode} mode with {len(settings.USER_DEFINED_PAIRS)} trading pairs.")
        return True, f"Bot started in {self.current_mode} mode."
    
    async def stop(self) -> Tuple[bool, str]:
        logger.info(f"Attempting to stop bot. Current state: running={self.running}, mode={self.current_mode}")
        if not self.running:
            logger.info("Bot is not running.")
            if self.current_mode in ["test_simulating", "test_idle"] and self.test_simulation_error_message:
                pass 
            if self.current_mode == "test_simulating": 
                self.current_mode = "test_idle"
            elif self.current_mode == "live":
                self.current_mode = "idle"
            return True, "Bot was not running."

        self.running = False 
        current_mode_before_stop = self.current_mode
        self.current_mode = "test_idle" if current_mode_before_stop == "test_simulating" else "idle"

        if self._main_loop_task and not self._main_loop_task.done():
            logger.info("Cancelling main loop task...")
            self._main_loop_task.cancel()
            try:
                await self._main_loop_task
                logger.info("Main loop task successfully awaited after cancellation.")
            except asyncio.CancelledError:
                logger.info("Main loop task successfully cancelled (caught CancelledError).")
            except Exception as e:
                logger.error(f"Error awaiting main loop task cancellation: {e}")
        self._main_loop_task = None
        
        if current_mode_before_stop == "test_simulating":
            self.test_simulation_active_since = None

        logger.info("Arbitrage bot stopped.")
        return True, "Bot stopped successfully."
    
    async def _initialize_test_balances(self, test_settings: TestModeSettings) -> Tuple[bool, str]:
        self.test_balances = {}
        exchanges_to_init = test_settings.exchanges or list(exchange_manager.exchanges.keys())
        if not exchanges_to_init:
            return False, "No exchanges connected or specified for test mode."

        usdt_capital_per_exchange = test_settings.usdt_capital_per_exchange
        asset_capital_usd_per_pair = test_settings.asset_capital_usd_per_pair 

        logger.info(f"Initializing test balances for exchanges: {exchanges_to_init}")
        logger.info(f"USDT capital per exchange: ${usdt_capital_per_exchange}")
        logger.info(f"USD value for each base asset (for {len(settings.USER_DEFINED_PAIRS)} pairs) per exchange: ${asset_capital_usd_per_pair}")

        price_source_exchange = None
        if test_settings.exchanges:
            for ex_id in test_settings.exchanges:
                if ex_id in exchange_manager.exchanges:
                    price_source_exchange = ex_id
                    logger.info(f"Using specified and connected exchange {ex_id} as price source for test balance init.")
                    break
        
        if not price_source_exchange and exchange_manager.exchanges:
            price_source_exchange = list(exchange_manager.exchanges.keys())[0]
            logger.info(f"Using first connected exchange {price_source_exchange} as price source for test balance init.")
        
        if not price_source_exchange and asset_capital_usd_per_pair > 0:
            msg = "Cannot initialize asset balances in USD without at least one connected exchange to fetch prices."
            logger.error(msg)
            await self._add_alert(AlertType.SYSTEM_ERROR, msg, "global", "error")
            return False, msg

        for exchange_id in exchanges_to_init:
            if exchange_id not in exchange_manager.exchanges and asset_capital_usd_per_pair > 0:
                logger.warning(f"Exchange {exchange_id} specified in test settings is not connected. Skipping asset initialization for it.")
                if price_source_exchange == exchange_id and not any(ex in exchange_manager.exchanges for ex in exchanges_to_init if ex != exchange_id):
                    msg = f"Price source exchange {exchange_id} for test balance init is not connected, and no other connected exchanges available in test settings."
                    logger.error(msg)
                    return False, msg
                self.test_balances[exchange_id] = {
                    "USDT": {"free": float(usdt_capital_per_exchange), "used": 0.0, "total": float(usdt_capital_per_exchange)}
                }
                continue 
            
            self.test_balances[exchange_id] = {
                "USDT": {"free": float(usdt_capital_per_exchange), "used": 0.0, "total": float(usdt_capital_per_exchange)}
            }
            for pair_str in settings.USER_DEFINED_PAIRS:
                base_currency, quote_currency = pair_str.split("/")
                if quote_currency != "USDT": 
                    logger.warning(f"Skipping non-USDT pair {pair_str} for USD-based asset initialization.")
                    continue

                if base_currency not in self.test_balances[exchange_id]:
                    asset_quantity = 0.0
                    if asset_capital_usd_per_pair > 0 and price_source_exchange:
                        if price_source_exchange not in exchange_manager.exchanges:
                            logger.error(f"Price source exchange {price_source_exchange} is no longer connected. Cannot initialize {base_currency} for {exchange_id}.")
                            asset_quantity = 0.0
                        else:
                            try:
                                ticker = await exchange_manager.fetch_ticker(price_source_exchange, pair_str)
                                if ticker and ticker.get("last") and ticker["last"] > 0:
                                    asset_quantity = asset_capital_usd_per_pair / ticker["last"]
                                    logger.info(f"For {pair_str} on {exchange_id}, ${asset_capital_usd_per_pair} at price {ticker['last']} = {asset_quantity:.8f} {base_currency}")
                                else:
                                    logger.warning(f"Could not fetch valid price for {pair_str} on {price_source_exchange}. Defaulting {base_currency} to 0 units for {exchange_id}.")
                            except Exception as e:
                                logger.error(f"Error fetching price for {pair_str} on {price_source_exchange} for test balance init: {e}. Defaulting {base_currency} to 0 units for {exchange_id}.")
                    
                    self.test_balances[exchange_id][base_currency] = {
                        "free": float(asset_quantity),
                        "used": 0.0,
                        "total": float(asset_quantity)
                    }
        logger.info(f"Test balances initialized: {self.test_balances}")
        await self._broadcast_bot_status() # Broadcast initial test balances
        return True, "Test balances initialized successfully."

    async def _main_loop(self):
        logger.info(f"Main loop started for mode: {self.current_mode}")
        while self.running:
            try:
                if self._failsafe_status_internal.global_trading_halt:
                    logger.warning(f"Global trading halt is active. Reason: {self._failsafe_status_internal.global_halt_reason}. Sleeping for {settings.FAILSAFE_GLOBAL_HALT_RECOVERY_CHECK_INTERVAL_SECONDS}s.")
                    await asyncio.sleep(settings.FAILSAFE_GLOBAL_HALT_RECOVERY_CHECK_INTERVAL_SECONDS)
                    await self._check_global_halt_recovery()
                    continue

                start_time = time.time()
                logger.debug(f"Main loop iteration started at {datetime.now(timezone.utc).isoformat()} for mode {self.current_mode}")

                # Fetch real order books for both live and true dry-run test mode
                all_order_books = await exchange_manager.get_all_order_books_for_pairs(settings.USER_DEFINED_PAIRS)
                
                if not all_order_books:
                    logger.warning("No order books fetched. Sleeping.")
                    await asyncio.sleep(settings.SCAN_INTERVAL_SECONDS)
                    continue

                opportunities = await self._find_opportunities(all_order_books)
                if opportunities:
                    logger.info(f"Found {len(opportunities)} potential opportunities.")
                    for opp in opportunities:
                        if self._failsafe_status_internal.global_trading_halt:
                            logger.info("Global trading halt activated during opportunity processing. Breaking loop.")
                            break
                        await self._execute_arbitrage(opp)
                else:
                    logger.debug("No arbitrage opportunities found in this iteration.")
                
                # Update balances periodically, especially for test mode to reflect simulated trades
                if self.is_actively_simulating_test_mode:
                    await self._broadcast_bot_status() # Ensure test balances are sent
                elif self.current_mode == "live": # For live mode, rely on exchange manager to update via WebSocket or periodic fetch
                    pass # Live balances are updated by exchange_manager

                elapsed_time = time.time() - start_time
                sleep_duration = max(0, settings.SCAN_INTERVAL_SECONDS - elapsed_time)
                logger.debug(f"Loop iteration took {elapsed_time:.2f}s. Sleeping for {sleep_duration:.2f}s.")
                await asyncio.sleep(sleep_duration)

            except asyncio.CancelledError:
                logger.info("Main loop cancelled.")
                break
            except Exception as e:
                logger.error(f"Error in main loop: {e}", exc_info=True)
                await self._add_alert(AlertType.SYSTEM_ERROR, f"Main loop error: {e}", "global", "critical")
                # Implement a more robust error handling, e.g., exponential backoff or specific error recovery
                await asyncio.sleep(settings.SCAN_INTERVAL_SECONDS * 2) # Longer sleep on error
        logger.info(f"Main loop ended. Bot running: {self.running}, Mode: {self.current_mode}")

    async def _find_opportunities(self, all_order_books: Dict[str, Dict[str, OrderBook]]) -> List[ArbitrageOpportunity]:
        opportunities = []
        if not all_order_books:
            return opportunities

        for pair in settings.USER_DEFINED_PAIRS:
            if self._is_pair_disabled(pair):
                logger.debug(f"Pair {pair} is disabled by failsafe. Skipping opportunity scan.")
                continue

            pair_order_books = {ex: books[pair] for ex, books in all_order_books.items() if pair in books}
            if len(pair_order_books) < 2:
                continue

            exchanges = list(pair_order_books.keys())
            for i in range(len(exchanges)):
                for j in range(len(exchanges)):
                    if i == j: 
                        continue

                    buy_exchange_id = exchanges[i]
                    sell_exchange_id = exchanges[j]

                    if self._is_exchange_disabled(buy_exchange_id) or self._is_exchange_disabled(sell_exchange_id):
                        logger.debug(f"One of the exchanges ({buy_exchange_id}, {sell_exchange_id}) for pair {pair} is disabled. Skipping.")
                        continue

                    buy_book = pair_order_books[buy_exchange_id]
                    sell_book = pair_order_books[sell_exchange_id]

                    if not buy_book.asks or not sell_book.bids:
                        continue

                    best_ask_price = buy_book.asks[0].price
                    best_ask_volume = buy_book.asks[0].amount
                    best_bid_price = sell_book.bids[0].price
                    best_bid_volume = sell_book.bids[0].amount

                    if best_ask_price <= 0 or best_bid_price <= 0:
                        continue # Invalid prices

                    profit_percentage = ((best_bid_price - best_ask_price) / best_ask_price) * 100

                    if profit_percentage > self.buffer_percentage * 100:
                        opportunity = ArbitrageOpportunity(
                            pair=pair,
                            buy_exchange=buy_exchange_id,
                            sell_exchange=sell_exchange_id,
                            buy_price=best_ask_price,
                            sell_price=best_bid_price,
                            potential_profit_percentage=profit_percentage,
                            timestamp=datetime.now(timezone.utc),
                            buy_exchange_orderbook_timestamp=buy_book.timestamp,
                            sell_exchange_orderbook_timestamp=sell_book.timestamp,
                            max_volume_base=min(best_ask_volume, best_bid_volume) # Simplistic volume for now
                        )
                        opportunities.append(opportunity)
                        self.opportunities.insert(0, opportunity)
                        if len(self.opportunities) > 50: # Keep last 50
                            self.opportunities.pop()
                        logger.info(f"Found opportunity: {opportunity}")
        
        opportunities.sort(key=lambda o: o.potential_profit_percentage, reverse=True)
        return opportunities

    async def _execute_arbitrage(self, opportunity: ArbitrageOpportunity):
        logger.info(f"Attempting to execute arbitrage for: {opportunity.pair} on {opportunity.buy_exchange} -> {opportunity.sell_exchange}")
        base_currency, quote_currency = opportunity.pair.split("/")
        is_test = self.is_actively_simulating_test_mode

        # 1. Determine trade amount (Base currency quantity)
        # Use the smaller of available balance or max_volume_base from opportunity, constrained by min/max trade sizes
        
        # Get available balances
        buy_exchange_base_balance = 0.0
        buy_exchange_quote_balance = 0.0
        sell_exchange_base_balance = 0.0
        sell_exchange_quote_balance = 0.0

        if is_test:
            buy_exchange_base_balance = self.test_balances.get(opportunity.buy_exchange, {}).get(base_currency, {}).get("free", 0.0)
            buy_exchange_quote_balance = self.test_balances.get(opportunity.buy_exchange, {}).get(quote_currency, {}).get("free", 0.0)
            sell_exchange_base_balance = self.test_balances.get(opportunity.sell_exchange, {}).get(base_currency, {}).get("free", 0.0)
            sell_exchange_quote_balance = self.test_balances.get(opportunity.sell_exchange, {}).get(quote_currency, {}).get("free", 0.0)
        else: # Live mode
            buy_balances = await exchange_manager.get_balances(opportunity.buy_exchange)
            sell_balances = await exchange_manager.get_balances(opportunity.sell_exchange)
            if buy_balances and base_currency in buy_balances and quote_currency in buy_balances:
                buy_exchange_base_balance = buy_balances[base_currency].get("free", 0.0)
                buy_exchange_quote_balance = buy_balances[quote_currency].get("free", 0.0)
            if sell_balances and base_currency in sell_balances and quote_currency in sell_balances:
                sell_exchange_base_balance = sell_balances[base_currency].get("free", 0.0)
                sell_exchange_quote_balance = sell_balances[quote_currency].get("free", 0.0)

        # Max amount we can buy with available quote currency on buy_exchange
        max_buyable_base_with_quote = (buy_exchange_quote_balance * 0.99) / opportunity.buy_price if opportunity.buy_price > 0 else 0 # 0.99 for safety
        # Max amount we can sell from available base currency on sell_exchange
        max_sellable_base = sell_exchange_base_balance * 0.99 # 0.99 for safety

        # Smallest of opportunity volume, what we can afford to buy, what we have to sell
        tradable_base_amount = min(opportunity.max_volume_base, max_buyable_base_with_quote, max_sellable_base)
        
        # Apply min/max trade size constraints (in quote currency for the buy leg)
        buy_leg_quote_value = tradable_base_amount * opportunity.buy_price
        
        if buy_leg_quote_value < self.min_trade_amount_quote:
            logger.info(f"Skipping opportunity: Trade value ${buy_leg_quote_value:.2f} is below min ${self.min_trade_amount_quote:.2f}")
            return
        if buy_leg_quote_value > self.max_trade_amount_quote:
            logger.info(f"Clamping trade: Trade value ${buy_leg_quote_value:.2f} is above max ${self.max_trade_amount_quote:.2f}. Adjusting base amount.")
            tradable_base_amount = self.max_trade_amount_quote / opportunity.buy_price
            buy_leg_quote_value = tradable_base_amount * opportunity.buy_price # Recalculate

        if tradable_base_amount <= 0:
            logger.info(f"Skipping opportunity: Calculated tradable base amount is {tradable_base_amount:.8f} for {opportunity.pair}")
            return

        logger.info(f"Calculated tradable base amount for {opportunity.pair}: {tradable_base_amount:.8f} {base_currency} (Value: ${buy_leg_quote_value:.2f}) Test Mode: {is_test}")

        # Simulate or Execute Trades
        buy_order_id = f"sim_buy_{uuid.uuid4()}" if is_test else None
        sell_order_id = f"sim_sell_{uuid.uuid4()}" if is_test else None
        buy_trade_status = OrderStatus.FILLED if is_test else OrderStatus.PENDING
        sell_trade_status = OrderStatus.FILLED if is_test else OrderStatus.PENDING
        actual_buy_price = opportunity.buy_price
        actual_sell_price = opportunity.sell_price
        buy_fee_cost = 0.0
        sell_fee_cost = 0.0
        
        trade_timestamp = datetime.now(timezone.utc)

        try:
            if is_test:
                # Simulate trade execution and update virtual balances
                cost_of_buy_quote = tradable_base_amount * actual_buy_price
                proceeds_from_sell_quote = tradable_base_amount * actual_sell_price
                
                # Simulate fees (using a generic fee rate for now, can be exchange-specific later)
                sim_fee_rate = settings.SIMULATED_FEE_RATE # e.g., 0.001 for 0.1%
                buy_fee_cost = cost_of_buy_quote * sim_fee_rate
                sell_fee_cost = proceeds_from_sell_quote * sim_fee_rate

                # Update quote currency on buy exchange
                self.test_balances[opportunity.buy_exchange][quote_currency]["free"] -= (cost_of_buy_quote + buy_fee_cost)
                self.test_balances[opportunity.buy_exchange][quote_currency]["total"] -= (cost_of_buy_quote + buy_fee_cost)
                # Update base currency on buy exchange
                self.test_balances[opportunity.buy_exchange][base_currency]["free"] += tradable_base_amount
                self.test_balances[opportunity.buy_exchange][base_currency]["total"] += tradable_base_amount

                # Update base currency on sell exchange
                self.test_balances[opportunity.sell_exchange][base_currency]["free"] -= tradable_base_amount
                self.test_balances[opportunity.sell_exchange][base_currency]["total"] -= tradable_base_amount
                # Update quote currency on sell exchange
                self.test_balances[opportunity.sell_exchange][quote_currency]["free"] += (proceeds_from_sell_quote - sell_fee_cost)
                self.test_balances[opportunity.sell_exchange][quote_currency]["total"] += (proceeds_from_sell_quote - sell_fee_cost)
                
                logger.info(f"[TEST MODE] Simulated BUY {tradable_base_amount:.8f} {base_currency} @ {actual_buy_price} on {opportunity.buy_exchange}")
                logger.info(f"[TEST MODE] Simulated SELL {tradable_base_amount:.8f} {base_currency} @ {actual_sell_price} on {opportunity.sell_exchange}")
                await self._broadcast_bot_status() # Update UI with new test balances

            else: # Live mode execution
                logger.info(f"Executing LIVE BUY on {opportunity.buy_exchange} for {tradable_base_amount} {base_currency} of {opportunity.pair} at ~{opportunity.buy_price}")
                buy_order = await exchange_manager.create_order(
                    exchange_id=opportunity.buy_exchange,
                    pair=opportunity.pair,
                    order_type=OrderType.LIMIT, # Or MARKET, depending on strategy
                    side=OrderSide.BUY,
                    amount=tradable_base_amount,
                    price=opportunity.buy_price # For LIMIT orders
                )
                if buy_order and buy_order.get("id"):
                    buy_order_id = buy_order["id"]
                    buy_trade_status = OrderStatus.OPEN # Or FILLED if market order and filled immediately
                    actual_buy_price = float(buy_order.get("price", opportunity.buy_price))
                    buy_fee_cost = float(buy_order.get("fee", {}).get("cost", 0.0))
                    logger.info(f"Live BUY order placed: {buy_order_id} on {opportunity.buy_exchange}")
                    # TODO: Add logic to monitor order status and handle partial fills / timeouts
                else:
                    err_msg = f"Failed to place BUY order on {opportunity.buy_exchange} for {opportunity.pair}. Order: {buy_order}"
                    logger.error(err_msg)
                    await self._add_alert(AlertType.TRADE_FAILURE, err_msg, opportunity.buy_exchange, "error", opportunity.pair)
                    await self._increment_failure_count(opportunity.buy_exchange, opportunity.pair)
                    return # Stop if buy order fails

                logger.info(f"Executing LIVE SELL on {opportunity.sell_exchange} for {tradable_base_amount} {base_currency} of {opportunity.pair} at ~{opportunity.sell_price}")
                sell_order = await exchange_manager.create_order(
                    exchange_id=opportunity.sell_exchange,
                    pair=opportunity.pair,
                    order_type=OrderType.LIMIT,
                    side=OrderSide.SELL,
                    amount=tradable_base_amount,
                    price=opportunity.sell_price
                )
                if sell_order and sell_order.get("id"):
                    sell_order_id = sell_order["id"]
                    sell_trade_status = OrderStatus.OPEN
                    actual_sell_price = float(sell_order.get("price", opportunity.sell_price))
                    sell_fee_cost = float(sell_order.get("fee", {}).get("cost", 0.0))
                    logger.info(f"Live SELL order placed: {sell_order_id} on {opportunity.sell_exchange}")
                    # TODO: Add logic to monitor order status
                else:
                    err_msg = f"Failed to place SELL order on {opportunity.sell_exchange} for {opportunity.pair}. Order: {sell_order}"
                    logger.error(err_msg)
                    await self._add_alert(AlertType.TRADE_FAILURE, err_msg, opportunity.sell_exchange, "error", opportunity.pair)
                    await self._increment_failure_count(opportunity.sell_exchange, opportunity.pair)
                    # TODO: Consider what to do with the bought assets if sell fails. Market sell? Hold?
                    return # Stop if sell order fails

            # Calculate profit
            cost = tradable_base_amount * actual_buy_price + buy_fee_cost
            revenue = tradable_base_amount * actual_sell_price - sell_fee_cost
            profit_quote = revenue - cost
            profit_percentage_actual = (profit_quote / cost) * 100 if cost > 0 else 0

            arbitrage_trade = ArbitrageTrade(
                id=str(uuid.uuid4()),
                opportunity_id=opportunity.id,
                pair=opportunity.pair,
                buy_trade=Trade(
                    exchange=opportunity.buy_exchange,
                    order_id=buy_order_id,
                    pair=opportunity.pair,
                    side=OrderSide.BUY,
                    price=actual_buy_price,
                    amount_base=tradable_base_amount,
                    amount_quote=tradable_base_amount * actual_buy_price,
                    fee_cost=buy_fee_cost,
                    fee_currency=quote_currency, # Assuming fees are in quote for simplicity
                    status=buy_trade_status,
                    timestamp=trade_timestamp
                ),
                sell_trade=Trade(
                    exchange=opportunity.sell_exchange,
                    order_id=sell_order_id,
                    pair=opportunity.pair,
                    side=OrderSide.SELL,
                    price=actual_sell_price,
                    amount_base=tradable_base_amount,
                    amount_quote=tradable_base_amount * actual_sell_price,
                    fee_cost=sell_fee_cost,
                    fee_currency=quote_currency,
                    status=sell_trade_status,
                    timestamp=trade_timestamp
                ),
                profit_quote=profit_quote,
                profit_percentage=profit_percentage_actual,
                timestamp=trade_timestamp,
                is_test_trade=is_test
            )
            self.trades.insert(0, arbitrage_trade)
            if len(self.trades) > settings.MAX_RECENT_TRADES_TO_STORE:
                self.trades.pop()
            
            if not is_test:
                self.live_total_trades += 1
                self.live_total_profit += profit_quote
                # Update historical high balance for failsafe
                current_total_usdt = await self._get_total_portfolio_value_usdt()
                if current_total_usdt > self._failsafe_status_internal.historical_high_balance_usdt:
                    self._failsafe_status_internal.historical_high_balance_usdt = current_total_usdt
            
            logger.info(f"Arbitrage {'simulated' if is_test else 'executed'}: {arbitrage_trade}")
            await self._add_alert(AlertType.TRADE_SUCCESS if not is_test else AlertType.TEST_TRADE_SUCCESS, 
                                f"Arbitrage {'simulated' if is_test else 'executed'} for {opportunity.pair}. Profit: {profit_quote:.2f} {quote_currency} ({profit_percentage_actual:.2f}%)", 
                                "global", "info", opportunity.pair)
            await self._broadcast_bot_status() # Send updated trades and potentially balances

        except Exception as e:
            logger.error(f"Error during arbitrage execution for {opportunity.pair}: {e}", exc_info=True)
            await self._add_alert(AlertType.TRADE_FAILURE, f"Execution error for {opportunity.pair}: {e}", "global", "critical", opportunity.pair)
            await self._increment_failure_count(opportunity.buy_exchange, opportunity.pair)
            await self._increment_failure_count(opportunity.sell_exchange, opportunity.pair)

    async def _get_total_portfolio_value_usdt(self) -> float:
        total_value = 0.0
        balances_by_exchange = await exchange_manager.get_all_balances()
        if not balances_by_exchange:
            return 0.0

        # Use a consistent price source, e.g., the first connected exchange or a preferred one
        price_source_ex = list(exchange_manager.exchanges.keys())[0] if exchange_manager.exchanges else None
        if not price_source_ex:
            logger.warning("Cannot calculate total portfolio value: No connected exchange for price fetching.")
            return 0.0 # Or raise an error

        for exchange_id, balances in balances_by_exchange.items():
            if not balances: continue
            for asset, balance_info in balances.items():
                asset_total = balance_info.get("total", 0.0)
                if asset_total > 0:
                    if asset == "USDT":
                        total_value += asset_total
                    else:
                        try:
                            pair = f"{asset}/USDT"
                            if pair in settings.USER_DEFINED_PAIRS: # Only convert if it's a traded pair
                                ticker = await exchange_manager.fetch_ticker(price_source_ex, pair)
                                if ticker and ticker.get("last") and ticker["last"] > 0:
                                    total_value += asset_total * ticker["last"]
                                else:
                                    logger.warning(f"Could not fetch USDT price for {asset} on {price_source_ex} to calculate total portfolio value.")
                            # else: asset is not part of a USDT pair we trade, so we might ignore it or handle differently
                        except Exception as e:
                            logger.error(f"Error fetching price for {asset}/USDT on {price_source_ex} for portfolio valuation: {e}")
        return total_value

    async def _check_failsafes(self):
        # Check for excessive losses (global failsafe)
        if self.current_mode == "live" and self._failsafe_status_internal.historical_high_balance_usdt > 0:
            current_total_usdt = await self._get_total_portfolio_value_usdt()
            loss_percentage = ((self._failsafe_status_internal.historical_high_balance_usdt - current_total_usdt) / 
                               self._failsafe_status_internal.historical_high_balance_usdt) * 100
            if loss_percentage > settings.FAILSAFE_MAX_GLOBAL_LOSS_PERCENTAGE:
                reason = f"Global portfolio value dropped by {loss_percentage:.2f}%, exceeding threshold of {settings.FAILSAFE_MAX_GLOBAL_LOSS_PERCENTAGE}%."
                await self._trigger_global_halt(reason)
                return # Halt immediately

        # Check for repeated pair/exchange failures
        for entity_key, count in list(self._failsafe_status_internal.pair_failure_counts.items()):
            if count >= settings.FAILSAFE_MAX_FAILURES_PER_PAIR_WINDOW:
                if not self._is_pair_disabled(entity_key):
                    await self._disable_entity("pair", entity_key, f"Exceeded {settings.FAILSAFE_MAX_FAILURES_PER_PAIR_WINDOW} failures.")
        
        for entity_key, count in list(self._failsafe_status_internal.exchange_failure_counts.items()):
            if count >= settings.FAILSAFE_MAX_FAILURES_PER_EXCHANGE_WINDOW:
                if not self._is_exchange_disabled(entity_key):
                    await self._disable_entity("exchange", entity_key, f"Exceeded {settings.FAILSAFE_MAX_FAILURES_PER_EXCHANGE_WINDOW} failures.")

    async def _increment_failure_count(self, exchange_id: str, pair: str):
        # Increment for specific pair on specific exchange (could be too granular, consider just pair or just exchange)
        pair_key = f"{exchange_id}:{pair}" # Example key, could be just pair
        self._failsafe_status_internal.pair_failure_counts[pair_key] = self._failsafe_status_internal.pair_failure_counts.get(pair_key, 0) + 1
        self._failsafe_status_internal.exchange_failure_counts[exchange_id] = self._failsafe_status_internal.exchange_failure_counts.get(exchange_id, 0) + 1
        logger.warning(f"Failure count incremented for pair {pair_key} (now {self._failsafe_status_internal.pair_failure_counts[pair_key]}) and exchange {exchange_id} (now {self._failsafe_status_internal.exchange_failure_counts[exchange_id]}).")
        await self._check_failsafes() # Check if threshold breached
        await self._broadcast_failsafe_status()

    async def _disable_entity(self, entity_type: str, entity_id: str, reason: str):
        timestamp = datetime.now(timezone.utc)
        if entity_type == "pair":
            self._failsafe_status_internal.disabled_pairs[entity_id] = {"reason": reason, "timestamp": timestamp.isoformat()}
            msg = f"Failsafe: Trading disabled for pair {entity_id}. Reason: {reason}"
        elif entity_type == "exchange":
            self._failsafe_status_internal.disabled_exchanges[entity_id] = {"reason": reason, "timestamp": timestamp.isoformat()}
            msg = f"Failsafe: Trading disabled for exchange {entity_id}. Reason: {reason}"
        else:
            return
        logger.warning(msg)
        await self._add_alert(AlertType.FAILSAFE_TRIGGERED, msg, entity_id if entity_type == "exchange" else "global", "warning", entity_id if entity_type == "pair" else None)
        await self._broadcast_failsafe_status()

    async def _trigger_global_halt(self, reason: str):
        if not self._failsafe_status_internal.global_trading_halt:
            self._failsafe_status_internal.global_trading_halt = True
            self._failsafe_status_internal.global_halt_reason = reason
            self._failsafe_status_internal.global_halt_timestamp = datetime.now(timezone.utc).isoformat()
            msg = f"GLOBAL TRADING HALT ACTIVATED. Reason: {reason}"
            logger.critical(msg)
            await self._add_alert(AlertType.FAILSAFE_TRIGGERED, msg, "global", "critical")
            await self._broadcast_failsafe_status()
            # Potentially cancel all open orders here if in live mode
            if self.current_mode == "live":
                logger.info("Attempting to cancel all open orders due to global halt.")
                # await exchange_manager.cancel_all_open_orders_all_exchanges() # Needs implementation in ExchangeManager

    async def _check_global_halt_recovery(self):
        # Placeholder for logic to check if global halt condition is resolved
        # For now, requires manual reactivation
        pass

    async def reactivate_failsafe_entity(self, entity_type: str, entity_id: Optional[str] = None) -> Tuple[bool, str]:
        if entity_type == "global" and self._failsafe_status_internal.global_trading_halt:
            self._failsafe_status_internal.global_trading_halt = False
            self._failsafe_status_internal.global_halt_reason = None
            self._failsafe_status_internal.global_halt_timestamp = None
            msg = "Global trading halt manually deactivated."
            logger.info(msg)
            await self._add_alert(AlertType.FAILSAFE_DEACTIVATED, msg, "global", "info")
        elif entity_type == "pair" and entity_id and entity_id in self._failsafe_status_internal.disabled_pairs:
            del self._failsafe_status_internal.disabled_pairs[entity_id]
            self._failsafe_status_internal.pair_failure_counts.pop(entity_id, None) # Reset failure count
            msg = f"Trading for pair {entity_id} manually reactivated."
            logger.info(msg)
            await self._add_alert(AlertType.FAILSAFE_DEACTIVATED, msg, "global", "info", entity_id)
        elif entity_type == "exchange" and entity_id and entity_id in self._failsafe_status_internal.disabled_exchanges:
            del self._failsafe_status_internal.disabled_exchanges[entity_id]
            self._failsafe_status_internal.exchange_failure_counts.pop(entity_id, None) # Reset failure count
            msg = f"Trading on exchange {entity_id} manually reactivated."
            logger.info(msg)
            await self._add_alert(AlertType.FAILSAFE_DEACTIVATED, msg, entity_id, "info")
        else:
            return False, f"No active failsafe found for {entity_type} {entity_id or ''} or invalid type."
        
        await self._broadcast_failsafe_status()
        return True, msg

    def _is_pair_disabled(self, pair_id: str) -> bool:
        # Check specific pair and also if any of its exchanges are disabled
        if pair_id in self._failsafe_status_internal.disabled_pairs:
            return True
        # This check might be too broad if pair_id is like "BTC/USDT" and disabled_exchanges contains "kraken:BTC/USDT"
        # For now, assume pair_id is just the symbol like "BTC/USDT"
        # A more robust check would parse exchanges from the pair if needed, or check if the opportunity involves a disabled exchange.
        return False # Simplified for now, specific exchange check is done in _find_opportunities

    def _is_exchange_disabled(self, exchange_id: str) -> bool:
        return exchange_id in self._failsafe_status_internal.disabled_exchanges

    async def _add_alert(self, type: AlertType, message: str, entity: str, level: str, pair: Optional[str] = None):
        alert = AlertMessage(type=type, message=message, entity=entity, level=level, pair=pair, timestamp=datetime.now(timezone.utc))
        self.alerts.insert(0, alert)
        if len(self.alerts) > settings.MAX_RECENT_ALERTS_TO_STORE:
            self.alerts.pop()
        # TODO: Implement WebSocket broadcast for alerts
        logger.info(f"ALERT ({level.upper()}): {message} (Entity: {entity}, Pair: {pair or 'N/A'})")
        await self._broadcast_bot_status() # Alerts are part of bot status

    async def _broadcast_bot_status(self):
        from .main import manager # Local import to avoid circular dependency
        status_payload = await self.get_full_bot_status()
        await manager.broadcast_bot_status(status_payload)

    async def _broadcast_failsafe_status(self):
        from .main import manager # Local import
        failsafe_data = await self.get_failsafe_status()
        await manager.broadcast_message(FailsafeStatusUpdate(type="failsafe_status", data=failsafe_data).model_dump_json())

    async def get_full_bot_status(self) -> BotStatusUpdate:
        exchange_statuses: List[ExchangeConnectionStatus] = []
        exchange_balances_list: List[ExchangeBalanceUpdate] = []

        if self.is_actively_simulating_test_mode:
            # For test mode, use self.test_balances
            for ex_id, balances_data in self.test_balances.items():
                # Assume connected if it has balances for test mode
                exchange_statuses.append(ExchangeConnectionStatus(exchange=ex_id, connected=True, message="Connected (Test Mode)"))
                exchange_balances_list.append(ExchangeBalanceUpdate(exchange=ex_id, balances=balances_data, error=None))
        else:
            # For live mode, use exchange_manager
            connected_exchanges_map = exchange_manager.get_connected_exchanges_status()
            for ex_id, status_info in connected_exchanges_map.items():
                exchange_statuses.append(ExchangeConnectionStatus(exchange=ex_id, connected=status_info["connected"], message=status_info["message"])) 
            
            live_balances = await exchange_manager.get_all_balances()
            for ex_id, balances_data in live_balances.items():
                error_msg = exchange_manager.get_exchange_error(ex_id)
                exchange_balances_list.append(ExchangeBalanceUpdate(exchange=ex_id, balances=balances_data if balances_data else {}, error=error_msg))

        return BotStatusUpdate(
            is_running=self.running,
            current_mode=self.current_mode,
            connected_exchanges=[ex.exchange for ex in exchange_statuses if ex.connected], # From actual status
            supported_exchanges=exchange_manager.get_supported_exchanges(),
            user_defined_pairs=settings.USER_DEFINED_PAIRS,
            recent_trades=await self.get_recent_trades(limit=settings.MAX_RECENT_TRADES_TO_DISPLAY, is_test_trade=self.is_test_mode or None),
            recent_opportunities=await self.get_recent_opportunities(limit=10),
            alerts=await self.get_alerts(limit=10),
            failsafe_status=await self.get_failsafe_status(),
            exchange_balances=exchange_balances_list,
            test_simulation_status=await self.get_test_simulation_status(),
            live_total_trades=self.live_total_trades,
            live_total_profit=self.live_total_profit,
            timestamp=datetime.now(timezone.utc).isoformat()
        )

arbitrage_bot = ArbitrageBot()

