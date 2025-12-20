import logging
import sys
import os

# Add the current directory to sys.path to ensure imports work correctly
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlmodel import Session
from infra.database.connection import engine
from infra.database.migrations import seed_initial_data

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    logger.info("Starting manual data seeding...")
    try:
        with Session(engine) as session:
            seed_initial_data(session)
        logger.info("Manual seeding completed successfully.")
    except Exception as e:
        logger.error(f"Seeding failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
