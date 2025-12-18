from typing import Dict, Any, List
from sqlmodel import Session, select
from models import Setting
from schemas.common import SettingUpdate

class SettingsService:
    def get_settings(self, session: Session) -> Dict[str, Any]:
        settings = session.exec(select(Setting)).all()
        return {s.key: s.value for s in settings}

    def update_setting(self, session: Session, setting: SettingUpdate) -> Dict[str, Any]:
        db_setting = session.get(Setting, setting.key)
        if not db_setting:
            # Create new if not exists
            db_setting = Setting(key=setting.key, value=setting.value)
            session.add(db_setting)
        else:
            db_setting.value = setting.value
            session.add(db_setting)
            
        session.commit()
        session.refresh(db_setting)
        return {"key": db_setting.key, "value": db_setting.value}
