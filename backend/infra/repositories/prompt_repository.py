from typing import List, Optional
from sqlmodel import Session, select
from domain.models.prompt import Prompt

class PromptRepository:
    def __init__(self, session: Session):
        self.session = session

    def find_all(self) -> List[Prompt]:
        return self.session.exec(select(Prompt)).all()

    def get_by_id(self, prompt_id: int) -> Optional[Prompt]:
        return self.session.get(Prompt, prompt_id)

    def create(self, prompt: Prompt) -> Prompt:
        self.session.add(prompt)
        self.session.commit()
        self.session.refresh(prompt)
        return prompt

    def update(self, prompt: Prompt) -> Prompt:
        self.session.add(prompt)
        self.session.commit()
        self.session.refresh(prompt)
        return prompt

    def delete(self, prompt: Prompt):
        self.session.delete(prompt)
        self.session.commit()
