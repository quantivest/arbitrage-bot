from fastapi import APIRouter, HTTPException, Depends, WebSocket, WebSocketDisconnect
from typing import Dict, List, Optional
import asyncio
import json
from datetime import datetime

from .models import (
    ExchangeCredentials, ExchangeBalance, ArbitrageOpportunity, 
    ArbitrageTrade, TestModeSettings, BotStatus, AlertType, FailsafeStatus
)
from .exchanges import exchange_manager
from .arbitrage import arbitrage_bot
from .config import settings

router = APIRouter()

active_connections: List[WebSocket] = []

async def broadcast_updates():
    """Broadcast updates to all connected WebSocket clients."""
    while True:
        if active_connections:
            status = BotStatus(
                running=arbitrage_bot.running,
                test_mode=arbitrage_bot.test_mode,
                connected_exchanges=list(exchange_manager.exchanges.keys()),
                last_update=datetime.now(),
                failsafe_status=arbitrage_bot.get_failsafe_status(),
                alerts=arbitrage_bot.get_alerts(10),
                trades_blocked=arbitrage_bot.trades_blocked,
                failsafes_triggered=arbitrage_bot.failsafes_triggered
            )
            
            data = {
                "timestamp": datetime.now().isoformat(),
                "bot_status": status.dict(),
                "recent_trades": [trade.dict() for trade in arbitrage_bot.get_recent_trades(10)],
                "recent_opportunities": [opp.dict() for opp in arbitrage_bot.get_recent_opportunities(10)]
            }
            
            for connection in active_connections:
                try:
                    await connection.send_text(json.dumps(data))
                except Exception:
                    pass  # Connection might be closed
        
        await asyncio.sleep(2)

@router.on_event("startup")
async def startup_event():
    asyncio.create_task(broadcast_updates())

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_connections.remove(websocket)

@router.get("/exchanges")
async def get_supported_exchanges():
    """Get list of supported exchanges."""
    return {"exchanges": settings.SUPPORTED_EXCHANGES}

@router.post("/exchanges/connect")
async def connect_exchange(credentials: ExchangeCredentials):
    """Connect to an exchange with API credentials."""
    if credentials.exchange not in settings.SUPPORTED_EXCHANGES:
        raise HTTPException(status_code=400, detail=f"Exchange {credentials.exchange} not supported")
    
    success = await exchange_manager.connect_exchange(
        credentials.exchange, 
        credentials.api_key, 
        credentials.api_secret,
        credentials.additional_params
    )
    
    if not success:
        raise HTTPException(status_code=400, detail=f"Failed to connect to {credentials.exchange}")
    
    await exchange_manager.fetch_balances(credentials.exchange)
    
    return {"status": "connected", "exchange": credentials.exchange}

@router.delete("/exchanges/{exchange_id}")
async def disconnect_exchange(exchange_id: str):
    """Disconnect from an exchange."""
    success = await exchange_manager.disconnect_exchange(exchange_id)
    
    if not success:
        raise HTTPException(status_code=404, detail=f"Exchange {exchange_id} not connected")
    
    return {"status": "disconnected", "exchange": exchange_id}

@router.get("/exchanges/connected")
async def get_connected_exchanges():
    """Get list of connected exchanges."""
    return {"exchanges": list(exchange_manager.exchanges.keys())}

@router.get("/balances")
async def get_balances(refresh: bool = False):
    """Get balances from all connected exchanges."""
    if refresh:
        balances = await exchange_manager.fetch_balances()
    else:
        balances = list(exchange_manager.exchange_balances.values())
    
    return {"balances": [balance.dict() for balance in balances]}

@router.get("/bot/status")
async def get_bot_status():
    """Get current bot status."""
    status = BotStatus(
        running=arbitrage_bot.running,
        test_mode=arbitrage_bot.test_mode,
        connected_exchanges=list(exchange_manager.exchanges.keys()),
        last_update=datetime.now(),
        failsafe_status=arbitrage_bot.get_failsafe_status(),
        alerts=arbitrage_bot.get_alerts(10),
        trades_blocked=arbitrage_bot.trades_blocked,
        failsafes_triggered=arbitrage_bot.failsafes_triggered
    )
    
    return status.dict()

@router.post("/bot/start")
async def start_bot(test_mode: bool = False, test_settings: Optional[TestModeSettings] = None):
    """Start the arbitrage bot."""
    if len(exchange_manager.exchanges) < 2:
        raise HTTPException(status_code=400, detail="At least 2 exchanges must be connected")
    
    await exchange_manager.fetch_balances()
    
    arbitrage_bot.start(test_mode, test_settings.dict() if test_settings else None)
    
    return {"status": "started", "test_mode": test_mode}

@router.post("/bot/stop")
async def stop_bot():
    """Stop the arbitrage bot."""
    arbitrage_bot.stop()
    
    return {"status": "stopped"}

@router.get("/opportunities")
async def get_opportunities(limit: int = 50):
    """Get recent arbitrage opportunities."""
    opportunities = arbitrage_bot.get_recent_opportunities(limit)
    
    return {"opportunities": [opp.dict() for opp in opportunities]}

@router.get("/trades")
async def get_trades(limit: int = 50, test_mode: Optional[bool] = None):
    """Get recent trades."""
    trades = arbitrage_bot.get_recent_trades(limit, test_mode)
    
    return {"trades": [trade.dict() for trade in trades]}

@router.get("/alerts")
async def get_alerts(limit: int = 50):
    """Get recent alerts."""
    alerts = arbitrage_bot.get_alerts(limit)
    
    return {"alerts": [alert.dict() for alert in alerts]}

@router.post("/reactivate/pair/{pair}")
async def reactivate_pair(pair: str):
    """Reactivate a disabled trading pair."""
    success = arbitrage_bot.reactivate_pair(pair)
    
    if not success:
        raise HTTPException(status_code=404, detail=f"Pair {pair} not disabled or not found")
    
    return {"status": "reactivated", "pair": pair}

@router.post("/reactivate/exchange/{exchange}")
async def reactivate_exchange(exchange: str):
    """Reactivate a disabled exchange."""
    success = arbitrage_bot.reactivate_exchange(exchange)
    
    if not success:
        raise HTTPException(status_code=404, detail=f"Exchange {exchange} not disabled or not found")
    
    return {"status": "reactivated", "exchange": exchange}

@router.post("/reactivate/global")
async def reactivate_global():
    """Reactivate global trading after halt."""
    success = arbitrage_bot.reactivate_global()
    
    if not success:
        raise HTTPException(status_code=400, detail="Global trading not halted")
    
    return {"status": "reactivated", "global": True}

@router.get("/test/balances")
async def get_test_balances():
    """Get current test balances."""
    if not arbitrage_bot.test_mode:
        raise HTTPException(status_code=400, detail="Bot is not in test mode")
    
    return {"balances": arbitrage_bot.get_test_balances()}
