import logging
from sqlmodel import Session

logger = logging.getLogger(__name__)

def seed_initial_data(session: Session):
    """初期データ投入 (現在は投入する初期データなし)"""
    pass
