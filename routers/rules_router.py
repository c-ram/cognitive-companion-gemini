from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional

from database import get_db, Rule, RuleContext
from scheduler import setup_scheduler

router = APIRouter()

# --- Pydantic Models ---

class RuleCreate(BaseModel):
    name: str
    description: str = ""
    enabled: bool = True
    schedule_cron: Optional[str] = None
    vision_prompt: str = "Describe this image in detail."
    logic_prompt: str = "Based on the description, decide if an action is needed."
    gemini_live_prompt: str = "Prompt for Gemini Live response."
    feedback_template: str = "Notification: {result}"
    cool_off_minutes: int = 5
    max_daily_triggers: int = 3

class RuleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None
    schedule_cron: Optional[str] = None
    vision_prompt: Optional[str] = None
    logic_prompt: Optional[str] = None
    gemini_live_prompt: Optional[str] = None
    feedback_template: Optional[str] = None
    cool_off_minutes: Optional[int] = None
    max_daily_triggers: Optional[int] = None

class ContextCreate(BaseModel):
    context_type: str # 'time_range', 'room'
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    room_name: Optional[str] = None

# --- Routes ---

@router.get("/rules")
def get_rules(db: Session = Depends(get_db)):
    # Simple return, normally would use Pydantic response model but dict logic in app.py suggests simple return
    # SQLAlchemy objects are not dicts, but FastAPI handles them if we define response_model or just return list.
    # The previous code returned `rules` (list of Rule objects).
    rules = db.query(Rule).all()
    return rules

@router.post("/rules")
def create_rule(rule: RuleCreate, db: Session = Depends(get_db)):
    db_rule = Rule(**rule.dict())
    db.add(db_rule)
    db.commit()
    db.refresh(db_rule)
    # If cron is set, reschedule
    if db_rule.schedule_cron:
        setup_scheduler() # Reload scheduler
    return db_rule

@router.put("/rules/{rule_id}")
def update_rule(rule_id: int, rule: RuleUpdate, db: Session = Depends(get_db)):
    db_rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not db_rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    update_data = rule.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_rule, key, value)
    
    db.commit()
    db.refresh(db_rule)
    
    if "schedule_cron" in update_data or "enabled" in update_data:
        setup_scheduler()
        
    return db_rule

@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    db_rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not db_rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    db.delete(db_rule)
    db.commit()
    setup_scheduler()
    return {"status": "deleted"}

@router.get("/rules/{rule_id}/contexts")
def get_contexts(rule_id: int, db: Session = Depends(get_db)):
    contexts = db.query(RuleContext).filter(RuleContext.rule_id == rule_id).all()
    return contexts

@router.post("/rules/{rule_id}/context")
def add_context(rule_id: int, context: ContextCreate, db: Session = Depends(get_db)):
    db_rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not db_rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    db_context = RuleContext(**context.dict(), rule_id=rule_id)
    db.add(db_context)
    db.commit()
    db.refresh(db_context)
    return db_context

@router.delete("/rules/{rule_id}/context/{context_id}")
def delete_context(rule_id: int, context_id: int, db: Session = Depends(get_db)):
    db_context = db.query(RuleContext).filter(RuleContext.id == context_id, RuleContext.rule_id == rule_id).first()
    if not db_context:
        raise HTTPException(status_code=404, detail="Context not found")
        
    db.delete(db_context)
    db.commit()
    return {"status": "deleted"}

