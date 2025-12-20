from typing import List, Optional
from sqlmodel import Session, select, or_
from domain.models.preset import Preset

class PresetRepository:
    def __init__(self, session: Session):
        self.session = session

    def find_all(self, type: Optional[str] = None, strict: bool = False) -> List[Preset]:
        query = select(Preset)
        if type:
            if strict:
                query = query.where(Preset.preset_type == type)
            else:
                query = query.where(or_(Preset.preset_type == type, Preset.preset_type == "all"))
        return self.session.exec(query).all()

    def get_by_id(self, preset_id: int) -> Optional[Preset]:
        return self.session.get(Preset, preset_id)

    def create(self, preset: Preset) -> Preset:
        self.session.add(preset)
        self.session.commit()
        self.session.refresh(preset)
        return preset

    def update(self, preset: Preset) -> Preset:
        self.session.add(preset)
        self.session.commit()
        self.session.refresh(preset)
        return preset

    def delete(self, preset: Preset):
        self.session.delete(preset)
        self.session.commit()
