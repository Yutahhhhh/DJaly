from typing import Dict, Any
from sqlmodel import Session
from domain.models.setting import Setting
from infra.repositories.setting_repository import SettingRepository
from api.schemas.common import SettingUpdate

RETIRED_LLM_SETTING_KEYS = {
    "llm_provider", "llm_model", "api_key", "openai_api_key",
    "anthropic_api_key", "google_api_key", "ollama_host", "codex_cli_path",
    "codex_timeout_seconds", "openai_model", "codex_model",
    "anthropic_model", "google_model", "ollama_model",
}
RETIRED_LLM_PROVIDERS = {"openai", "anthropic", "google", "ollama", "codex"}


def is_retired_llm_setting_key(key: str) -> bool:
    """Recognize legacy/future variants without hiding unrelated app settings."""
    normalized = (key or "").strip().lower()
    if normalized in RETIRED_LLM_SETTING_KEYS or normalized.startswith("llm_"):
        return True
    return any(
        normalized in {f"{provider}_model", f"{provider}_api_key"}
        for provider in RETIRED_LLM_PROVIDERS
    )

class SettingAppService:
    def __init__(self, session: Session):
        self.session = session
        self.repository = SettingRepository(session)

    def get_settings(self) -> Dict[str, Any]:
        settings = self.repository.find_all()
        return {s.key: s.value for s in settings if not is_retired_llm_setting_key(s.key)}

    def update_setting(self, setting_update: SettingUpdate) -> Dict[str, Any]:
        if is_retired_llm_setting_key(setting_update.key):
            raise ValueError(
                "Djaly no longer stores LLM credentials or model settings; "
                "AI reasoning is provided by the connected MCP client."
            )
        db_setting = self.repository.get_by_key(setting_update.key)
        if not db_setting:
            db_setting = Setting(key=setting_update.key, value=setting_update.value)
        else:
            db_setting.value = setting_update.value
            
        saved_setting = self.repository.save(db_setting)
        return {"key": saved_setting.key, "value": saved_setting.value}
