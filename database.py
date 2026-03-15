from sqlalchemy import create_engine, Column, Integer, String, Boolean, Text, ForeignKey, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime

# SQLite database setup
DATABASE_URL = "sqlite:///./nanai.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Sensor(Base):
    __tablename__ = "sensors"

    id = Column(String, primary_key=True, index=True) # sensor_id from payload
    name = Column(String, index=True)
    room_name = Column(String, index=True)
    type = Column(String, default="camera")
    enabled = Column(Boolean, default=True)

class Rule(Base):
    __tablename__ = "rules"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    description = Column(String)
    enabled = Column(Boolean, default=True)
    schedule_cron = Column(String, nullable=True) # e.g., "0 8 * * *"
    
    # Prompts
    vision_prompt = Column(Text, default="Describe this image in detail.")
    logic_prompt = Column(Text, default="Based on the description, decide if an action is needed.")
    feedback_template = Column(Text, default="{result}")
    gemini_live_prompt = Column(Text, default="{result}") # Prompt to generate live feedback for user in Tamil using Gemini Live API
    
    # Rate Limiting
    cool_off_minutes = Column(Integer, default=5) # Minutes to wait before re-triggering
    max_daily_triggers = Column(Integer, default=3) # Max times this rule can trigger per day
    
    contexts = relationship("RuleContext", back_populates="rule", cascade="all, delete-orphan")

class RuleContext(Base):
    __tablename__ = "rule_contexts"

    id = Column(Integer, primary_key=True, index=True)
    rule_id = Column(Integer, ForeignKey("rules.id"))
    context_type = Column(String) # 'time_range', 'room'
    
    # For time_range
    start_time = Column(String, nullable=True) # "HH:MM" 24hr format
    end_time = Column(String, nullable=True)   # "HH:MM" 24hr format
    
    # For room
    room_name = Column(String, nullable=True)

    rule = relationship("Rule", back_populates="contexts")

class EventLog(Base):
    __tablename__ = "event_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    rule_name = Column(String)
    sensor_id = Column(String)
    room_name = Column(String)
    media_path = Column(String)
    vision_response = Column(Text)
    logic_response = Column(Text)
    status = Column(String) # 'processed', 'failed', 'skipped'

class RoomOccupancy(Base):
    __tablename__ = "room_occupancy"

    id = Column(Integer, primary_key=True, index=True)
    sensor_id = Column(String, index=True)
    room_name = Column(String, index=True)
    start_time = Column(DateTime, default=datetime.utcnow)
    end_time = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)

class EmergencyAlert(Base):
    __tablename__ = "emergency_alerts"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    alert_type = Column(String) # e.g., 'bathroom_fall', 'loud_noise'
    description = Column(String)
    sensor_id = Column(String, nullable=True)
    room_name = Column(String, nullable=True)
    resolved = Column(Boolean, default=False)
    assistance_needed = Column(Boolean, default=False)

class ActiveImageState(Base):
    __tablename__ = "active_image_state"

    id = Column(Integer, primary_key=True, index=True)
    expires_at = Column(DateTime, nullable=True)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
