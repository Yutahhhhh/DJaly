from typing import List, Optional, Dict, Any
from sqlmodel import Session
from domain.models.preset import Preset
from infra.repositories.preset_repository import PresetRepository
from infra.repositories.prompt_repository import PromptRepository
from api.schemas.common import PresetCreate, PresetUpdate

class PresetAppService:
    def __init__(self, session: Session):
        self.session = session
        self.repository = PresetRepository(session)
        self.prompt_repository = PromptRepository(session)

    def get_presets(self, type: Optional[str] = None, strict: bool = False) -> List[Dict[str, Any]]:
        presets = self.repository.find_all(type, strict)
        
        result = []
        for p in presets:
            p_dict = p.model_dump()
            # Promptの内容を含める
            if p.prompt_id:
                prompt = self.prompt_repository.get_by_id(p.prompt_id)
                if prompt:
                    p_dict["prompt_content"] = prompt.content
            result.append(p_dict)
            
        return result

    def create_preset(self, preset: PresetCreate) -> Dict[str, Any]:
        db_preset = Preset.model_validate(preset)
        saved_preset = self.repository.create(db_preset)
        return saved_preset.model_dump()

    def update_preset(self, preset_id: int, preset: PresetUpdate) -> Optional[Dict[str, Any]]:
        db_preset = self.repository.get_by_id(preset_id)
        if not db_preset:
            return None
        
        preset_data = preset.model_dump(exclude_unset=True)
        for key, value in preset_data.items():
            setattr(db_preset, key, value)
            
        saved_preset = self.repository.update(db_preset)
        return saved_preset.model_dump()

    def delete_preset(self, preset_id: int) -> bool:
        db_preset = self.repository.get_by_id(preset_id)
        if not db_preset:
            return False
            
        self.repository.delete(db_preset)
        return True
