from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Query
from typing import List, Optional, Dict
import asyncio
import json
from datetime import datetime
import logging

from .models import (
    ExchangeCredentials, ExchangeBalance, ArbitrageOpportunity, 
    ArbitrageTrade, TestModeSettings, BotStatusPayload, AlertMessage, 
    FailsafeStatusData, StartBotRequest, ActionResponse, ReactivateRequest,
    TestSimulationStatusPayload
)
from .exchanges import exchange_manager
from .arbitrage import arbitrage_bot # Direct import of the instance
from .config import settings

logger = logging.getLogger(__name__)
# BasicConfig should ideally be in main.py or a central logging setup
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

router = APIRouter()

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.broadcast_task: Optional[asyncio.Task] = None
        logger.info("WebSocket ConnectionManager initialized.")

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connection accepted from {websocket.client.host}:{websocket.client.port}. Total: {len(self.active_connections)}")
        await self.send_initial_status(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"WebSocket connection closed for {websocket.client.host}:{websocket.client.port}. Total: {len(self.active_connections)}")

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        try:
            await websocket.send_text(json.dumps(message, default=str))
        except Exception as e:
            logger.error(f"Error sending personal message to {websocket.client.host}:{websocket.client.port}: {e}")
            # self.disconnect(websocket) # Disconnect might be too aggressive here, depends on error type

    async def broadcast(self, message: dict):
        if not self.active_connections:
            return
        # More selective logging for broadcast to avoid excessive noise
        if message.get("type") != "bot_status_update" or len(self.active_connections) > 0:
             logger.debug(f"Broadcasting message of type {message.get('type')} to {len(self.active_connections)} client(s).")
        
        # Create a copy for iteration as disconnect can modify the list
        for connection in list(self.active_connections):
            try:
                await connection.send_text(json.dumps(message, default=str))
            except Exception as e:
                logger.warning(f"Error broadcasting to client {connection.client.host}:{connection.client.port}: {e}. Removing client.")
                self.disconnect(connection)
    
    async def send_initial_status(self, websocket: WebSocket):
        logger.info(f"Sending initial status to newly connected client {websocket.client.host}:{websocket.client.port}.")
        status_payload = await self._get_current_full_status_payload()
        await self.send_personal_message({"type": "initial_status", "payload": status_payload}, websocket)
        
    async def _get_current_full_status_payload(self) -> dict:
        """Helper to construct the current full status payload for WebSocket broadcasts."""
        connected_exchanges_list = list(exchange_manager.exchanges.keys())
        # Ensure all awaited calls are correctly handled
        current_failsafe_status = await arbitrage_bot.get_failsafe_status()
        current_alerts = await arbitrage_bot.get_alerts(limit=settings.MAX_ALERTS_WEBSOCKET)
        test_sim_status = await arbitrage_bot.get_test_simulation_status()

        bot_status_data = BotStatusPayload(
            is_bot_running=arbitrage_bot.is_running,
            current_mode=arbitrage_bot.current_mode,
            connected_exchanges=connected_exchanges_list,
            websocket_connected=True, # This is true for the client receiving it
            last_status_update_ts=datetime.utcnow(),
            active_alerts=[alert.model_dump() for alert in current_alerts],
            failsafe_status=current_failsafe_status.model_dump(),
            live_total_trades=arbitrage_bot.live_total_trades,
            live_total_profit=arbitrage_bot.live_total_profit
        )
        
        # Ensure exchange_balances are correctly fetched and formatted
        # This might involve calling exchange_manager.fetch_all_balances() if stale or relying on cached
        # For broadcast, using cached is generally fine if there's a background update mechanism.
        # For simplicity, let's assume exchange_manager.exchange_balances is up-to-date enough for broadcast.
        current_balances = [bal.model_dump() for bal in exchange_manager.exchange_balances.values()]

        return {
            "bot_status": bot_status_data.model_dump(),
            "test_simulation_status": test_sim_status.model_dump(),
            "recent_trades": [trade.model_dump() for trade in await arbitrage_bot.get_recent_trades(limit=10, is_test_trade=arbitrage_bot.is_test_mode)],
            "recent_opportunities": [opp.model_dump() for opp in await arbitrage_bot.get_recent_opportunities(limit=10)],
            "exchange_balances": current_balances
        }

    async def periodic_broadcast_loop(self):
        logger.info("WebSocket periodic broadcast loop starting.")
        while True:
            await asyncio.sleep(settings.WEBSOCKET_BROADCAST_INTERVAL_SECONDS)
            if not self.active_connections:
                continue # No clients, no broadcast
            try:
                payload = await self._get_current_full_status_payload()
                await self.broadcast({"type": "bot_status_update", "payload": payload})
            except Exception as e:
                logger.error(f"Error in periodic_broadcast_loop: {e}", exc_info=True)
        logger.info("WebSocket periodic broadcast loop stopped.")

