from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session
from infra.database.connection import get_session
from domain.models.prompt import Prompt
from api.schemas.common import PromptCreate, PromptUpdate
from app.services.prompt_app_service import PromptAppService

router = APIRouter()

@router.get("/api/prompts")
def get_prompts(session: Session = Depends(get_session)):
    service = PromptAppService(session)
    return service.get_prompts()

@router.post("/api/prompts")
def create_prompt(prompt: PromptCreate, session: Session = Depends(get_session)):
    service = PromptAppService(session)
    return service.create_prompt(prompt)

@router.put("/api/prompts/{prompt_id}")
def update_prompt(prompt_id: int, prompt: PromptUpdate, session: Session = Depends(get_session)):
    service = PromptAppService(session)
    db_prompt = service.update_prompt(prompt_id, prompt)
    if not db_prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return db_prompt

@router.delete("/api/prompts/{prompt_id}")
def delete_prompt(prompt_id: int, session: Session = Depends(get_session)):
    service = PromptAppService(session)
    success = service.delete_prompt(prompt_id)
    if not success:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return {"ok": True}
