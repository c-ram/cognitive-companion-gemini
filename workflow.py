import asyncio
import os
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session
from typing import List, Optional
import json
import time

from database import SessionLocal, Rule, RuleContext, Sensor, EventLog
from integrations import TTSClient, HomeAssistantClient, WhatsAppClient, EmailToSMSClient
from utils import call_vllm_cosmos, call_gemma, call_vllm_translate
from routers.image_router import generate_alert_image
from routers.ws_router import manager
import uuid
from minio_utils import minio_client

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Clients
tts_client = TTSClient()
ha_client = HomeAssistantClient()
wa_client = WhatsAppClient()
email_sms_client = EmailToSMSClient()

# Env
VLLM_COSMOS_URL = os.getenv("VLLM_COSMOS_API_URL")
VLLM_TRANSLATE_URL = os.getenv("VLLM_TRANSLATE_API_URL")
OLLAMA_API_URL = os.getenv("OLLAMA_API_URL")

async def process_event(sensor_id_or_name: str, media_paths: List[str], media_type: str = "image"):
    """
    Main entry point for processing a camera/sensor event.
    Accepts a list of media paths for batch processing.
    """
    logger.info(f"Processing event from {sensor_id_or_name} with {len(media_paths)} items")
    session = SessionLocal()
    try:
        # 0. Lookup Sensor/Room
        sensor = session.query(Sensor).filter(
            (Sensor.id == sensor_id_or_name) | (Sensor.name == sensor_id_or_name)
        ).first()
        
        if not sensor:
            logger.info(f"Sensor {sensor_id_or_name} not found or not mapped.")
            # Optional: Auto-create sensor entry?
            return 

        if not sensor.enabled:
            logger.info(f"Sensor {sensor.name} is disabled.")
            return

        room_name = sensor.room_name
        logger.info(f"Sensor {sensor.name} is in room {room_name}")

        # 1. Fetch Active Rules
        # Filter by Room Context and Time Context
        # This is a bit complex in SQL, so we can fetch potential rules and filter in python for flexibility
        # Or do a join.
        
        # Simple approach: Fetch all enabled rules, then check contexts.
        rules = session.query(Rule).filter(Rule.enabled == True).all()
        
        matched_rules = []
        now = datetime.now(ZoneInfo("America/New_York"))
        current_time_str = now.strftime("%H:%M")
        
        for rule in rules:
            # Check contexts
             # If no contexts, does it apply always? Let's assume rules MUST have context to apply to specific triggers.
             # Or maybe "Global" rules.
             
             # Context Logic: OR between different contexts types? AND?
             # Let's assume: If Room context exists, must match. If Time context exists, must match.
             
             contexts = rule.contexts
             room_match = True
             time_match = True
             
             # Check if there are room contexts
             room_contexts = [c for c in contexts if c.context_type == 'room']
             if room_contexts:
                 # Must match at least one
                 room_match = any(c.room_name.lower() == room_name.lower() for c in room_contexts)
             
             # Check if there are time contexts
             time_contexts = [c for c in contexts if c.context_type == 'time_range']
             if time_contexts:
                 # Must match at least one
                 time_match = False
                 for tc in time_contexts:
                     if tc.start_time <= current_time_str <= tc.end_time:
                         time_match = True
                         break
             
             if room_match and time_match:
                 matched_rules.append(rule)

        logger.info(f"Matched {len(matched_rules)} rules.")

        # 2. Execute Rules
        tasks = []
        now_utc = datetime.utcnow()
        
        for rule in matched_rules:
            # Rate Limiting Logic
            # Check Cool-off
            if rule.cool_off_minutes > 0:
                last_run = session.query(EventLog).filter(
                    EventLog.rule_name == rule.name,
                    EventLog.status == 'completed'
                ).order_by(EventLog.timestamp.desc()).first()
                
                if last_run:
                    time_since_last = (now_utc - last_run.timestamp).total_seconds() / 60
                    if time_since_last < rule.cool_off_minutes:
                        logger.info(f"Rule {rule.name} skipped due to cool-off. Time since last: {time_since_last:.2f}m, Cool-off: {rule.cool_off_minutes}m")
                        continue
            
            # Check Daily Limit
            if rule.max_daily_triggers > 0:
                start_of_day = datetime(now_utc.year, now_utc.month, now_utc.day)
                daily_count = session.query(EventLog).filter(
                    EventLog.rule_name == rule.name,
                    EventLog.status == 'completed',
                    EventLog.timestamp >= start_of_day
                ).count()
                
                if daily_count >= rule.max_daily_triggers:
                    logger.info(f"Rule {rule.name} skipped due to daily limit. Count: {daily_count}, Limit: {rule.max_daily_triggers}")
                    continue

            tasks.append(execute_rule_pipeline(rule, sensor, media_paths, media_type, session))
            
        if tasks:
            await asyncio.gather(*tasks)

    except Exception as e:
        logger.error(f"Error in process_event: {e}")
    finally:
        session.close()

