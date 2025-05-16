from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Query
from typing import List, Optional, Dict
import asyncio
import json
from datetime import datetime
import logging
import traceback # Added for more detailed error logging

from .models import (
    ExchangeCredentials, ExchangeBalance, ArbitrageOpportunity, 
    ArbitrageTrade, TestModeSettings, BotStatusPayload, AlertMessage, 
    FailsafeStatus, FailsafeStatusData, StartBotRequest, ActionResponse, ReactivateRequest,
    TestSimulationStatusPayload, FullStatusUpdatePayload
)
from .exchanges import exchange_manager
from .arbitrage import arbitrage_bot 
from .config import settings

logger = logging.getLogger(__name__)

# Define the APIRouter instance
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

    async def broadcast(self, message: dict):
        if not self.active_connections:
            return
        for connection in list(self.active_connections):
            try:
                await connection.send_text(json.dumps(message, default=str))
            except Exception as e:
                logger.warning(f"Error broadcasting to client {connection.client.host}:{connection.client.port}: {e}. Removing client.")
                self.disconnect(connection)
    
    async def send_initial_status(self, websocket: WebSocket):
        logger.info(f"Sending initial status to newly connected client {websocket.client.host}:{websocket.client.port}.")
        try:
            status_payload = await self._get_current_full_status_payload()
            await self.send_personal_message({"type": "initial_status", "payload": status_payload.model_dump()}, websocket)
        except Exception as e:
            logger.error(f"Error sending initial status: {e}\n{traceback.format_exc()}")
            await self.send_personal_message({"type": "error", "payload": {"message": "Failed to retrieve initial status."}}, websocket)
        
    async def _get_current_full_status_payload(self) -> FullStatusUpdatePayload:
        connected_exchanges_list = list(exchange_manager.exchanges.keys())
        # arbitrage_bot.get_failsafe_status() returns FailsafeStatus
        # BotStatusPayload expects FailsafeStatusData for its failsafe_status field.
        # We need to convert FailsafeStatus to FailsafeStatusData.
        raw_failsafe_status: FailsafeStatus = await arbitrage_bot.get_failsafe_status()
        
        # Perform the conversion
        converted_failsafe_status_data = FailsafeStatusData(
            global_trading_halt=raw_failsafe_status.global_trading_halt,
            global_halt_reason=raw_failsafe_status.global_halt_reason,
            global_halt_timestamp=raw_failsafe_status.global_halt_timestamp,
            disabled_exchanges=raw_failsafe_status.disabled_exchanges,
            disabled_pairs=raw_failsafe_status.disabled_pairs
        )

        current_alerts = await arbitrage_bot.get_alerts(limit=settings.MAX_ALERTS_WEBSOCKET)
        test_sim_status_obj = await arbitrage_bot.get_test_simulation_status()

        bot_status_data = BotStatusPayload(
            is_bot_running=arbitrage_bot.is_running,
            current_mode=arbitrage_bot.current_mode,
            connected_exchanges=connected_exchanges_list,
            websocket_connected=True, 
            last_status_update_ts=datetime.utcnow(),
            active_alerts=current_alerts, 
            failsafe_status=converted_failsafe_status_data, # Use the converted data
            live_total_trades=arbitrage_bot.live_total_trades,
            live_total_profit=arbitrage_bot.live_total_profit
        )
        
        current_balances = list(exchange_manager.exchange_balances.values()) 
        recent_trades_list = await arbitrage_bot.get_recent_trades(limit=20, is_test_trade=arbitrage_bot.is_test_mode)
        recent_opportunities_list = await arbitrage_bot.get_recent_opportunities(limit=20)

        return FullStatusUpdatePayload(
            bot_status=bot_status_data,
            test_simulation_status=test_sim_status_obj, 
            recent_trades=recent_trades_list, 
            recent_opportunities=recent_opportunities_list, 
            exchange_balances=current_balances
        )

    async def periodic_broadcast_loop(self):
        logger.info("WebSocket periodic broadcast loop starting.")
        while True:
            await asyncio.sleep(settings.WEBSOCKET_BROADCAST_INTERVAL_SECONDS)
            if not self.active_connections:
                continue 
            try:
                payload_model = await self._get_current_full_status_payload()
                await self.broadcast({"type": "bot_status_update", "payload": payload_model.model_dump()})
            except Exception as e:
                logger.error(f"Error in periodic_broadcast_loop: {e}\n{traceback.format_exc()}")
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
    for ws in list(connection_manager.active_connections):
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
            try:
                data = json.loads(message_text)
                if data.get("type") == "ping":
                    await connection_manager.send_personal_message({"type": "pong", "timestamp": datetime.utcnow().isoformat()}, websocket)
            except json.JSONDecodeError:
                logger.warning(f"Received invalid JSON via WebSocket: {message_text}")
            except Exception as e:
                logger.error(f"Error processing WebSocket message: {e}\n{traceback.format_exc()}")

    except WebSocketDisconnect:
        logger.info(f"WebSocket client {websocket.client.host}:{websocket.client.port} disconnected.")
    except Exception as e:
        logger.error(f"Unexpected WebSocket error for {websocket.client.host}:{websocket.client.port}: {e}\n{traceback.format_exc()}")
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
    try:
        success, message = await exchange_manager.connect_exchange(
            credentials.exchange,
            credentials.api_key,
            credentials.api_secret,
            credentials.additional_params
        )
        if not success:
            logger.error(f"API: Failed to connect to {credentials.exchange}: {message}")
            raise HTTPException(status_code=400, detail=message)
        
        await exchange_manager.fetch_balances_for_exchange(credentials.exchange)
        logger.info(f"API: Successfully fetched initial balances for {credentials.exchange} post-connection.")

        full_status_payload = await connection_manager._get_current_full_status_payload()
        await connection_manager.broadcast({"type": "bot_status_update", "payload": full_status_payload.model_dump()})

        return ActionResponse(success=True, message=f"Successfully connected to {credentials.exchange}. Balances are being updated.")
    except HTTPException: # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"API: Unexpected error connecting to {credentials.exchange}: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred while connecting to {credentials.exchange}.")