connection_manager = ConnectionManager()

@router.on_event("startup")
async def startup_event():
    logger.info("API Startup event triggered.")
    if connection_manager.broadcast_task is None or connection_manager.broadcast_task.done():
        connection_manager.broadcast_task = asyncio.create_task(connection_manager.periodic_broadcast_loop())
        logger.info("WebSocket broadcast loop (re)started.")

@router.on_event("shutdown")
async def shutdown_event():
    logger.info("API Shutdown event triggered.")
    if arbitrage_bot.is_running:
        logger.info("Stopping arbitrage bot during API shutdown...")
        await arbitrage_bot.stop()
    if connection_manager.broadcast_task and not connection_manager.broadcast_task.done():
        connection_manager.broadcast_task.cancel()
        try:
            await connection_manager.broadcast_task
        except asyncio.CancelledError:
            logger.info("WebSocket broadcast loop successfully cancelled.")
    logger.info("Closing all active WebSocket connections...")
    for ws in list(connection_manager.active_connections): # Iterate over a copy
        try:
            await ws.close(code=1000)
        except Exception as e:
            logger.warning(f"Error closing a WebSocket connection during shutdown: {e}")
    logger.info("API Shutdown complete.")

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await connection_manager.connect(websocket)
    try:
        while True:
            message_text = await websocket.receive_text()
            # Handle client-to-server messages if any (e.g., custom pings, commands)
            # For now, we primarily use server-to-client broadcasts
            try:
                data = json.loads(message_text)
                if data.get("type") == "ping": # Simple ping/pong
                    await connection_manager.send_personal_message({"type": "pong", "timestamp": datetime.utcnow().isoformat()}, websocket)
            except json.JSONDecodeError:
                logger.warning(f"Received invalid JSON via WebSocket: {message_text}")
            except Exception as e:
                logger.error(f"Error processing WebSocket message: {e}", exc_info=True)

    except WebSocketDisconnect:
        logger.info(f"WebSocket client {websocket.client.host}:{websocket.client.port} disconnected.")
    except Exception as e:
        logger.error(f"Unexpected WebSocket error for {websocket.client.host}:{websocket.client.port}: {e}", exc_info=True)
    finally:
        connection_manager.disconnect(websocket)

@router.get("/exchanges", response_model=Dict[str, List[str]])
async def get_supported_exchanges_api():
    return {"exchanges": settings.SUPPORTED_EXCHANGES}

@router.post("/exchanges/connect", response_model=ActionResponse)
async def connect_exchange_api(credentials: ExchangeCredentials):
    if credentials.exchange.lower() not in [ex.lower() for ex in settings.SUPPORTED_EXCHANGES]:
        raise HTTPException(status_code=400, detail=f"Exchange {credentials.exchange} is not supported.")
    
    logger.info(f"API: Attempting to connect to exchange: {credentials.exchange}")
    success, message = await exchange_manager.connect_exchange(
        credentials.exchange,
        credentials.api_key,
        credentials.api_secret,
        credentials.additional_params
    )
    if not success:
        logger.error(f"API: Failed to connect to {credentials.exchange}: {message}")
        raise HTTPException(status_code=400, detail=message)
    
    # Attempt to fetch balances immediately to confirm connection health and populate cache
    try:
        await exchange_manager.fetch_balances_for_exchange(credentials.exchange)
        logger.info(f"API: Successfully fetched initial balances for {credentials.exchange} post-connection.")
    except Exception as e:
        logger.warning(f"API: Connected to {credentials.exchange}, but failed initial balance fetch: {str(e)}")
        # Don't fail the connection, but this might mean balances are stale/unavailable initially

    # Trigger a broadcast to update clients with new connection status and balances
    await connection_manager.broadcast({"type": "exchange_connected", "payload": {"exchange": credentials.exchange}})
    full_status_payload = await connection_manager._get_current_full_status_payload()
    await connection_manager.broadcast({"type": "bot_status_update", "payload": full_status_payload})

    return ActionResponse(success=True, message=f"Successfully connected to {credentials.exchange}. Balances are being updated.")

@router.post("/exchanges/{exchange_id}/disconnect", response_model=ActionResponse)
async def disconnect_exchange_api(exchange_id: str):
    logger.info(f"API: Attempting to disconnect from exchange: {exchange_id}")
    success, message = await exchange_manager.disconnect_exchange(exchange_id)
    if not success:
        # Even if disconnect had an issue, it might be removed from manager. Reflect this.
        logger.warning(f"API: Disconnect from {exchange_id} reported: {message}")
        # Check if it's truly still in manager's list
        if exchange_id in exchange_manager.exchanges:
             raise HTTPException(status_code=400, detail=message)
    
    # Trigger a broadcast to update clients
    await connection_manager.broadcast({"type": "exchange_disconnected", "payload": {"exchange": exchange_id}})
    full_status_payload = await connection_manager._get_current_full_status_payload()
    await connection_manager.broadcast({"type": "bot_status_update", "payload": full_status_payload})

    return ActionResponse(success=True, message=f"Successfully processed disconnect for {exchange_id}.")

