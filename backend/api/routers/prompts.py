from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session
from db import get_session
from models import Prompt
from schemas.common import PromptCreate, PromptUpdate
from services.prompts import PromptService

router = APIRouter()
prompt_service = PromptService()

@router.get("/api/prompts")
def get_prompts(session: Session = Depends(get_session)):
    return prompt_service.get_prompts(session)

@router.post("/api/prompts")
def create_prompt(prompt: PromptCreate, session: Session = Depends(get_session)):
    return prompt_service.create_prompt(session, prompt)

@router.put("/api/prompts/{prompt_id}")
def update_prompt(prompt_id: int, prompt: PromptUpdate, session: Session = Depends(get_session)):
    db_prompt = prompt_service.update_prompt(session, prompt_id, prompt)
    if not db_prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return db_prompt

@router.delete("/api/prompts/{prompt_id}")
def delete_prompt(prompt_id: int, session: Session = Depends(get_session)):
    success = prompt_service.delete_prompt(session, prompt_id)
    if not success:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return {"ok": True}
