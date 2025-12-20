from typing import Dict, Any
from sqlmodel import Session
from domain.models.setting import Setting
from infra.repositories.setting_repository import SettingRepository
from api.schemas.common import SettingUpdate

class SettingAppService:
    def __init__(self, session: Session):
        self.session = session
        self.repository = SettingRepository(session)

    def get_settings(self) -> Dict[str, Any]:
        settings = self.repository.find_all()
        return {s.key: s.value for s in settings}

    def update_setting(self, setting_update: SettingUpdate) -> Dict[str, Any]:
        db_setting = self.repository.get_by_key(setting_update.key)
        if not db_setting:
            db_setting = Setting(key=setting_update.key, value=setting_update.value)
        else:
            db_setting.value = setting_update.value
            
        saved_setting = self.repository.save(db_setting)
        return {"key": saved_setting.key, "value": saved_setting.value}
