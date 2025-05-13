from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Query
from typing import List, Optional, Dict
import asyncio
import json
from datetime import datetime
import logging # MODIFICATION: Added logging

from .models import (
    ExchangeCredentials, ExchangeBalance, ArbitrageOpportunity, 
    ArbitrageTrade, TestModeSettings, BotStatusPayload, AlertMessage, 
    FailsafeStatusData, StartBotRequest, ActionResponse, ReactivateRequest,
    TestSimulationStatusPayload # MODIFICATION: Added TestSimulationStatusPayload
)
from .exchanges import exchange_manager
from .arbitrage import arbitrage_bot
from .config import settings

# Configure logging
logger = logging.getLogger("api") # MODIFICATION: Use a named logger
logging.basicConfig(level=logging.INFO, format=\'%(asctime)s - %(name)s - %(levelname)s - %(message)s

router = APIRouter()

# --- WebSocket Connection Management ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.broadcast_task: Optional[asyncio.Task] = None

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connection accepted. Total: {len(self.active_connections)}")
        await self.send_initial_status(websocket) # MODIFICATION: Send initial status immediately

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"WebSocket connection closed. Total: {len(self.active_connections)}")

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        try:
            await websocket.send_text(json.dumps(message, default=str))
        except Exception as e:
            logger.error(f"Error sending personal message: {e}")
            self.disconnect(websocket)

    async def broadcast(self, message: dict):
        # logger.debug(f"Broadcasting message to {len(self.active_connections)} clients: {message.get(\'type
        # MODIFICATION: More selective logging for broadcast to avoid excessive noise
        if message.get("type") != "bot_status_update": # Log other types of broadcasts
             logger.info(f"Broadcasting message of type {message.get(\'type
        living_connections = self.active_connections[:]
        for connection in living_connections:
            try:
                await connection.send_text(json.dumps(message, default=str))
            except Exception as e:
                logger.warning(f"Error broadcasting to a client: {e}. Removing client.")
                self.disconnect(connection)
    
    async def send_initial_status(self, websocket: WebSocket):
        """Sends the current bot status immediately upon connection."""
        status_payload = await self._get_current_status_payload()
        await self.send_personal_message({"type": "initial_status", "payload": status_payload}, websocket)
        logger.info("Sent initial status to newly connected WebSocket client.")

    async def _get_current_status_payload(self) -> dict:
        """Helper to construct the current full status payload."""
        # This ensures we get the most up-to-date status from the bot and exchange_manager
        connected_exchanges_list = list(exchange_manager.exchanges.keys())
        current_failsafe_status = await arbitrage_bot.get_failsafe_status() # Ensure it's awaited if async
        current_alerts = await arbitrage_bot.get_alerts(limit=settings.MAX_ALERTS_WEBSOCKET)
        test_sim_status = await arbitrage_bot.get_test_simulation_status() # New method

        payload = BotStatusPayload(
            is_bot_running=arbitrage_bot.is_running, # Use the correct property
            current_mode=arbitrage_bot.current_mode, # Use the correct property
            connected_exchanges=connected_exchanges_list,
            websocket_connected=True, # For the client receiving this
            last_status_update_ts=datetime.utcnow(),
            active_alerts=[alert.dict() for alert in current_alerts],
            failsafe_status=current_failsafe_status.dict() if current_failsafe_status else FailsafeStatusData().dict(),
            live_total_trades=arbitrage_bot.live_total_trades,
            live_total_profit=arbitrage_bot.live_total_profit
        )
        return {
            "bot_status": payload.dict(),
            "test_simulation_status": test_sim_status.dict() if test_sim_status else TestSimulationStatusPayload().dict(),
            "recent_trades": [trade.dict() for trade in await arbitrage_bot.get_recent_trades(limit=10, is_test_trade=arbitrage_bot.current_mode == "test_simulating")],
            "recent_opportunities": [opp.dict() for opp in await arbitrage_bot.get_recent_opportunities(limit=10)],
            "exchange_balances": [bal.dict() for bal in list(exchange_manager.exchange_balances.values())] # Also send balances
        }

    async def periodic_broadcast_loop(self):
        """Periodically broadcasts full status updates."""
        while True:
            await asyncio.sleep(settings.WEBSOCKET_BROADCAST_INTERVAL_SECONDS)
            if not self.active_connections:
                continue
            try:
                payload = await self._get_current_status_payload()
                await self.broadcast({"type": "bot_status_update", "payload": payload})
            except Exception as e:
                logger.error(f"Error in periodic_broadcast_loop: {e}", exc_info=True)

connection_manager = ConnectionManager()

# --- Event Handlers ---
@router.on_event("startup")
async def startup_event():
    logger.info("API Startup: Initializing exchange manager and arbitrage bot...")
    # Initialize connections or other startup tasks if necessary
    # Start the periodic broadcast loop
    if connection_manager.broadcast_task is None:
        connection_manager.broadcast_task = asyncio.create_task(connection_manager.periodic_broadcast_loop())
        logger.info("WebSocket broadcast loop started.")

@router.on_event("shutdown")
async def shutdown_event():
    logger.info("API Shutdown: Stopping bot and closing connections...")
    if arbitrage_bot.is_running:
        await arbitrage_bot.stop() # Ensure bot is stopped gracefully
    if connection_manager.broadcast_task:
        connection_manager.broadcast_task.cancel()
        try:
            await connection_manager.broadcast_task
        except asyncio.CancelledError:
            logger.info("WebSocket broadcast loop cancelled.")
    # Close all WebSocket connections
    for ws in connection_manager.active_connections[:]:
        await ws.close(code=1000)
    logger.info("All WebSocket connections closed.")

# --- WebSocket Endpoint ---
@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await connection_manager.connect(websocket)
    try:
        while True:
            message_text = await websocket.receive_text()
            try:
                data = json.loads(message_text)
                if data.get("type") == "ping":
                    await connection_manager.send_personal_message({"type": "pong", "timestamp": datetime.utcnow().isoformat()}, websocket)
                # Potentially handle other client-to-server messages here
            except json.JSONDecodeError:
                logger.warning(f"Received invalid JSON via WebSocket: {message_text}")
            except Exception as e:
                logger.error(f"Error processing WebSocket message: {e}", exc_info=True)
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected.")
    except Exception as e:
        logger.error(f"Unexpected WebSocket error: {e}", exc_info=True)
    finally:
        connection_manager.disconnect(websocket)

# --- Exchange Endpoints ---
@router.get("/exchanges", response_model=Dict[str, List[str]])
async def get_supported_exchanges_api():
    return {"exchanges": settings.SUPPORTED_EXCHANGES}

@router.post("/exchanges/connect", response_model=ActionResponse)
async def connect_exchange_api(credentials: ExchangeCredentials):
    if credentials.exchange not in settings.SUPPORTED_EXCHANGES:
        raise HTTPException(status_code=400, detail=f"Exchange {credentials.exchange} is not supported.")
    
    logger.info(f"Attempting to connect to exchange: {credentials.exchange}")
    success, message = await exchange_manager.connect_exchange(
        credentials.exchange,
        credentials.api_key,
        credentials.api_secret,
        credentials.additional_params
    )
    if not success:
        logger.error(f"Failed to connect to {credentials.exchange}: {message}")
        raise HTTPException(status_code=400, detail=message or f"Failed to connect to {credentials.exchange}")
    
    # Attempt to fetch balances immediately to confirm connection health
    try:
        await exchange_manager.fetch_balances_for_exchange(credentials.exchange) # MODIFICATION: Specific fetch
        logger.info(f"Successfully fetched initial balances for {credentials.exchange}.")
    except Exception as e:
        logger.warning(f"Connected to {credentials.exchange}, but failed initial balance fetch: {str(e)}")
        # Don\'t fail the connection yet, but log it. Frontend should show error for this exchange balance.

    return ActionResponse(success=True, message=f"Successfully connected to {credentials.exchange}. Balances are being updated.")

@router.post("/exchanges/{exchange_id}/disconnect", response_model=ActionResponse) # MODIFICATION: Changed to POST for action
async def disconnect_exchange_api(exchange_id: str):
    logger.info(f"Attempting to disconnect from exchange: {exchange_id}")
    success, message = await exchange_manager.disconnect_exchange(exchange_id)
    if not success:
        logger.warning(f"Failed to disconnect from {exchange_id}: {message}")
        raise HTTPException(status_code=404, detail=message or f"Exchange {exchange_id} not found or already disconnected.")
    return ActionResponse(success=True, message=f"Successfully disconnected from {exchange_id}.")

@router.get("/exchanges/connected", response_model=Dict[str, List[str]])
async def get_connected_exchanges_api():
    return {"exchanges": list(exchange_manager.exchanges.keys())}

@router.get("/balances", response_model=List[ExchangeBalance])
async def get_balances_api(refresh: bool = Query(False, description="Force refresh balances from exchanges")):
    if refresh:
        logger.info("Force refreshing all exchange balances via API request.")
        await exchange_manager.fetch_all_balances() # MODIFICATION: More explicit method name
    return list(exchange_manager.exchange_balances.values())

# --- Bot Control & Status Endpoints ---
@router.get("/bot/status", response_model=BotStatusPayload)
async def get_bot_status_api():
    payload_dict = await connection_manager._get_current_status_payload() # Use the same helper
    # The helper returns a dict with keys like "bot_status", "test_simulation_status", etc.
    # We need to ensure the response model matches this structure or adapt it.
    # For now, let's assume BotStatusPayload is the main part.
    return BotStatusPayload(**payload_dict["bot_status"]) # Adapt if necessary

@router.post("/bot/start", response_model=ActionResponse)
async def start_bot_api(request: StartBotRequest):
    logger.info(f"Received request to start bot in {request.mode} mode.")
    if len(exchange_manager.exchanges) < 2:
        logger.warning("Start bot request failed: Less than 2 exchanges connected.")
        raise HTTPException(status_code=400, detail="At least 2 exchanges must be connected to start the bot.")
    
    success, message = await arbitrage_bot.start(request.mode, request.test_settings)
    if not success:
        logger.error(f"Failed to start bot: {message}")
        raise HTTPException(status_code=500, detail=message or "Failed to start the bot.")
    logger.info(f"Bot started successfully in {request.mode} mode.")
    return ActionResponse(success=True, message=message or f"Bot started in {request.mode} mode.")

@router.post("/bot/stop", response_model=ActionResponse)
async def stop_bot_api():
    logger.info("Received request to stop bot.")
    success, message = await arbitrage_bot.stop()
    if not success:
        logger.error(f"Failed to stop bot: {message}")
        # Even if there was an issue, we usually want to confirm it tried to stop.
        # Consider if a 500 is appropriate or just a success=false with message.
        # For now, let's assume stop should generally succeed in changing state.
        return ActionResponse(success=False, message=message or "Bot was not running or failed to stop cleanly.")
    logger.info("Bot stopped successfully.")
    return ActionResponse(success=True, message=message or "Bot stopped successfully.")

# --- Data Endpoints ---
@router.get("/opportunities", response_model=List[ArbitrageOpportunity])
async def get_opportunities_api(limit: int = Query(20, ge=1, le=100)):
    return await arbitrage_bot.get_recent_opportunities(limit)

@router.get("/trades", response_model=List[ArbitrageTrade])
async def get_trades_api(limit: int = Query(50, ge=1, le=200), is_test_trade: Optional[bool] = Query(None)):
    return await arbitrage_bot.get_recent_trades(limit, is_test_trade)

@router.get("/alerts", response_model=List[AlertMessage])
async def get_alerts_api(limit: int = Query(20, ge=1, le=100)):
    return await arbitrage_bot.get_alerts(limit)

# --- Failsafe Endpoints ---
@router.get("/failsafe/status", response_model=FailsafeStatusData)
async def get_failsafe_status_api():
    status = await arbitrage_bot.get_failsafe_status()
    if status is None: # Should always return a status object from the bot
        logger.warning("Failsafe status returned None from bot, returning default empty status.")
        return FailsafeStatusData()
    return status

@router.post("/failsafe/reactivate", response_model=ActionResponse)
async def reactivate_failsafe_api(request: ReactivateRequest):
    logger.info(f"Received request to reactivate failsafe: type={request.type}, entity={request.entity_name}")
    success, message = await arbitrage_bot.reactivate_failsafe(request.type, request.entity_name)
    if not success:
        logger.warning(f"Failed to reactivate failsafe {request.type} for {request.entity_name}: {message}")
        raise HTTPException(status_code=400, detail=message)
    return ActionResponse(success=True, message=message)

# MODIFICATION: Endpoint for test simulation status (if needed beyond general bot status)
@router.get("/test/simulation/status", response_model=TestSimulationStatusPayload)
async def get_test_simulation_status_api():
    status = await arbitrage_bot.get_test_simulation_status()
    if status is None:
        logger.warning("Test simulation status returned None, returning default.")
        return TestSimulationStatusPayload() # Return default if None
    return status

# Example of how to trigger a broadcast manually (e.g., after a significant event)
# This would typically be called from within other modules like arbitrage_bot or exchange_manager
async def trigger_manual_status_broadcast(event_type: str, event_data: Optional[dict] = None):
    logger.info(f"Manually triggering broadcast for event: {event_type}")
    full_status_payload = await connection_manager._get_current_status_payload()
    message_to_broadcast = {
        "type": "event_update", 
        "event_type": event_type,
        "event_data": event_data or {},
        "current_status": full_status_payload
    }
    await connection_manager.broadcast(message_to_broadcast)