@router.post("/exchanges/{exchange_id}/disconnect", response_model=ActionResponse)
async def disconnect_exchange_api(exchange_id: str):
    logger.info(f"API: Attempting to disconnect from exchange: {exchange_id}")
    try:
        success, message = await exchange_manager.disconnect_exchange(exchange_id)
        if not success and exchange_id in exchange_manager.exchanges:
             logger.warning(f"API: Disconnect from {exchange_id} reported: {message}, but still in manager list.")
        
        full_status_payload = await connection_manager._get_current_full_status_payload()
        await connection_manager.broadcast({"type": "bot_status_update", "payload": full_status_payload.model_dump()})

        return ActionResponse(success=True, message=f"Successfully processed disconnect for {exchange_id}.")
    except Exception as e:
        logger.error(f"API: Unexpected error disconnecting from {exchange_id}: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred while disconnecting from {exchange_id}.")

@router.get("/exchanges/connected", response_model=Dict[str, List[str]])
async def get_connected_exchanges_api():
    return {"exchanges": list(exchange_manager.exchanges.keys())}

@router.get("/balances", response_model=List[ExchangeBalance])
async def get_balances_api(refresh: bool = Query(False, description="Force refresh balances from exchanges")):
    try:
        if refresh:
            logger.info("API: Force refreshing all exchange balances via request.")
            await exchange_manager.fetch_all_balances()
        return list(exchange_manager.exchange_balances.values())
    except Exception as e:
        logger.error(f"API: Error fetching balances: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Failed to fetch balances.")

@router.get("/bot/status", response_model=BotStatusPayload)
async def get_bot_status_api():
    try:
        full_payload = await connection_manager._get_current_full_status_payload()
        return full_payload.bot_status 
    except Exception as e:
        logger.error(f"API: Error fetching bot status: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Failed to fetch bot status.")