async def execute_rule_pipeline(rule: Rule, sensor: Sensor, media_paths: List[str], media_type: str, session: Session):
    """
    Executes a single rule pipeline.
    """
    rule_name = rule.name
    logger.info(f"Executing Rule: {rule_name}")
    
    # Use the first media path for logging/thumbnail purposes if needed
    primary_media_path = media_paths[0] if media_paths else ""
    
    log_entry = EventLog(
        rule_name=rule_name,
        sensor_id=sensor.id,
        room_name=sensor.room_name,
        media_path=primary_media_path,
        status="processing"
    )
    session.add(log_entry)
    session.commit()
    
    try:
        # Step 1: Vision LLM (Cosmos)
        vision_prompt = rule.vision_prompt
        # Pass list of media paths to VLLM
        vision_response = await call_vllm_cosmos(VLLM_COSMOS_URL, vision_prompt, media_paths=media_paths, media_type=media_type, thinking=True)
        
        vision_text = str(vision_response)

        print(f"Vision Prompt: {vision_prompt}")
        print(f"Vision Response: {vision_text}")

        log_entry.vision_response = vision_text
        session.commit()
        
        # Step 2: Logic LLM (Ollama)
        # We need a client for Ollama. Let's use call_vllm_cosmos pointing to Ollama or a new helper.
        # Ollama usually is compatible with OpenAI API.
        
        logic_prompt = rule.logic_prompt
        now = datetime.now(ZoneInfo("America/New_York"))
        current_time_str = now.strftime("%H:%M")
        full_logic_prompt = f"""
        Context: Room {sensor.room_name}, Time(24hr format) {current_time_str}.

        Visual Response: {vision_text}
        
        Rule: {logic_prompt}
        
        Analyze the situation and decide if action is needed. 
        """
        
        # Re-using call_vllm_cosmos for Ollama as it is OpenAI compatible usually
        logic_response_data = await call_gemma(OLLAMA_API_URL, full_logic_prompt)
        
        logic_text = str(logic_response_data)
            
        log_entry.logic_response = logic_text
        session.commit()

        print(f"Full Logic Prompt: {full_logic_prompt}")
        print(f"Logic Response: {logic_text}")

        logic_response_json = json.loads(logic_text)

        if not logic_response_json.get("is_notification_needed", True):
            log_entry.status = "ignored"
            session.commit()
            print(f"Exiting Workflow. No notification required")
            return
        
        # Step 3: Action Decision
        # Heuristic: Check if logic_text indicates affirmative or contains specific keywords.
        # Or better, ask Ollama to output JSON.
        
        # For now, let's assume we proceed if logic_text is not empty.
        # We generate user-facing feedback.
        
        feedback_template = rule.feedback_template

        feedback_message = feedback_template.replace("{result}", logic_response_json["user_notification"])
        
        feedback_message_ta = await call_vllm_translate(VLLM_TRANSLATE_URL, feedback_message)
        # Step 4: Visual Alert & TTS & Notification
        
        # Generate Visual Alert (Image)
        try:
            generate_alert_image(
                text=feedback_message+" \n\n"+feedback_message_ta,
                expires_in_minutes=5,
                bbox=(750, 430),
                font_name="NotoSansTamil-Regular.ttf",
                db=session
            )
        except Exception as e:
            logger.error(f"Failed to generate visual alert: {e}")

        # Generate Audio in English for demo purposes.
        # await ha_client.play_message_as_audio(feedback_message, voice="en-IN-NeerjaExpressiveNeural", speed=0.85)
        # time.sleep(13)
        # Generate Audio in Tamil
        #await ha_client.play_message_as_audio(feedback_message_ta, voice="ta-IN-PallaviNeural", speed=0.85)
        logger.info(f"Generated Audio in Tamil: {feedback_message_ta}")
        # Enqueue a text prompt to Gemini Live API
        async def gemini_callback(response_text: str):
            logger.info(f"Received text from Gemini Live API internal task: {response_text}")
            #log_entry.gemini_response = response_text
            #session.commit()
        
        logger.info(f"Sending Gemini task: {feedback_message}")

        push_payload = {
            "type": "warning",
            "message": feedback_message,
            "room": sensor.room_name
        }
        await manager.broadcast(push_payload)

        gemini_template = rule.gemini_live_prompt
        gemini_prompt = gemini_template.replace("{result}", feedback_message)

        #gemini_prompt = f"The following feedback notification was generated by a vision AI system. Translate the notification to colloquial Tamil and read the translated notification to the user. Notification: {feedback_message}."
        await manager.send_gemini_task(prompt=gemini_prompt, callback=gemini_callback)
        
        # Notify WhatsApp
        # caretakers = ["+1234567890"] # Should be in config or DB
        # for number in caretakers:
        #    await wa_client.send_message(number, f"Alert from {sensor.room_name}: {feedback_message}\n\nAnalysis: {logic_text}")
        #
        # Email-to-SMS (e.g., 10digit@tmomail.net)
        # caretakers_sms = ["1234567890@tmomail.net"] # Should be in config or DB
        # for to_email in caretakers_sms:
        #    await email_sms_client.send_message(to_email, f"Alert from {sensor.room_name}: {feedback_message}")

        log_entry.status = "completed"
        session.commit()
        print(f"Exiting Workflow. Notification sent successfully")
    except Exception as e:
        logger.error(f"Rule execution failed: {e}")
        log_entry.status = "failed"
        session.commit()
