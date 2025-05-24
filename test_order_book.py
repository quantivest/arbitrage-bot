import asyncio
import sys
import logging
from app.exchanges import exchange_manager
from app.models import OrderBook
from app.config import settings
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def test_fetch_order_book():
    """Test the fetch_order_book function with retry mechanism."""
    logger.info("Testing fetch_order_book function with retry mechanism")
    
    exchange_id = "binanceus"  # Using Binance US as an example
    symbol = "BTC/USDT"
    
    await exchange_manager.connect_exchange(
        exchange_id=exchange_id,
        api_key=settings.EXCHANGE_API_KEYS.get(exchange_id.lower(), ""),
        api_secret=settings.EXCHANGE_API_SECRETS.get(exchange_id.lower(), ""),
        test_mode=True
    )
    
    logger.info(f"Fetching order book for {symbol} on {exchange_id} with retry")
    order_book = await exchange_manager.fetch_order_book(
        exchange_id=exchange_id,
        symbol=symbol,
        limit=10,
        max_retries=2
    )
    
    if order_book:
        logger.info(f"Successfully fetched order book:")
        logger.info(f"  Symbol: {order_book.symbol}")
        logger.info(f"  Exchange: {order_book.exchange}")
        logger.info(f"  Timestamp: {order_book.timestamp}")
        logger.info(f"  Top bid: {order_book.bids[0].price if order_book.bids else 'N/A'}")
        logger.info(f"  Top ask: {order_book.asks[0].price if order_book.asks else 'N/A'}")
        logger.info(f"  Timestamp type: {type(order_book.timestamp)}")
        
        assert isinstance(order_book.timestamp, datetime), "Timestamp is not a datetime object"
        logger.info("Timestamp validation passed")
        
        return True
    else:
        logger.error("Failed to fetch order book")
        return False

async def main():
    """Main test function."""
    try:
        success = await test_fetch_order_book()
        if success:
            logger.info("All tests passed!")
            return 0
        else:
            logger.error("Tests failed!")
            return 1
    except Exception as e:
        logger.error(f"Error during testing: {e}", exc_info=True)
        return 1
    finally:
        for exchange_id in exchange_manager.exchanges:
            await exchange_manager.disconnect_exchange(exchange_id)

if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(result)
