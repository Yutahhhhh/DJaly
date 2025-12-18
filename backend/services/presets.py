from typing import List, Optional, Dict, Any
from sqlmodel import Session, select, or_
from models import Preset, Prompt
from schemas.common import PresetCreate, PresetUpdate

class PresetService:
    def get_presets(self, session: Session, type: Optional[str] = None, strict: bool = False) -> List[Dict[str, Any]]:
        """
        プリセット一覧を取得する。
        strict=True の場合、指定された type と完全に一致するもののみを返す。
        strict=False (デフォルト) の場合、type='generation' でも 'all' (汎用) を含めて返す。
        """
        query = select(Preset)
        
        if type:
            if strict:
                query = query.where(Preset.preset_type == type)
            else:
                # 従来通りの挙動 (指定タイプ OR 'all')
                query = query.where(or_(Preset.preset_type == type, Preset.preset_type == "all"))
        
        presets = session.exec(query).all()
        
        result = []
        for p in presets:
            p_dict = p.dict()
            # Promptの内容を含める
            if p.prompt_id:
                prompt = session.get(Prompt, p.prompt_id)
                if prompt:
                    p_dict["prompt_content"] = prompt.content
            result.append(p_dict)
            
        return result

    def create_preset(self, session: Session, preset: PresetCreate) -> Dict[str, Any]:
        db_preset = Preset.from_orm(preset)
        session.add(db_preset)
        session.commit()
        session.refresh(db_preset)
        
        return db_preset.dict()

    def update_preset(self, session: Session, preset_id: int, preset: PresetUpdate) -> Optional[Dict[str, Any]]:
        db_preset = session.get(Preset, preset_id)
        if not db_preset:
            return None
        
        preset_data = preset.dict(exclude_unset=True)
        for key, value in preset_data.items():
            setattr(db_preset, key, value)
            
        session.add(db_preset)
        session.commit()
        session.refresh(db_preset)
        
        return db_preset.dict()

    def delete_preset(self, session: Session, preset_id: int) -> bool:
        db_preset = session.get(Preset, preset_id)
        if not db_preset:
            return False
            
        # 関連するPromptは削除しない（他のプリセットで使われている可能性があるため）
        # 必要ならPromptの参照カウントなどを管理するが、今回はシンプルにPresetのみ削除
        session.delete(db_preset)
        session.commit()
        return True
