import sys
import logging
from datetime import datetime, timezone
from app.models import OrderBook, OrderBookEntry

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_orderbook_timestamp_handling():
    """Test the timestamp handling in OrderBook creation."""
    logger.info("Testing timestamp handling in OrderBook creation")
    
    logger.info("Test case 1: Valid timestamp")
    timestamp = datetime.now(timezone.utc)
    order_book = OrderBook(
        symbol="BTC/USDT",
        bids=[OrderBookEntry(price=50000.0, amount=1.0)],
        asks=[OrderBookEntry(price=50100.0, amount=1.0)],
        timestamp=timestamp,
        exchange="test_exchange"
    )
    logger.info(f"OrderBook created with timestamp: {order_book.timestamp}")
    assert isinstance(order_book.timestamp, datetime), "Timestamp is not a datetime object"
    logger.info("Test case 1 passed: Valid timestamp accepted")
    
    logger.info("Test case 2: Default timestamp")
    order_book = OrderBook(
        symbol="BTC/USDT",
        bids=[OrderBookEntry(price=50000.0, amount=1.0)],
        asks=[OrderBookEntry(price=50100.0, amount=1.0)],
        exchange="test_exchange"
    )
    logger.info(f"OrderBook created with default timestamp: {order_book.timestamp}")
    assert isinstance(order_book.timestamp, datetime), "Default timestamp is not a datetime object"
    logger.info("Test case 2 passed: Default timestamp is a valid datetime object")
    
    return True

if __name__ == "__main__":
    try:
        success = test_orderbook_timestamp_handling()
        if success:
            logger.info("All tests passed!")
            sys.exit(0)
        else:
            logger.error("Tests failed!")
            sys.exit(1)
    except Exception as e:
        logger.error(f"Error during testing: {e}", exc_info=True)
        sys.exit(1)
