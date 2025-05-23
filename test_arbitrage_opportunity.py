import sys
import logging
from datetime import datetime, timezone
import uuid
from app.models import ArbitrageOpportunity

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_arbitrage_opportunity_creation():
    """Test the ArbitrageOpportunity model with all required fields."""
    logger.info("Testing ArbitrageOpportunity model creation")
    
    opportunity_id = str(uuid.uuid4())
    opportunity = ArbitrageOpportunity(
        id=opportunity_id,
        pair="BTC/USDT",  # Using 'pair' instead of 'symbol'
        buy_exchange="binance",
        sell_exchange="kraken",
        buy_price=50000.0,
        sell_price=50100.0,
        potential_profit_percentage=0.2,
        max_tradeable_amount_base=0.1,
        max_tradeable_amount_quote=5000.0,
        timestamp=datetime.now(timezone.utc),
        source="test"
    )
    
    logger.info(f"Successfully created ArbitrageOpportunity with ID: {opportunity.id}")
    logger.info(f"Symbol (from pair alias): {opportunity.symbol}")
    logger.info(f"Max tradeable amount base: {opportunity.max_tradeable_amount_base}")
    logger.info(f"Max tradeable amount quote: {opportunity.max_tradeable_amount_quote}")
    
    assert opportunity.id == opportunity_id, "ID field mismatch"
    assert opportunity.symbol == "BTC/USDT", "Symbol field mismatch"
    assert opportunity.max_tradeable_amount_base == 0.1, "max_tradeable_amount_base field mismatch"
    assert opportunity.max_tradeable_amount_quote == 5000.0, "max_tradeable_amount_quote field mismatch"
    
    logger.info("All validation tests passed!")
    return True

if __name__ == "__main__":
    try:
        success = test_arbitrage_opportunity_creation()
        if success:
            logger.info("All tests passed!")
            sys.exit(0)
        else:
            logger.error("Tests failed!")
            sys.exit(1)
    except Exception as e:
        logger.error(f"Error during testing: {e}", exc_info=True)
        sys.exit(1)
