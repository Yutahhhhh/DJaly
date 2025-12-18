from typing import List, Optional
from sqlmodel import Session, select
from models import Prompt
from schemas.common import PromptCreate, PromptUpdate

class PromptService:
    def get_prompts(self, session: Session) -> List[Prompt]:
        prompts = session.exec(select(Prompt)).all()
        return prompts

    def create_prompt(self, session: Session, prompt: PromptCreate) -> Prompt:
        db_prompt = Prompt.from_orm(prompt)
        session.add(db_prompt)
        session.commit()
        session.refresh(db_prompt)
        return db_prompt

    def update_prompt(self, session: Session, prompt_id: int, prompt: PromptUpdate) -> Optional[Prompt]:
        db_prompt = session.get(Prompt, prompt_id)
        if not db_prompt:
            return None
        
        prompt_data = prompt.dict(exclude_unset=True)
        for key, value in prompt_data.items():
            setattr(db_prompt, key, value)
            
        session.add(db_prompt)
        session.commit()
        session.refresh(db_prompt)
        return db_prompt

    def delete_prompt(self, session: Session, prompt_id: int) -> bool:
        db_prompt = session.get(Prompt, prompt_id)
        if not db_prompt:
            return False
        session.delete(db_prompt)
        session.commit()
        return True
