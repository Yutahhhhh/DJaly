from typing import List, Optional
from sqlmodel import Session
from domain.models.prompt import Prompt
from infra.repositories.prompt_repository import PromptRepository
from api.schemas.common import PromptCreate, PromptUpdate

class PromptAppService:
    def __init__(self, session: Session):
        self.session = session
        self.repository = PromptRepository(session)

    def get_prompts(self) -> List[Prompt]:
        return self.repository.find_all()

    def create_prompt(self, prompt: PromptCreate) -> Prompt:
        db_prompt = Prompt.model_validate(prompt)
        return self.repository.create(db_prompt)

    def update_prompt(self, prompt_id: int, prompt: PromptUpdate) -> Optional[Prompt]:
        db_prompt = self.repository.get_by_id(prompt_id)
        if not db_prompt:
            return None
        
        prompt_data = prompt.model_dump(exclude_unset=True)
        for key, value in prompt_data.items():
            setattr(db_prompt, key, value)
            
        return self.repository.update(db_prompt)

    def delete_prompt(self, prompt_id: int) -> bool:
        db_prompt = self.repository.get_by_id(prompt_id)
        if not db_prompt:
            return False
        self.repository.delete(db_prompt)
        return True
