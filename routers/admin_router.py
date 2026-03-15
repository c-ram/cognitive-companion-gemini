from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import (
    get_db,
    EventLog,
    RoomOccupancy,
    EmergencyAlert,
    ActiveImageState,
)

router = APIRouter(prefix="/admin", tags=["admin"])


class EventLogUpdate(BaseModel):
    timestamp: Optional[datetime] = None
    rule_name: Optional[str] = None
    sensor_id: Optional[str] = None
    room_name: Optional[str] = None
    media_path: Optional[str] = None
    vision_response: Optional[str] = None
    logic_response: Optional[str] = None
    status: Optional[str] = None


class RoomOccupancyUpdate(BaseModel):
    sensor_id: Optional[str] = None
    room_name: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    is_active: Optional[bool] = None


class EmergencyAlertUpdate(BaseModel):
    timestamp: Optional[datetime] = None
    alert_type: Optional[str] = None
    description: Optional[str] = None
    sensor_id: Optional[str] = None
    room_name: Optional[str] = None
    resolved: Optional[bool] = None
    assistance_needed: Optional[bool] = None


class ActiveImageStateUpdate(BaseModel):
    expires_at: Optional[datetime] = None


@router.get("/event_logs")
def list_event_logs(db: Session = Depends(get_db)):
    return db.query(EventLog).order_by(EventLog.timestamp.desc()).all()


@router.put("/event_logs/{event_id}")
def update_event_log(event_id: int, payload: EventLogUpdate, db: Session = Depends(get_db)):
    record = db.query(EventLog).filter(EventLog.id == event_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Event log not found")
    update_data = payload.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(record, key, value)
    db.commit()
    db.refresh(record)
    return record


@router.delete("/event_logs/{event_id}")
def delete_event_log(event_id: int, db: Session = Depends(get_db)):
    record = db.query(EventLog).filter(EventLog.id == event_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Event log not found")
    db.delete(record)
    db.commit()
    return {"status": "deleted"}


@router.get("/room_occupancy")
def list_room_occupancy(db: Session = Depends(get_db)):
    return db.query(RoomOccupancy).order_by(RoomOccupancy.start_time.desc()).all()


@router.put("/room_occupancy/{occupancy_id}")
def update_room_occupancy(
    occupancy_id: int, payload: RoomOccupancyUpdate, db: Session = Depends(get_db)
):
    record = db.query(RoomOccupancy).filter(RoomOccupancy.id == occupancy_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Room occupancy record not found")
    update_data = payload.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(record, key, value)
    db.commit()
    db.refresh(record)
    return record


@router.delete("/room_occupancy/{occupancy_id}")
def delete_room_occupancy(occupancy_id: int, db: Session = Depends(get_db)):
    record = db.query(RoomOccupancy).filter(RoomOccupancy.id == occupancy_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Room occupancy record not found")
    db.delete(record)
    db.commit()
    return {"status": "deleted"}


@router.get("/emergency_alerts")
def list_emergency_alerts(db: Session = Depends(get_db)):
    return db.query(EmergencyAlert).order_by(EmergencyAlert.timestamp.desc()).all()


@router.put("/emergency_alerts/{alert_id}")
def update_emergency_alert(
    alert_id: int, payload: EmergencyAlertUpdate, db: Session = Depends(get_db)
):
    record = db.query(EmergencyAlert).filter(EmergencyAlert.id == alert_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Emergency alert not found")
    update_data = payload.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(record, key, value)
    db.commit()
    db.refresh(record)
    return record


@router.delete("/emergency_alerts/{alert_id}")
def delete_emergency_alert(alert_id: int, db: Session = Depends(get_db)):
    record = db.query(EmergencyAlert).filter(EmergencyAlert.id == alert_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Emergency alert not found")
    db.delete(record)
    db.commit()
    return {"status": "deleted"}


@router.get("/active_image_state")
def list_active_image_state(db: Session = Depends(get_db)):
    return db.query(ActiveImageState).all()


@router.put("/active_image_state/{state_id}")
def update_active_image_state(
    state_id: int, payload: ActiveImageStateUpdate, db: Session = Depends(get_db)
):
    record = db.query(ActiveImageState).filter(ActiveImageState.id == state_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Active image state not found")
    update_data = payload.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(record, key, value)
    db.commit()
    db.refresh(record)
    return record


@router.delete("/active_image_state/{state_id}")
def delete_active_image_state(state_id: int, db: Session = Depends(get_db)):
    record = db.query(ActiveImageState).filter(ActiveImageState.id == state_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Active image state not found")
    db.delete(record)
    db.commit()
    return {"status": "deleted"}