@router.get("/exchanges/connected", response_model=Dict[str, List[str]])
async def get_connected_exchanges_api():
    return {"exchanges": list(exchange_manager.exchanges.keys())}

@router.get("/balances", response_model=List[ExchangeBalance])
async def get_balances_api(refresh: bool = Query(False, description="Force refresh balances from exchanges")):
    if refresh:
        logger.info("API: Force refreshing all exchange balances via request.")
        await exchange_manager.fetch_all_balances()
    return list(exchange_manager.exchange_balances.values())

@router.get("/bot/status", response_model=BotStatusPayload) # This might need to return the full status dict now
async def get_bot_status_api():
    # This endpoint should ideally return the same structure as the WebSocket bot_status part
    full_payload = await connection_manager._get_current_full_status_payload()
    return BotStatusPayload(**full_payload["bot_status"]) 

@router.post("/bot/start", response_model=ActionResponse)
async def start_bot_api(request: StartBotRequest):
    logger.info(f"API: Received request to start bot in {request.mode} mode.")
    if len(exchange_manager.exchanges) < 2 and request.mode == "live":
        logger.warning("API: Start live bot request failed: Less than 2 exchanges connected.")
        raise HTTPException(status_code=400, detail="At least 2 exchanges must be connected to start the bot in live mode.")
    if request.mode == "test" and not request.test_settings:
        raise HTTPException(status_code=400, detail="Test settings are required to start in test mode.")

    success, message = await arbitrage_bot.start(request.mode, request.test_settings.model_dump() if request.test_settings else None)
    if not success:
        logger.error(f"API: Failed to start bot: {message}")
        raise HTTPException(status_code=500, detail=message)
    
    logger.info(f"API: Bot started successfully in {request.mode} mode.")
    # Trigger broadcast for status update
    full_status_payload = await connection_manager._get_current_full_status_payload()
    await connection_manager.broadcast({"type": "bot_status_update", "payload": full_status_payload})
    return ActionResponse(success=True, message=message)

@router.post("/bot/stop", response_model=ActionResponse)
async def stop_bot_api():
    logger.info("API: Received request to stop bot.")
    success, message = await arbitrage_bot.stop()
    # No specific error code for stop failure, as it usually means it wasn't running or already stopped.
    # The success flag and message should be sufficient.
    logger.info(f"API: Bot stop processed. Success: {success}, Message: {message}")
    # Trigger broadcast for status update
    full_status_payload = await connection_manager._get_current_full_status_payload()
    await connection_manager.broadcast({"type": "bot_status_update", "payload": full_status_payload})
    return ActionResponse(success=success, message=message)

@router.get("/opportunities", response_model=List[ArbitrageOpportunity])
async def get_opportunities_api(limit: int = Query(20, ge=1, le=100)):
    return await arbitrage_bot.get_recent_opportunities(limit)

@router.get("/trades", response_model=List[ArbitrageTrade])
async def get_trades_api(limit: int = Query(50, ge=1, le=200), is_test_trade: Optional[bool] = Query(None)):
    return await arbitrage_bot.get_recent_trades(limit, is_test_trade)

@router.get("/alerts", response_model=List[AlertMessage])
async def get_alerts_api(limit: int = Query(20, ge=1, le=100)):
    return await arbitrage_bot.get_alerts(limit)

@router.get("/failsafe/status", response_model=FailsafeStatusData)
async def get_failsafe_status_api():
    status = await arbitrage_bot.get_failsafe_status()
    return status # Assumes get_failsafe_status returns FailsafeStatusData model

@router.post("/failsafe/reactivate", response_model=ActionResponse)
async def reactivate_failsafe_api(request: ReactivateRequest):
    logger.info(f"API: Received request to reactivate failsafe: type={request.type}, entity={request.entity_name}")
    success, message = await arbitrage_bot.reactivate_failsafe(request.type, request.entity_name)
    if not success:
        logger.warning(f"API: Failed to reactivate failsafe {request.type} for {request.entity_name}: {message}")
        raise HTTPException(status_code=400, detail=message)
    # Trigger broadcast for status update as failsafe status might have changed
    full_status_payload = await connection_manager._get_current_full_status_payload()
    await connection_manager.broadcast({"type": "bot_status_update", "payload": full_status_payload})
    return ActionResponse(success=True, message=message)

@router.get("/test/simulation/status", response_model=TestSimulationStatusPayload)
async def get_test_simulation_status_api():
    status = await arbitrage_bot.get_test_simulation_status()
    return status

