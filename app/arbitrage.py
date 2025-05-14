import asyncio
import time
import uuid
import traceback
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta, timezone # Added timezone
from .models import (
    ArbitrageOpportunity, ArbitrageTrade, Trade, OrderBook, AlertType, 
    FailsafeStatus, FailsafeStatusData, OrderBookEntry, ExchangeBalanceUpdate, BotStatusUpdate, 
    TestSimulationStatusPayload, FailsafeStatusUpdate, AlertMessage, 
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
        self.current_mode: str = "idle" 
        self._main_loop_task: Optional[asyncio.Task] = None
        self.opportunities: List[ArbitrageOpportunity] = []
        self.trades: List[ArbitrageTrade] = []
        self.test_balances: Dict[str, Dict[str, Dict[str, float]]] = {}
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
        self.max_trade_amount_quote = 750.0
        self.current_test_settings: Optional[TestModeSettings] = None
        self.test_simulation_active_since: Optional[datetime] = None
        self.test_simulation_error_message: Optional[str] = None # Added for detailed test errors
        self.live_total_trades = 0
        self.live_total_profit = 0.0
        logger.info(f"ArbitrageBot initialized. Default buffer: {self.buffer_percentage*100:.4f}%, Max trade leg: ${self.max_trade_amount_quote}")

    @property
    def is_running(self) -> bool:
        return self.running

    @property
    def is_test_mode(self) -> bool:
        # Considers test_simulating as the active test mode
        return self.current_mode == "test_simulating"

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
        message_str = "Test simulation is not active."
        if self.current_mode == "test_simulating" and self.running:
            status_str = "RUNNING"
            message_str = "Test simulation is active."
        elif self.current_mode == "test_idle" and not self.running: # After stopping a test
             status_str = "IDLE"
             message_str = "Test simulation stopped."
        elif self.test_simulation_error_message:
            status_str = "ERROR"
            message_str = self.test_simulation_error_message
        
        return TestSimulationStatusPayload(
            status=status_str,
            message=message_str,
            active_since=self.test_simulation_active_since.isoformat() if self.test_simulation_active_since and status_str == "RUNNING" else None,
            total_test_trades=len([t for t in self.trades if t.is_test_trade]),
            total_test_profit=sum(t.profit_quote for t in self.trades if t.is_test_trade),
            error_message=self.test_simulation_error_message if status_str == "ERROR" else None # Ensure error message is part of payload
        )

    async def start(self, mode: str, test_settings_data: Optional[Dict] = None) -> Tuple[bool, str]:
        logger.info(f"Attempting to start bot. Current state: running={self.running}, mode={self.current_mode}. Requested mode: {mode}")
        self.test_simulation_error_message = None # Clear previous errors
        
        if self.running:
            logger.info("Bot is already running. Stopping first to ensure clean start.")
            await self.stop() # stop() will also clear test_simulation_error_message

        if mode == "live":
            self.current_mode = "live"
            self.current_test_settings = None
            self.buffer_percentage = settings.BUFFER_PERCENTAGE
            logger.info(f"Live Mode: Using buffer percentage: {self.buffer_percentage*100:.4f}%")
        elif mode == "test" and test_settings_data:
            logger.info(f"Attempting to start Test Mode with settings: {test_settings_data}")
            try:
                self.current_test_settings = TestModeSettings(**test_settings_data)
                logger.info(f"TestModeSettings parsed successfully: {self.current_test_settings}")
            except Exception as e:
                error_detail = f"Invalid test settings provided: {e}. Data: {test_settings_data}"
                logger.error(error_detail, exc_info=True)
                self.test_simulation_error_message = error_detail
                self.current_mode = "test_idle" # Or just "idle"
                return False, error_detail
            
            self.current_mode = "test_simulating" # Tentatively set mode
            logger.info(f"Initializing test balances with settings: {self.current_test_settings}")
            init_success, init_msg = await self._initialize_test_balances(self.current_test_settings)
            if not init_success:
                logger.error(f"Failed to initialize test balances: {init_msg}")
                self.test_simulation_error_message = f"Failed to initialize test balances: {init_msg}"
                self.current_mode = "test_idle" # Revert mode if init fails
                return False, self.test_simulation_error_message
            
            if self.current_test_settings.buffer_percentage is not None:
                self.buffer_percentage = self.current_test_settings.buffer_percentage / 100.0 
            else:
                self.buffer_percentage = settings.BUFFER_PERCENTAGE
            logger.info(f"Test Mode: Buffer percentage set to {self.buffer_percentage*100:.4f}%")
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
            # Ensure error messages are cleared if it was in a test error state but not running
            if self.current_mode in ["test_simulating", "test_idle"] and self.test_simulation_error_message:
                self.test_simulation_error_message = None
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
            # Do not clear test_simulation_error_message here, let get_status reflect it until next start attempt

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
        if exchange_manager.exchanges:
            # Try to find a connected exchange that is also in the test_settings.exchanges list if provided
            if test_settings.exchanges:
                for ex_id in test_settings.exchanges:
                    if ex_id in exchange_manager.exchanges:
                        price_source_exchange = ex_id
                        break
            if not price_source_exchange: # Fallback to any connected exchange
                 price_source_exchange = list(exchange_manager.exchanges.keys())[0]
        
        if not price_source_exchange and asset_capital_usd_per_pair > 0:
            msg = "Cannot initialize asset balances in USD without at least one connected exchange (from test settings or globally) to fetch prices."
            logger.error(msg)
            await self._add_alert(AlertType.SYSTEM_ERROR, msg, "global", "error")
            return False, msg

        for exchange_id in exchanges_to_init:
            if exchange_id not in exchange_manager.exchanges and asset_capital_usd_per_pair > 0:
                logger.warning(f"Exchange {exchange_id} specified in test settings is not connected. Skipping asset initialization for it if it was the price source, or if it needs prices.")
                # If this was the only price source, we might have an issue.
                if price_source_exchange == exchange_id and not any(ex in exchange_manager.exchanges for ex in exchanges_to_init if ex != exchange_id):
                    msg = f"Price source exchange {exchange_id} for test balance init is not connected."
                    logger.error(msg)
                    return False, msg
            
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
                            await self._add_alert(AlertType.DATA_FETCH_ERROR, f"Price source {price_source_exchange} disconnected during test init for {pair_str}.", exchange_id, "error")
                            # Potentially return False here if this is critical
                            # return False, f"Price source {price_source_exchange} disconnected."
                            asset_quantity = 0.0 # Default to 0 if price source fails mid-init
                        else:
                            try:
                                # Assuming fetch_ticker is part of exchange_manager
                                if not hasattr(exchange_manager, "fetch_ticker"):
                                    logger.error("ExchangeManager does not have fetch_ticker method!")
                                    raise NotImplementedError("fetch_ticker not implemented in ExchangeManager")
                                
                                ticker = await exchange_manager.fetch_ticker(price_source_exchange, pair_str)
                                if ticker and ticker.get("last") and ticker["last"] > 0:
                                    asset_quantity = asset_capital_usd_per_pair / ticker["last"]
                                    logger.info(f"For {pair_str} on {exchange_id}, ${asset_capital_usd_per_pair} at price {ticker[\"last\"]} = {asset_quantity:.8f} {base_currency}")
                                else:
                                    logger.warning(f"Could not fetch valid price for {pair_str} on {price_source_exchange}. Defaulting {base_currency} to 0 units for {exchange_id}.")
                                    await self._add_alert(AlertType.DATA_FETCH_ERROR, f"Could not fetch price for {pair_str} on {price_source_exchange} for test balance init.", exchange_id, "warning")
                            except Exception as e:
                                logger.error(f"Error fetching price for {pair_str} on {price_source_exchange} for test balance init: {e}. Defaulting {base_currency} to 0 units for {exchange_id}.")
                                await self._add_alert(AlertType.DATA_FETCH_ERROR, f"Error fetching price for {pair_str} on {price_source_exchange}: {e}", exchange_id, "error")
                    
                    self.test_balances[exchange_id][base_currency] = {
                        "free": float(asset_quantity),
                        "used": 0.0,
                        "total": float(asset_quantity)
                    }
        logger.info(f"Test balances initialized. Example for {exchanges_to_init[0] if exchanges_to_init else \"N/A\"}: {self.test_balances.get(exchanges_to_init[0] if exchanges_to_init else None)}")
        return True, "Test balances initialized successfully."

    async def _get_balance(self, exchange_id: str, currency: str) -> float:
        if self.is_test_mode:
            return self.test_balances.get(exchange_id, {}).get(currency, {}).get("free", 0.0)
        else:
            # Assuming exchange_manager.get_balance returns a Balance object or None
            bal_obj = exchange_manager.exchange_balances.get(exchange_id)
            if bal_obj and not bal_obj.error and currency in bal_obj.balances:
                return bal_obj.balances[currency].free
            return 0.0

    async def _update_test_balance(self, exchange_id: str, currency: str, amount_change: float):
        if not self.is_test_mode: return
        
        if exchange_id not in self.test_balances or currency not in self.test_balances[exchange_id]:
            logger.warning(f"Attempted to update non-existent test balance: {exchange_id}, {currency}. Initializing to 0.")
            if exchange_id not in self.test_balances: self.test_balances[exchange_id] = {}
            if currency not in self.test_balances[exchange_id]: 
                self.test_balances[exchange_id][currency] = {"free": 0.0, "used": 0.0, "total": 0.0}

        current_balance = self.test_balances[exchange_id][currency]
        current_balance["free"] += amount_change
        current_balance["total"] += amount_change 
        
        if current_balance["free"] < -1e-9: # Allow for small floating point inaccuracies
            logger.error(f"Test balance for {currency} on {exchange_id} went negative: {current_balance[\"free\"]}. Clamping to 0.")
            await self._add_alert(AlertType.TRADING_ERROR, f"Test balance for {currency} on {exchange_id} went negative ({current_balance[\"free\"]:.8f}). Check logic.", exchange_id, "error")
            current_balance["free"] = 0.0 
            # Total should reflect the actual sum of free and used.
            # If used is 0, total becomes 0. If used is positive, total becomes used.
            current_balance["total"] = current_balance["used"] 

    async def _add_alert(self, alert_type: AlertType, message: str, entity_name: Optional[str] = None, severity: str = "info"):
        alert = AlertMessage(
            id=str(uuid.uuid4()), # Ensure ID for alerts
            type=alert_type.value,
            message=message,
            timestamp=datetime.now(timezone.utc).isoformat(),
            severity=severity,
            entity_name=entity_name
        )
        self.alerts.insert(0, alert)
        self.alerts = self.alerts[:settings.MAX_ALERTS_STORED]
        logger.info(f"ALERT ({severity.upper()}): [{alert_type.value}] {message} (Entity: {entity_name or \"N/A\"})")

    async def _simulate_test_trade(self, connected_exchanges: List[str]):
        """Placeholder for simulating a test trade. 
        In a real scenario, this would find an opportunity and execute it against test_balances.
        """
        if not self.is_test_mode or not self.running:
            return

        logger.info(f"TEST MODE: Attempting to simulate a trade. Iteration for trade simulation.")
        try:
            if len(connected_exchanges) < 2:
                logger.warning("TEST MODE: Need at least two connected exchanges to simulate a trade.")
                return

            # Simple example: Pick two exchanges and a pair
            buy_exchange = connected_exchanges[0]
            sell_exchange = connected_exchanges[1]
            if buy_exchange == sell_exchange: # Should not happen if len >= 2, but good check
                 logger.warning("TEST MODE: Buy and sell exchange are the same. Skipping simulation.")
                 return

            if not settings.USER_DEFINED_PAIRS:
                logger.warning("TEST MODE: No user defined pairs to simulate a trade.")
                return
            
            pair_to_trade = settings.USER_DEFINED_PAIRS[0] # Example: trade the first defined pair
            base_currency, quote_currency = pair_to_trade.split("/")

            # Simulate fetching prices (in a real scenario, these would come from order books)
            # For simplicity, assume a small positive spread to make a profit
            buy_price = 100.0 
            sell_price = 100.5 
            amount_to_trade_base = 0.1 # Trade 0.1 of base currency

            # Check balances
            buy_exchange_quote_balance = await self._get_balance(buy_exchange, quote_currency)
            sell_exchange_base_balance = await self._get_balance(sell_exchange, base_currency)

            cost_quote = amount_to_trade_base * buy_price

            if buy_exchange_quote_balance < cost_quote:
                logger.warning(f"TEST MODE: Insufficient {quote_currency} on {buy_exchange} to buy {amount_to_trade_base} {base_currency}. Has: {buy_exchange_quote_balance}, Needs: {cost_quote}")
                return
            if sell_exchange_base_balance < amount_to_trade_base:
                logger.warning(f"TEST MODE: Insufficient {base_currency} on {sell_exchange} to sell. Has: {sell_exchange_base_balance}, Needs: {amount_to_trade_base}")
                return

            # Simulate trade execution
            await self._update_test_balance(buy_exchange, quote_currency, -cost_quote)
            await self._update_test_balance(buy_exchange, base_currency, amount_to_trade_base)
            await self._update_test_balance(sell_exchange, base_currency, -amount_to_trade_base)
            await self._update_test_balance(sell_exchange, quote_currency, amount_to_trade_base * sell_price)

            profit_quote = (amount_to_trade_base * sell_price) - cost_quote
            profit_percentage = (profit_quote / cost_quote) * 100 if cost_quote > 0 else 0

            trade_entry = ArbitrageTrade(
                id=str(uuid.uuid4()),
                opportunity_id="simulated_opportunity",
                symbol=pair_to_trade,
                profit_quote=profit_quote,
                profit_percentage=profit_percentage,
                timestamp=datetime.now(timezone.utc),
                buy_trade=Trade(exchange=buy_exchange, symbol=pair_to_trade, side=OrderSide.BUY, type=OrderType.MARKET, amount=amount_to_trade_base, price=buy_price, timestamp=datetime.now(timezone.utc), fee_amount=0, fee_currency=quote_currency, status=OrderStatus.CLOSED, order_id="sim_buy_"+str(uuid.uuid4())[:8]),
                sell_trade=Trade(exchange=sell_exchange, symbol=pair_to_trade, side=OrderSide.SELL, type=OrderType.MARKET, amount=amount_to_trade_base, price=sell_price, timestamp=datetime.now(timezone.utc), fee_amount=0, fee_currency=quote_currency, status=OrderStatus.CLOSED, order_id="sim_sell_"+str(uuid.uuid4())[:8]),
                is_test_trade=True,
                status_messages=["Simulated trade executed successfully."]
            )
            self.trades.insert(0, trade_entry)
            self.trades = self.trades[:settings.MAX_TRADES_STORED]
            logger.info(f"TEST MODE: Simulated trade for {pair_to_trade} executed. Profit: {profit_quote:.4f} {quote_currency} ({profit_percentage:.4f}%)")
            await self._add_alert(AlertType.TRADE_COMPLETED, f"Simulated test trade for {pair_to_trade} completed. Profit: {profit_quote:.2f} {quote_currency}", "global", "success")
            self.test_simulation_error_message = None # Clear error on successful simulation step

        except Exception as e:
            error_msg = f"TEST MODE: Error during trade simulation: {e}"
            logger.error(error_msg, exc_info=True)
            self.test_simulation_error_message = error_msg
            await self._add_alert(AlertType.TRADING_ERROR, error_msg, "global", "error")
            # Optionally stop the simulation on error
            # await self.stop()

    async def _main_loop(self):
        logger.info(f"Main loop started. Bot running: {self.running}, Mode: {self.current_mode}")
        loop_iterations = 0
        
        while self.running:
            loop_iterations += 1
            start_time_iteration = time.perf_counter()
            try:
                if loop_iterations % 60 == 1: 
                    logger.info(f"Main loop iter: {loop_iterations}, Mode: {self.current_mode}, Opps: {len(self.opportunities)}, Trades: {len(self.trades)}, Test Err: {self.test_simulation_error_message}")
                
                connected_exchanges = list(exchange_manager.exchanges.keys())
                if len(connected_exchanges) < 2 and self.current_mode == "live": # Only enforce for live mode strictly here
                    if loop_iterations % 10 == 1: 
                        logger.warning(f"Live Mode: Insufficient exchanges connected ({len(connected_exchanges)}). Need at least 2. Skipping scan.")
                        await self._add_alert(AlertType.SYSTEM_WARNING, "Live Mode: Insufficient exchanges connected. Need at least 2.", "global", "warning")
                    await asyncio.sleep(settings.SCAN_INTERVAL_SECONDS * 2) 
                    continue
                
                if self.current_mode == "live":
                    # Placeholder for actual arbitrage scanning logic for live mode
                    # for pair in settings.USER_DEFINED_PAIRS:
                    #     if not self.running: break 
                    #     await self._scan_arbitrage_opportunities(pair, connected_exchanges)
                    pass # Replace with actual live mode logic
                
                elif self.is_test_mode: # current_mode == "test_simulating"
                    if loop_iterations % settings.TEST_MODE_TRADE_INTERVAL_ITERATIONS == 0:
                        logger.debug(f"Test mode: Triggering _simulate_test_trade. Iteration: {loop_iterations}")
                        await self._simulate_test_trade(connected_exchanges)
                    if self.test_simulation_error_message: # If simulation itself errored
                        logger.error(f"Test simulation encountered an error: {self.test_simulation_error_message}. Loop continues but simulation might be stuck.")
                        # Consider stopping test mode if error is persistent or critical
                        # await self.stop()
                        # return 

                if not self.running: break
                await asyncio.sleep(settings.SCAN_INTERVAL_SECONDS)

            except asyncio.CancelledError:
                logger.info("Main loop task cancelled.")
                break 
            except Exception as e:
                error_msg = f"Critical Error in arbitrage main loop (iter {loop_iterations}): {str(e)}"
                logger.critical(error_msg, exc_info=True)
                await self._add_alert(AlertType.SYSTEM_ERROR, error_msg, "global", "critical")
                # Decide if bot should stop on critical errors
                # self.test_simulation_error_message = error_msg # If in test mode
                # await self.stop()
                # break
                await asyncio.sleep(settings.SCAN_INTERVAL_SECONDS * 5) # Longer sleep on critical error
        
        logger.info(f"Main loop ended. Bot running: {self.running}, Mode: {self.current_mode}")

    # Placeholder for _scan_arbitrage_opportunities if it were to be implemented
    async def _scan_arbitrage_opportunities(self, pair: str, exchanges: List[str]):
        logger.debug(f"Scanning for opportunities for {pair} on {exchanges}")
        # Actual implementation would fetch order books, compare prices, calculate profit, etc.
        await asyncio.sleep(0.1) # Simulate work
        pass

    async def reactivate_failsafe(self, type: str, entity_name: Optional[str] = None) -> Tuple[bool, str]:
        logger.info(f"Attempting to reactivate failsafe for type: {type}, entity: {entity_name}")
        # Simplified reactivation logic for now
        if type == "global":
            self._failsafe_status_internal.global_trading_halt = False
            self._failsafe_status_internal.global_halt_reason = None
            msg = "Global trading halt lifted."
        elif type == "exchange" and entity_name:
            if entity_name in self._failsafe_status_internal.disabled_exchanges:
                del self._failsafe_status_internal.disabled_exchanges[entity_name]
                msg = f"Failsafe for exchange {entity_name} reactivated."
            else:
                msg = f"Exchange {entity_name} was not in failsafe."
        elif type == "pair" and entity_name:
            if entity_name in self._failsafe_status_internal.disabled_pairs:
                del self._failsafe_status_internal.disabled_pairs[entity_name]
                msg = f"Failsafe for pair {entity_name} reactivated."
            else:
                msg = f"Pair {entity_name} was not in failsafe."
        else:
            return False, "Invalid failsafe reactivation type or missing entity name."
        
        logger.info(msg)
        await self._add_alert(AlertType.FAILSAFE_REACTIVATED, msg, entity_name or "global", "warning")
        return True, msg

# Instantiate the bot for use in the application
arbitrage_bot = ArbitrageBot()

