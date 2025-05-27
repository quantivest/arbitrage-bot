from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import psycopg
from datetime import datetime
from .api import router as api_router

app = FastAPI(
    title="Crypto Arbitrage Bot API",
    description="API for spot-to-spot crypto arbitrage bot",
    version="1.0.0"
)

# Disable CORS. Do not remove this for full-stack development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

app.include_router(api_router, prefix="/api")

@app.get("/healthz")
async def healthz():
    return {"status": "ok"}

@app.get("/health")
async def health_check():
    """Comprehensive health check for deployment monitoring."""
    try:
        from .exchanges import exchange_manager
        from .arbitrage import arbitrage_bot
        
        health_status = {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "version": "1.0.0",
            "services": {
                "api": "healthy",
                "websocket": "healthy",
                "arbitrage_bot": "healthy" if arbitrage_bot else "unavailable",
                "exchange_manager": "healthy" if exchange_manager else "unavailable"
            },
            "connected_exchanges": list(exchange_manager.exchanges.keys()) if exchange_manager else [],
            "bot_running": arbitrage_bot.is_running if arbitrage_bot else False,
            "bot_mode": arbitrage_bot.current_mode if arbitrage_bot else "unknown"
        }
        
        return health_status
    except Exception as e:
        return {
            "status": "unhealthy",
            "timestamp": datetime.utcnow().isoformat(),
            "error": str(e)
        }
