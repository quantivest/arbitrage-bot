import asyncio
import time
import uuid
import traceback
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from .models import (
    ArbitrageOpportunity, ArbitrageTrade, Trade, OrderBook, AlertType, 
    FailsafeStatus, OrderBookEntry, ExchangeBalanceUpdate, BotStatusUpdate, 
    TestSimulationStatusPayload, FailsafeStatusUpdate, AlertMessage, 
    ExchangeConnectionStatus, OrderStatus, OrderType, OrderSide, TestModeSettings # Added TestModeSettings
)
from .exchanges import exchange_manager # Assuming exchange_manager can provide ticker/price info
from .config import settings
import logging

logger = logging.getLogger(__name__)

class ArbitrageBot:
    """Spot-to-spot arbitrage bot."""
    
    def __init__(self):
        self.running = False
        self.current_mode: str = "idle" # idle, live, test_simulating
        self._main_loop_task: Optional[asyncio.Task] = None
        self.opportunities: List[ArbitrageOpportunity] = []
        self.trades: List[ArbitrageTrade] = []
        self.test_balances: Dict[str, Dict[str, Dict[str, float]]] = {}
        self.buffer_percentage = settings.BUFFER_PERCENTAGE
        self.failsafe_status = FailsafeStatus(
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
        self.websocket_queues: List[asyncio.Queue] = [] # Not used by current api.py, but kept for potential direct use
        self.current_test_settings: Optional[TestModeSettings] = None # Use the Pydantic model
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

    async def get_failsafe_status(self) -> FailsafeStatus:
        return self.failsafe_status

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
                logger.error(f"Invalid test settings provided: {e}")
                return False, f"Invalid test settings: {e}"
            self.current_mode = "test_simulating"
            logger.info(f"Initializing test balances with settings: {self.current_test_settings}")
            init_success, init_msg = await self._initialize_test_balances(self.current_test_settings)
            if not init_success:
                self.current_mode = "idle"
                return False, init_msg
            
            if self.current_test_settings.buffer_percentage is not None:
                self.buffer_percentage = self.current_test_settings.buffer_percentage / 100.0 # Assuming input is % e.g. 0.01 for 0.01%
            else:
                self.buffer_percentage = settings.BUFFER_PERCENTAGE
            logger.info(f"Test Mode: Buffer percentage set to {self.buffer_percentage*100:.4f}%")
            self.test_simulation_active_since = datetime.utcnow()
        else:
            return False, "Invalid mode or missing test settings for test mode."

        self.running = True
        self.opportunities = [] 
        # self.trades = [] # Keep trades for historical view unless explicitly reset
        # self.alerts = [] # Keep alerts

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
        asset_capital_usd_per_pair = test_settings.asset_capital_usd_per_pair # This is the USD value

        logger.info(f"Initializing test balances for exchanges: {exchanges_to_init}")
        logger.info(f"USDT capital per exchange: ${usdt_capital_per_exchange}")
        logger.info(f"USD value for each base asset (for {len(settings.USER_DEFINED_PAIRS)} pairs) per exchange: ${asset_capital_usd_per_pair}")

        # Use the first connected exchange to fetch indicative prices for conversion
        # This is a simplification; ideally, prices might vary slightly per exchange.
        # For test mode, using one exchange's prices for all is acceptable.
        price_source_exchange = None
        if exchange_manager.exchanges:
            price_source_exchange = list(exchange_manager.exchanges.keys())[0]
        
        if not price_source_exchange and asset_capital_usd_per_pair > 0:
            msg = "Cannot initialize asset balances in USD without at least one connected exchange to fetch prices."
            logger.error(msg)
            return False, msg

        for exchange_id in exchanges_to_init:
            self.test_balances[exchange_id] = {
                "USDT": {"free": float(usdt_capital_per_exchange), "used": 0.0, "total": float(usdt_capital_per_exchange)}
            }
            for pair_str in settings.USER_DEFINED_PAIRS:
                base_currency, quote_currency = pair_str.split("/")
                if quote_currency != "USDT": # Ensure we are dealing with XXX/USDT pairs for this logic
                    logger.warning(f"Skipping non-USDT pair {pair_str} for USD-based asset initialization.")
                    continue

                if base_currency not in self.test_balances[exchange_id]:
                    asset_quantity = 0.0
                    if asset_capital_usd_per_pair > 0 and price_source_exchange:
                        try:
                            # Attempt to fetch ticker for current price
                            ticker = await exchange_manager.fetch_ticker(price_source_exchange, pair_str)
                            if ticker and ticker.get("last") and ticker["last"] > 0:
                                asset_quantity = asset_capital_usd_per_pair / ticker["last"]
                            else:
                                logger.warning(f"Could not fetch valid price for {pair_str} on {price_source_exchange}. Defaulting {base_currency} to 0 units for {exchange_id}.")
                        except Exception as e:
                            logger.error(f"Error fetching price for {pair_str} on {price_source_exchange} for test balance init: {e}. Defaulting {base_currency} to 0 units for {exchange_id}.")
                    
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
            # In live mode, fetch from exchange_manager which should hold live balances
            bal = exchange_manager.get_balance(exchange_id, currency)
            return bal.free if bal else 0.0

    async def _update_test_balance(self, exchange_id: str, currency: str, amount_change: float):
        """ Amount change is positive for credit, negative for debit from 'free' """
        if not self.is_test_mode: return
        
        if exchange_id not in self.test_balances or currency not in self.test_balances[exchange_id]:
            logger.warning(f"Attempted to update non-existent test balance: {exchange_id}, {currency}")
            # Initialize if missing, though ideally it should exist
            if exchange_id not in self.test_balances: self.test_balances[exchange_id] = {}
            if currency not in self.test_balances[exchange_id]: 
                self.test_balances[exchange_id][currency] = {"free": 0.0, "used": 0.0, "total": 0.0}

        current_balance = self.test_balances[exchange_id][currency]
        current_balance["free"] += amount_change
        current_balance["total"] += amount_change # Assuming 'used' doesn't change here, or is handled separately
        
        if current_balance["free"] < 0:
            logger.error(f"Test balance for {currency} on {exchange_id} went negative: {current_balance['free']}. Clamping to 0.")
            # This indicates a flaw in trade simulation logic or insufficient funds check
            current_balance["free"] = 0.0 
            # Adjust total accordingly if free is clamped. This is a simplistic recovery.
            current_balance["total"] = current_balance["used"] # Total = Used if Free is 0

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
                        # Consider broadcasting an alert via api.py's connection_manager
                    await asyncio.sleep(settings.SCAN_INTERVAL_SECONDS * 2) # Longer sleep if not enough exchanges
                    continue
                
                # Failsafe checks and reactivations (simplified)
                # await self._check_and_reactivate_failsafes() 

                for pair in settings.USER_DEFINED_PAIRS:
                    if not self.running: break 
                    await self._scan_arbitrage_opportunities(pair, connected_exchanges)
                
                if not self.running: break
                await asyncio.sleep(settings.SCAN_INTERVAL_SECONDS)

            except asyncio.CancelledError:
                logger.info("Main loop task cancelled.")
                break # Exit loop on cancellation
            except Exception as e:
                error_msg = f"Critical Error in arbitrage main loop (iter {loop_iterations}): {str(e)}"
                logger.critical(error_msg, exc_info=True)
                # Consider broadcasting an alert
                await asyncio.sleep(10) # Cooldown after critical error
            finally:
                end_time_iteration = time.perf_counter()
                if loop_iterations % 300 == 0: # Log duration less frequently
                     logger.info(f"Main loop iteration {loop_iterations} took {end_time_iteration - start_time_iteration:.4f} seconds.")

        logger.info(f"Main loop exited. Bot running: {self.running}, Mode: {self.current_mode}")
        # Final status update handled by stop() method

    async def _scan_arbitrage_opportunities(self, pair: str, exchanges: List[str]):
        # Placeholder for actual arbitrage scanning logic
        # This would involve fetching order books, calculating potential profits, etc.
        # For now, let's simulate finding an opportunity occasionally in test mode
        if self.is_test_mode and len(exchanges) >=2 and loop_iterations % 15 == 0: # Simulate an opportunity
            try:
                buy_exchange = exchanges[0]
                sell_exchange = exchanges[1]
                base_curr, quote_curr = pair.split("/")

                # Simulate some prices
                buy_price = await exchange_manager.fetch_ticker(buy_exchange, pair).get("ask", 10000) * 0.999 # Simulate buying slightly below market ask
                sell_price = await exchange_manager.fetch_ticker(sell_exchange, pair).get("bid", 10000) * 1.001 # Simulate selling slightly above market bid
                
                if not buy_price or not sell_price or buy_price <=0 or sell_price <=0:
                    return

                profit_percentage = ((sell_price - buy_price) / buy_price) * 100 - (2 * self.buffer_percentage * 100) # Simplified fee/buffer

                if profit_percentage > settings.MIN_PROFIT_PERCENTAGE_THRESHOLD:
                    timestamp = datetime.utcnow()
                    opportunity_id = str(uuid.uuid4())
                    
                    # Simulate available balance and trade amount
                    available_usdt_buy_ex = await self._get_balance(buy_exchange, quote_curr)
                    sim_trade_amount_quote = min(available_usdt_buy_ex, self.max_trade_amount_quote, asset_capital_usd_per_pair) # Use asset_capital_usd_per_pair as a cap for test trades
                    sim_trade_amount_base = sim_trade_amount_quote / buy_price

                    if sim_trade_amount_base < settings.MIN_TRADE_AMOUNT_BASE:
                        return # Too small to trade

                    opp = ArbitrageOpportunity(
                        id=opportunity_id,
                        timestamp=timestamp,
                        pair=pair,
                        profit_percentage=profit_percentage,
                        buy_exchange=buy_exchange,
                        sell_exchange=sell_exchange,
                        buy_price=buy_price,
                        sell_price=sell_price,
                        potential_trade_volume_quote=sim_trade_amount_quote
                    )
                    self.opportunities.insert(0, opp)
                    self.opportunities = self.opportunities[:50]
                    logger.info(f"TEST MODE: Simulated opportunity found: {opp.pair} on {opp.buy_exchange} -> {opp.sell_exchange}, Profit: {opp.profit_percentage:.4f}%")
                    # await self._broadcast_to_websockets({"type": "new_opportunity", "data": opp.model_dump()})
                    await self._execute_trade(opp, sim_trade_amount_base, sim_trade_amount_quote)
            except Exception as e:
                logger.error(f"Error in test mode opportunity simulation: {e}", exc_info=True)
        pass # Actual live mode scanning would be complex

    async def _execute_trade(self, opportunity: ArbitrageOpportunity, amount_base: float, amount_quote: float):
        # Placeholder for actual trade execution (live or test)
        trade_id = str(uuid.uuid4())
        timestamp = datetime.utcnow()
        profit_usd = (opportunity.sell_price - opportunity.buy_price) * amount_base - (2 * self.buffer_percentage * opportunity.buy_price * amount_base)
        
        buy_trade_details = Trade(
            exchange=opportunity.buy_exchange,
            pair=opportunity.pair,
            type=OrderType.MARKET,
            side=OrderSide.BUY,
            price=opportunity.buy_price,
            amount_base=amount_base,
            amount_quote=amount_quote,
            timestamp=timestamp,
            status=OrderStatus.CLOSED, # Simulate immediate fill for test
            fee_amount=self.buffer_percentage * amount_quote, # Simplified fee
            fee_currency=opportunity.pair.split("/")[1]
        )
        sell_trade_details = Trade(
            exchange=opportunity.sell_exchange,
            pair=opportunity.pair,
            type=OrderType.MARKET,
            side=OrderSide.SELL,
            price=opportunity.sell_price,
            amount_base=amount_base,
            amount_quote=opportunity.sell_price * amount_base,
            timestamp=timestamp,
            status=OrderStatus.CLOSED, # Simulate immediate fill for test
            fee_amount=self.buffer_percentage * (opportunity.sell_price * amount_base),
            fee_currency=opportunity.pair.split("/")[1]
        )

        arbitrage_trade = ArbitrageTrade(
            id=trade_id,
            opportunity_id=opportunity.id,
            timestamp=timestamp,
            pair=opportunity.pair,
            profit_percentage=opportunity.profit_percentage,
            profit_quote=profit_usd,
            buy_trade=buy_trade_details,
            sell_trade=sell_trade_details,
            is_test_trade=self.is_test_mode,
            status="completed" # Simplified
        )
        self.trades.insert(0, arbitrage_trade)
        self.trades = self.trades[:100]

        if self.is_test_mode:
            # Update test balances
            base_curr, quote_curr = opportunity.pair.split("/")
            await self._update_test_balance(opportunity.buy_exchange, quote_curr, -amount_quote) # Debit USDT
            await self._update_test_balance(opportunity.buy_exchange, base_curr, amount_base)    # Credit Base
            await self._update_test_balance(opportunity.sell_exchange, base_curr, -amount_base)   # Debit Base
            await self._update_test_balance(opportunity.sell_exchange, quote_curr, sell_trade_details.amount_quote) # Credit USDT
            logger.info(f"TEST MODE: Simulated trade executed: {arbitrage_trade.id}, Profit: ${profit_usd:.2f}")
        else:
            # Live mode: update running totals
            self.live_total_trades += 1
            self.live_total_profit += profit_usd
            logger.info(f"LIVE MODE: Trade executed: {arbitrage_trade.id}, Profit: ${profit_usd:.2f}")
        
        # await self._broadcast_new_trade(arbitrage_trade)
        # Consider broadcasting balance updates too
        pass

    async def reactivate_failsafe(self, type: str, entity_name: Optional[str] = None) -> Tuple[bool, str]:
        # Simplified failsafe reactivation logic
        logger.info(f"Attempting to reactivate failsafe: type={type}, entity={entity_name}")
        # ... (actual logic would modify self.failsafe_status)
        return True, f"Failsafe {type} for {entity_name or 'global'} reactivation attempted."

arbitrage_bot = ArbitrageBot()

# Helper for global access if needed, though direct import is fine for FastAPI
async def get_arbitrage_bot_instance() -> ArbitrageBot:
    return arbitrage_bot

# Add a global variable for loop_iterations to be used in _scan_arbitrage_opportunities
loop_iterations = 0
asset_capital_usd_per_pair = 0 # This is a placeholder, should be set from test_settings

