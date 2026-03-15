import asyncio
import logging
from datetime import datetime, timedelta
from database import SessionLocal, RoomOccupancy, EmergencyAlert, Sensor
from routers.ws_router import manager as ws_manager
from integrations import HomeAssistantClient

logger = logging.getLogger(__name__)

# Mock settings for HomeAssistant
# Removed HA_API_URL and HA_TOKEN as they are now handled by HomeAssistantClient

BATHROOM_TIME_LIMIT_MINUTES = 2 # Alerts if in bathroom for over 30 mins

async def poll_homeassistant_sensors():
    """
    Periodically checks the status of MR60BHA2 sensors (Breathing/Heartbeat)
    from HomeAssistant to track RoomOccupancy and catch anomalies.
    """
    logger.info("Polling HomeAssistant sensors for occupancy")
    try:
        session = SessionLocal()
        sensors = session.query(Sensor).filter(Sensor.type == "presence", Sensor.enabled == True).all()
        if not sensors:
            session.close()
            return

        ha_client = HomeAssistantClient()

        for sensor in sensors:
            try:
                # Poll both entities using HomeAssistantClient
                person_info_state = await ha_client.get_person_info_state(sensor.id)
                distance_state = await ha_client.get_distance_entity_state(sensor.id)
                
                logger.info(f"Person info state for sensor {sensor.id}: {person_info_state}")
                logger.info(f"Distance state for sensor {sensor.id}: {distance_state}")
                
                # Given there is no real HA right now or if HA is down, we wrap in a fallback mock state
                state = person_info_state if person_info_state is not None else "on"
                
                # Track occupancy
                active_occupancy = session.query(RoomOccupancy).filter(
                    RoomOccupancy.sensor_id == sensor.id,
                    RoomOccupancy.is_active == True
                ).first()

                if state == "on":
                    if not active_occupancy:
                        new_occupancy = RoomOccupancy(
                            sensor_id=sensor.id,
                            room_name=sensor.room_name,
                            start_time=datetime.utcnow(),
                            is_active=True
                        )
                        session.add(new_occupancy)
                        session.commit()
                    else:
                        # Check if the duration exceeds limit for bathroom
                        duration = datetime.utcnow() - active_occupancy.start_time
                        if sensor.room_name.lower() == "bathroom" and duration > timedelta(minutes=BATHROOM_TIME_LIMIT_MINUTES):
                            # Ensure we haven't already alerted for this session
                            existing_alert = session.query(EmergencyAlert).filter(
                                EmergencyAlert.sensor_id == sensor.id,
                                EmergencyAlert.room_name == sensor.room_name,
                                EmergencyAlert.resolved == False
                            ).first()

                            if not existing_alert:
                                alert = EmergencyAlert(
                                    alert_type="bathroom_time_exceeded",
                                    description=f"Person has been in the {sensor.room_name} for over {BATHROOM_TIME_LIMIT_MINUTES} minutes.",
                                    sensor_id=sensor.id,
                                    room_name=sensor.room_name
                                )
                                session.add(alert)
                                session.commit()
                                
                                # Push to UI using websocket watchdog
                                push_payload = {
                                    "type": "emergency_alert",
                                    "alert_id": alert.id,
                                    "message": alert.description,
                                    "room": sensor.room_name
                                }
                                await ws_manager.broadcast(push_payload)

                                async def gemini_callback(response_text: str):
                                    logger.info(f"Received text from Gemini Live API internal task: {response_text}")

                                gemini_prompt = f"The following emergency alert was generated: {alert.description}. Ask the user if they need assistance and if so, click on the \"need assistance\" button in the app to notify caregivers. Ask in simple colloquial Tamil."
                                await ws_manager.send_gemini_task(prompt=gemini_prompt, callback=gemini_callback)
                                logger.warning(f"Generated emergency alert: {alert.description}")

                elif state == "off" and active_occupancy:
                    active_occupancy.end_time = datetime.utcnow()
                    active_occupancy.is_active = False
                    session.commit()

            except Exception as e:
                logger.error(f"Error connecting to HA for sensor {sensor.id}: {e}")

    except Exception as e:
        logger.error(f"Error in HA polling loop: {e}")
    finally:
        session.close()