@router.post("/bot/start", response_model=ActionResponse)
async def start_bot_api(request: StartBotRequest):
    logger.info(f"API: Received request to start bot in {request.mode} mode.")
    try:
        if len(exchange_manager.exchanges) < 2 and request.mode == "live":
            logger.warning("API: Start live bot request failed: Less than 2 exchanges connected.")
            raise HTTPException(status_code=400, detail="At least 2 exchanges must be connected to start the bot in live mode.")
        if request.mode == "test" and not request.test_settings:
            raise HTTPException(status_code=400, detail="Test settings are required to start in test mode.")

        test_settings_dict = request.test_settings.model_dump() if request.test_settings else None
        success, message = await arbitrage_bot.start(request.mode, test_settings_dict)
        
        if not success:
            logger.error(f"API: Failed to start bot: {message}")
            raise HTTPException(status_code=500, detail=message)
        
        logger.info(f"API: Bot started successfully in {request.mode} mode.")
        full_status_payload = await connection_manager._get_current_full_status_payload()
        await connection_manager.broadcast({"type": "bot_status_update", "payload": full_status_payload.model_dump()})
        return ActionResponse(success=True, message=message)
    except HTTPException: 
        raise
    except Exception as e:
        error_detail = f"Unexpected error starting bot: {str(e)}"
        logger.error(f"API: {error_detail}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=error_detail)

@router.post("/bot/stop", response_model=ActionResponse)
async def stop_bot_api():
    logger.info("API: Received request to stop bot.")
    try:
        success, message = await arbitrage_bot.stop()
        logger.info(f"API: Bot stop processed. Success: {success}, Message: {message}")
        full_status_payload = await connection_manager._get_current_full_status_payload()
        await connection_manager.broadcast({"type": "bot_status_update", "payload": full_status_payload.model_dump()})
        return ActionResponse(success=success, message=message)
    except Exception as e:
        logger.error(f"API: Unexpected error stopping bot: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred while stopping the bot.")

@router.get("/opportunities", response_model=List[ArbitrageOpportunity])
async def get_opportunities_api(limit: int = Query(20, ge=1, le=100)):
    try:
        return await arbitrage_bot.get_recent_opportunities(limit)
    except Exception as e:
        logger.error(f"API: Error fetching opportunities: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Failed to fetch opportunities.")

@router.get("/trades", response_model=List[ArbitrageTrade])
async def get_trades_api(limit: int = Query(50, ge=1, le=200), is_test_trade: Optional[bool] = Query(None)):
    try:
        return await arbitrage_bot.get_recent_trades(limit, is_test_trade)
    except Exception as e:
        logger.error(f"API: Error fetching trades: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Failed to fetch trades.")

@router.get("/alerts", response_model=List[AlertMessage])
async def get_alerts_api(limit: int = Query(20, ge=1, le=100)):
    try:
        return await arbitrage_bot.get_alerts(limit)
    except Exception as e:
        logger.error(f"API: Error fetching alerts: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Failed to fetch alerts.")

@router.get("/failsafe/status", response_model=FailsafeStatusData)
async def get_failsafe_status_api():
    try:
        raw_status: FailsafeStatus = await arbitrage_bot.get_failsafe_status()
        # Convert FailsafeStatus to FailsafeStatusData
        status_data = FailsafeStatusData(
            global_trading_halt=raw_status.global_trading_halt,
            global_halt_reason=raw_status.global_halt_reason,
            global_halt_timestamp=raw_status.global_halt_timestamp,
            disabled_exchanges=raw_status.disabled_exchanges,
            disabled_pairs=raw_status.disabled_pairs
        )
        return status_data
    except Exception as e:
        logger.error(f"API: Error fetching failsafe status: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Failed to fetch failsafe status.")

@router.post("/failsafe/reactivate", response_model=ActionResponse)
async def reactivate_failsafe_api(request: ReactivateRequest):
    logger.info(f"API: Received request to reactivate failsafe: type={request.type}, entity={request.entity_name}")
    try:
        # Placeholder for actual reactivation logic in arbitrage_bot
        success, message = await arbitrage_bot.reactivate_failsafe_entity(request.type, request.entity_name)
        if not success:
            raise HTTPException(status_code=400, detail=message)
        
        full_status_payload = await connection_manager._get_current_full_status_payload()
        await connection_manager.broadcast({"type": "bot_status_update", "payload": full_status_payload.model_dump()})
        return ActionResponse(success=True, message=message)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"API: Unexpected error reactivating failsafe: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred during failsafe reactivation.")

@router.get("/bot/test_simulation_status", response_model=TestSimulationStatusPayload)
async def get_test_simulation_status_api():
    try:
        return await arbitrage_bot.get_test_simulation_status()
    except Exception as e:
        logger.error(f"API: Error fetching test simulation status: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Failed to fetch test simulation status.")

