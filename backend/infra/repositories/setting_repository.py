from typing import List, Optional, Dict, Any
from sqlmodel import Session, select
from domain.models.setting import Setting

class SettingRepository:
    def __init__(self, session: Session):
        self.session = session

    def find_all(self) -> List[Setting]:
        return self.session.exec(select(Setting)).all()

    def get_by_key(self, key: str) -> Optional[Setting]:
        return self.session.get(Setting, key)

    def save(self, setting: Setting) -> Setting:
        self.session.add(setting)
        self.session.commit()
        self.session.refresh(setting)
        return setting
