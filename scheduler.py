from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session
from database import SessionLocal, Rule
from integrations import HomeAssistantClient, TTSClient
from minio_utils import minio_client
from sensor_polling import poll_homeassistant_sensors
import asyncio
import os

scheduler = AsyncIOScheduler()
ha_client = HomeAssistantClient()
tts_client = TTSClient()

def get_db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

async def execute_periodic_rule(rule_id: int):
    """
    Executes a periodic rule.
    For now, this assumes periodic rules might just be simple functionality like 
    "Say something" or "Check something generic".
    Visual checks require a camera input, which isn't naturally "periodic" unless we pull from a stream.
    """
    print(f"Executing periodic rule {rule_id}")
    # Logic to fetch rule and execute
    session = SessionLocal()
    try:
        rule = session.query(Rule).filter(Rule.id == rule_id).first()
        if not rule or not rule.enabled:
            return

        # Simple example: Just generic feedback/reminder
        # If we had access to a camera snapshot URL, we could grab it here.
        # But for now, let's assume it's a text/audio reminder.
        
        message = rule.feedback_template.format(result="Periodic Reminder")
        
        # Determine output (Audio via HA)
        # We need a temp path for audio
        output_path = f"/tmp/periodic_{rule_id}.mp3" 
        
        audio_file = await tts_client.generate_audio(message, output_path)
        if audio_file:
            pass
            
        print(f"Periodic rule {rule.name} executed: {message}")
        
    except Exception as e:
        print(f"Error executing periodic rule {rule_id}: {e}")
    finally:
        session.close()


def setup_scheduler():
    """
    Loads rules with schedules from DB and adds them to scheduler.
    """
    session = SessionLocal()
    try:
        rules = session.query(Rule).filter(Rule.schedule_cron.isnot(None), Rule.enabled == True).all()
        scheduler.remove_all_jobs()
        for rule in rules:
            if rule.schedule_cron:
                try:
                    scheduler.add_job(
                        execute_periodic_rule,
                        CronTrigger.from_crontab(rule.schedule_cron),
                        id=f"rule_{rule.id}",
                        args=[rule.id],
                        replace_existing=True
                    )
                    print(f"Scheduled rule '{rule.name}' with cron: {rule.schedule_cron}")
                except Exception as e:
                    print(f"Failed to schedule rule {rule.name}: {e}")
    finally:
        session.close()
    
    # Schedule the HA sensor polling every 30 seconds
    try:
        scheduler.add_job(
            poll_homeassistant_sensors,
            'interval',
            seconds=30,
            id="ha_sensor_polling",
            replace_existing=True
        )
        print("Scheduled HomeAssistant sensor polling loop.")
    except Exception as e:
        print(f"Failed to schedule HA polling loop: {e}")

    if not scheduler.running:
        scheduler.start()
