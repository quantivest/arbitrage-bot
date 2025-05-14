import asyncio
import time
import uuid
import traceback
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
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
        # This is the internal FailsafeStatus model with all fields
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
        self.live_total_trades = 0
        self.live_total_profit = 0.0
        logger.info(f"ArbitrageBot initialized. Default buffer: {self.buffer_percentage*100:.4f}%, Max trade leg: ${self.max_trade_amount_quote}")

    @property
    def is_running(self) -> bool:
        return self.running

    @property
    def is_test_mode(self) -> bool:
        return self.current_mode == "test_simulating"

    async def get_recent_opportunities(self, limit: int = 10) -> List[ArbitrageOpportunity]:
        return self.opportunities[:limit]

    async def get_recent_trades(self, limit: int = 10, is_test_trade: Optional[bool] = None) -> List[ArbitrageTrade]:
        if is_test_trade is None:
            return self.trades[:limit]
        return [t for t in self.trades if t.is_test_trade == is_test_trade][:limit]

    async def get_alerts(self, limit: int = 10) -> List[AlertMessage]:
        return self.alerts[:limit]

    # Modified to return FailsafeStatusData as expected by BotStatusPayload
    async def get_failsafe_status(self) -> FailsafeStatusData:
        return FailsafeStatusData(
            global_trading_halt=self._failsafe_status_internal.global_trading_halt,
            global_halt_reason=self._failsafe_status_internal.global_halt_reason,
            global_halt_timestamp=self._failsafe_status_internal.global_halt_timestamp,
            disabled_exchanges=self._failsafe_status_internal.disabled_exchanges,
            disabled_pairs=self._failsafe_status_internal.disabled_pairs
        )

    async def get_test_simulation_status(self) -> TestSimulationStatusPayload:
        return TestSimulationStatusPayload(
            status="RUNNING" if self.is_test_mode and self.running else "IDLE" if not self.running else "UNKNOWN",
            message="Test simulation is active." if self.is_test_mode and self.running else "Test simulation is not active.",
            active_since=self.test_simulation_active_since.isoformat() if self.test_simulation_active_since and self.is_test_mode and self.running else None,
            total_test_trades=len([t for t in self.trades if t.is_test_trade]),
            total_test_profit=sum(t.profit_quote for t in self.trades if t.is_test_trade)
        )

    async def start(self, mode: str, test_settings_data: Optional[Dict] = None) -> Tuple[bool, str]:
        logger.info(f"Attempting to start bot. Current state: running={self.running}, mode={self.current_mode}. Requested mode: {mode}")
        
        if self.running:
            logger.info("Bot is already running. Stopping first to ensure clean start.")
            await self.stop()

        if mode == "live":
            self.current_mode = "live"
            self.current_test_settings = None
            self.buffer_percentage = settings.BUFFER_PERCENTAGE
            logger.info(f"Live Mode: Using buffer percentage: {self.buffer_percentage*100:.4f}%")
        elif mode == "test" and test_settings_data:
            try:
                self.current_test_settings = TestModeSettings(**test_settings_data)
            except Exception as e:
                logger.error(f"Invalid test settings provided: {e}. Data: {test_settings_data}", exc_info=True)
                return False, f"Invalid test settings: {e}"
            
            self.current_mode = "test_simulating"
            logger.info(f"Initializing test balances with settings: {self.current_test_settings}")
            init_success, init_msg = await self._initialize_test_balances(self.current_test_settings)
            if not init_success:
                self.current_mode = "idle"
                return False, init_msg
            
            if self.current_test_settings.buffer_percentage is not None:
                self.buffer_percentage = self.current_test_settings.buffer_percentage / 100.0 
            else:
                self.buffer_percentage = settings.BUFFER_PERCENTAGE
            logger.info(f"Test Mode: Buffer percentage set to {self.buffer_percentage*100:.4f}%")
            self.test_simulation_active_since = datetime.utcnow()
        else:
            return False, "Invalid mode or missing test settings for test mode."

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
            return True, "Bot was not running."

        self.running = False 
        current_mode_before_stop = self.current_mode
        self.current_mode = "idle"

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
        if exchange_manager.exchanges:
            price_source_exchange = list(exchange_manager.exchanges.keys())[0]
        
        if not price_source_exchange and asset_capital_usd_per_pair > 0:
            msg = "Cannot initialize asset balances in USD without at least one connected exchange to fetch prices."
            logger.error(msg)
            await self._add_alert(AlertType.SYSTEM_ERROR, msg, "global")
            return False, msg

        for exchange_id in exchanges_to_init:
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
                        try:
                            ticker = await exchange_manager.fetch_ticker(price_source_exchange, pair_str)
                            if ticker and ticker.get("last") and ticker["last"] > 0:
                                asset_quantity = asset_capital_usd_per_pair / ticker["last"]
                                # Corrected f-string syntax below
                                logger.info(f"For {pair_str} on {exchange_id}, ${asset_capital_usd_per_pair} at price {ticker['last']} = {asset_quantity:.8f} {base_currency}")
                            else:
                                logger.warning(f"Could not fetch valid price for {pair_str} on {price_source_exchange}. Defaulting {base_currency} to 0 units for {exchange_id}.")
                                await self._add_alert(AlertType.DATA_FETCH_ERROR, f"Could not fetch price for {pair_str} on {price_source_exchange} for test balance init.", exchange_id)
                        except Exception as e:
                            logger.error(f"Error fetching price for {pair_str} on {price_source_exchange} for test balance init: {e}. Defaulting {base_currency} to 0 units for {exchange_id}.")
                            await self._add_alert(AlertType.DATA_FETCH_ERROR, f"Error fetching price for {pair_str} on {price_source_exchange}: {e}", exchange_id)
                    
                    self.test_balances[exchange_id][base_currency] = {
                        "free": float(asset_quantity),
                        "used": 0.0,
                        "total": float(asset_quantity)
                    }
        logger.info(f"Test balances initialized. Example for {exchanges_to_init[0] if exchanges_to_init else 'N/A'}: {self.test_balances.get(exchanges_to_init[0] if exchanges_to_init else None)}")
        return True, "Test balances initialized successfully."

    async def _get_balance(self, exchange_id: str, currency: str) -> float:
        if self.is_test_mode:
            return self.test_balances.get(exchange_id, {}).get(currency, {}).get("free", 0.0)
        else:
            bal = exchange_manager.get_balance(exchange_id, currency)
            return bal.free if bal else 0.0

    async def _update_test_balance(self, exchange_id: str, currency: str, amount_change: float):
        if not self.is_test_mode: return
        
        if exchange_id not in self.test_balances or currency not in self.test_balances[exchange_id]:
            logger.warning(f"Attempted to update non-existent test balance: {exchange_id}, {currency}")
            if exchange_id not in self.test_balances: self.test_balances[exchange_id] = {}
            if currency not in self.test_balances[exchange_id]: 
                self.test_balances[exchange_id][currency] = {"free": 0.0, "used": 0.0, "total": 0.0}

        current_balance = self.test_balances[exchange_id][currency]
        current_balance["free"] += amount_change
        current_balance["total"] += amount_change 
        
        if current_balance["free"] < 0:
            logger.error(f"Test balance for {currency} on {exchange_id} went negative: {current_balance['free']}. Clamping to 0.")
            await self._add_alert(AlertType.TRADING_ERROR, f"Test balance for {currency} on {exchange_id} went negative. Check logic.", exchange_id)
            current_balance["free"] = 0.0 
            current_balance["total"] = current_balance["used"] 

    async def _add_alert(self, alert_type: AlertType, message: str, entity_name: Optional[str] = None, severity: str = "info"):
        alert = AlertMessage(
            type=alert_type.value,
            message=message,
            timestamp=datetime.utcnow().isoformat(), # Ensure ISO format for AlertMessage
            severity=severity,
            entity_name=entity_name
        )
        self.alerts.insert(0, alert)
        self.alerts = self.alerts[:settings.MAX_ALERTS_STORED]
        logger.info(f"ALERT ({severity.upper()}): [{alert_type.value}] {message} (Entity: {entity_name or 'N/A'})")

    async def _main_loop(self):
        logger.info(f"Main loop started. Bot running: {self.running}, Mode: {self.current_mode}")
        loop_iterations = 0
        
        while self.running:
            loop_iterations += 1
            start_time_iteration = time.perf_counter()
            try:
                if loop_iterations % 60 == 1: 
                    logger.info(f"Main loop iter: {loop_iterations}, Mode: {self.current_mode}, Opps: {len(self.opportunities)}, Trades: {len(self.trades)}")
                
                connected_exchanges = list(exchange_manager.exchanges.keys())
                if len(connected_exchanges) < 2:
                    if loop_iterations % 10 == 1: 
                        logger.warning(f"Insufficient exchanges connected ({len(connected_exchanges)}). Need at least 2. Skipping scan.")
                        await self._add_alert(AlertType.SYSTEM_WARNING, "Insufficient exchanges connected. Need at least 2.", "global", "warning")
                    await asyncio.sleep(settings.SCAN_INTERVAL_SECONDS * 2) 
                    continue
                
                # Placeholder for actual arbitrage scanning logic
                # for pair in settings.USER_DEFINED_PAIRS:
                #     if not self.running: break 
                #     await self._scan_arbitrage_opportunities(pair, connected_exchanges)
                
                if not self.running: break
                if self.is_test_mode and loop_iterations % settings.TEST_MODE_TRADE_INTERVAL_ITERATIONS == 0:
                    await self._simulate_test_trade(connected_exchanges)

                await asyncio.sleep(settings.SCAN_INTERVAL_SECONDS)

            except asyncio.CancelledError:
                logger.info("Main loop task cancelled.")
                break 
            except Exception as e:
                error_msg = f"Critical Error in arbitrage main loop (iter {loop_iterations}): {str(e)}"
                logger.critical(error_msg, exc_info=True)
                await self._add_alert(AlertType.CRITICAL_ERROR, error_msg, "global", "critical")
                await asyncio.sleep(5) # Avoid rapid crash loop
        
        logger.info("Main loop ended.")

    async def _simulate_test_trade(self, exchanges: List[str]):
        if len(exchanges) < 2 or not settings.USER_DEFINED_PAIRS:
            return

        # Pick a random pair and exchanges for simulation
        pair_to_trade = settings.USER_DEFINED_PAIRS[0] # Simplistic: always use the first pair
        buy_exchange_id = exchanges[0]
        sell_exchange_id = exchanges[1]
        base_currency, quote_currency = pair_to_trade.split("/")

        # Simulate some prices
        buy_price = 50000.0 + (time.time() % 100) # Dynamic price for simulation
        sell_price = buy_price * 1.001 # Simulate a 0.1% profit opportunity

        # Simulate a trade amount (e.g., 0.001 of base currency)
        trade_amount_base = 0.001
        buy_cost_quote = trade_amount_base * buy_price
        sell_proceeds_quote = trade_amount_base * sell_price

        # Check if balances are sufficient (simplified)
        if await self._get_balance(buy_exchange_id, quote_currency) < buy_cost_quote:
            logger.warning(f"Test Trade Sim: Insufficient {quote_currency} on {buy_exchange_id} to buy {trade_amount_base} {base_currency}.")
            return
        if await self._get_balance(sell_exchange_id, base_currency) < trade_amount_base:
            logger.warning(f"Test Trade Sim: Insufficient {base_currency} on {sell_exchange_id} to sell.")
            return

        # Simulate trade execution and update test balances
        await self._update_test_balance(buy_exchange_id, quote_currency, -buy_cost_quote)
        await self._update_test_balance(buy_exchange_id, base_currency, trade_amount_base)
        await self._update_test_balance(sell_exchange_id, base_currency, -trade_amount_base)
        await self._update_test_balance(sell_exchange_id, quote_currency, sell_proceeds_quote)

        # Record the simulated arbitrage trade
        trade_id = str(uuid.uuid4())
        buy_trade_details = {
            "id": f"buy-{trade_id[:8]}", "exchange": buy_exchange_id, "symbol": pair_to_trade, 
            "side": "buy", "amount": trade_amount_base, "price": buy_price, 
            "cost": buy_cost_quote, "fee_amount": buy_cost_quote * 0.001, "fee_currency": quote_currency, 
            "timestamp": datetime.utcnow(), "status": "filled"
        }
        sell_trade_details = {
            "id": f"sell-{trade_id[:8]}", "exchange": sell_exchange_id, "symbol": pair_to_trade, 
            "side": "sell", "amount": trade_amount_base, "price": sell_price, 
            "cost": sell_proceeds_quote, "fee_amount": sell_proceeds_quote * 0.001, "fee_currency": quote_currency, 
            "timestamp": datetime.utcnow(), "status": "filled"
        }
        
        profit = (sell_proceeds_quote - sell_trade_details['fee_amount']) - (buy_cost_quote + buy_trade_details['fee_amount'])
        profit_percentage = (profit / buy_cost_quote) * 100 if buy_cost_quote > 0 else 0

        arbitrage_trade_entry = ArbitrageTrade(
            id=trade_id,
            buy_trade=buy_trade_details,
            sell_trade=sell_trade_details,
            symbol=pair_to_trade,
            profit_quote=profit,
            profit_percentage=profit_percentage,
            is_test_trade=True,
            status="completed"
        )
        self.trades.insert(0, arbitrage_trade_entry)
        self.trades = self.trades[:100] # Keep last 100 trades
        logger.info(f"Test Trade Sim: Executed for {pair_to_trade}. Buy {buy_exchange_id} @ {buy_price}, Sell {sell_exchange_id} @ {sell_price}. Profit: ${profit:.2f} ({profit_percentage:.4f}%)")
        await self._add_alert(AlertType.TRADE_EXECUTED, f"Simulated test trade for {pair_to_trade} executed. Profit: ${profit:.2f}", "global")

    async def reactivate_failsafe_entity(self, entity_type: str, entity_name: Optional[str] = None) -> Tuple[bool, str]:
        logger.info(f"Attempting to reactivate failsafe: type={entity_type}, entity={entity_name}")
        if entity_type == "global":
            self._failsafe_status_internal.global_trading_halt = False
            self._failsafe_status_internal.global_halt_reason = None
            self._failsafe_status_internal.global_halt_timestamp = None
            msg = "Global trading halt reactivated."
            logger.info(msg)
            await self._add_alert(AlertType.INFO, msg, "global")
            return True, msg
        elif entity_name:
            if entity_type == "pair" and entity_name in self._failsafe_status_internal.disabled_pairs:
                del self._failsafe_status_internal.disabled_pairs[entity_name]
                msg = f"Pair {entity_name} reactivated."
                logger.info(msg)
                await self._add_alert(AlertType.INFO, msg, entity_name)
                return True, msg
            elif entity_type == "exchange" and entity_name in self._failsafe_status_internal.disabled_exchanges:
                del self._failsafe_status_internal.disabled_exchanges[entity_name]
                msg = f"Exchange {entity_name} reactivated."
                logger.info(msg)
                await self._add_alert(AlertType.INFO, msg, entity_name)
                return True, msg
        msg = f"Failed to reactivate: Invalid type or entity not found/disabled. Type: {entity_type}, Entity: {entity_name}"
        logger.warning(msg)
        return False, msg

arbitrage_bot = ArbitrageBot()

