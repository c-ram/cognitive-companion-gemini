import os
import uuid
import shutil
import asyncio
import logging
import base64
import time
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from config import settings
from utils import process_video, call_vllm_cosmos, get_video_info, call_vllm_translate
from database import init_db, SessionLocal, EmergencyAlert
from scheduler import setup_scheduler
from event_aggregator import EventAggregator
from minio_utils import minio_client

# --- Routers ---
from routers.rules_router import router as rules_api_router
from routers.sensors_router import router as sensors_api_router
from routers.image_router import router as image_api_router
from routers.admin_router import router as admin_api_router
from routers.stream_router import router as stream_api_router
from routers.ws_router import router as ws_api_router

from integrations import EmailToSMSClient

# --- Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Lifecycle ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    setup_scheduler()
    yield

app = FastAPI(lifespan=lifespan)

cors_origins = [
    "https://domain.com",
    "http://domain.com",
]
cors_env = os.getenv("CORS_ALLOW_ORIGINS", "")
if cors_env:
    cors_origins = [origin.strip() for origin in cors_env.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(rules_api_router)
app.include_router(sensors_api_router)
app.include_router(image_api_router)
app.include_router(admin_api_router)
app.include_router(stream_api_router)
app.include_router(ws_api_router)

# --- State ---
event_aggregator = EventAggregator(batch_size=3, window_seconds=10, cooldown_seconds=60)

# --- Models ---
class TranslationRequest(BaseModel):
    prompt: str = Field(..., min_length=1)

class EmergencyAlertAction(BaseModel):
    action: str = Field(..., min_length=1)

# -- Clients ---
email_sms_client = EmailToSMSClient()

# --- Endpoints ---
@app.post("/recamera")
async def handle_recamera_event(request: Request):
    try:
        payload = await request.json()
        data = payload.get("data", {})
        
        sensor_id = "recamera-001"
        media_path = None

        image_b64 = data.get("image")
        if image_b64:
            try:
                image_data = base64.b64decode(image_b64)
                object_name = f"recamera_{int(time.time())}_{uuid.uuid4().hex[:8]}.jpg"
                
                media_path = minio_client.upload_bytes(
                    image_data, 
                    object_name, 
                    content_type="image/jpeg"
                )
                logger.info(f"Uploaded recamera image: {object_name}")
            except Exception as e:
                logger.error(f"Failed to process recamera image: {e}")

        await event_aggregator.add_event(sensor_id, media_path)
             
    except Exception as e:
        logger.error(f"Error parsing recamera payload: {e}")
        return JSONResponse(status_code=400, content={"status": "error", "message": "Invalid payload"})

    return {"status": "ok"}

@app.post("/emergency_alerts/{alert_id}/action")
async def handle_emergency_alert_action(alert_id: int, payload: EmergencyAlertAction):
    action = payload.action.strip().lower()
    if action not in {"dismiss", "assist"}:
        raise HTTPException(status_code=400, detail="Invalid action. Use 'dismiss' or 'assist'.")

    session = SessionLocal()
    try:
        alert = session.query(EmergencyAlert).filter(EmergencyAlert.id == alert_id).first()
        if not alert:
            raise HTTPException(status_code=404, detail="Emergency alert not found.")

        if action == "dismiss":
            alert.resolved = True
            alert.assistance_needed = False
        elif action == "assist":
            alert.assistance_needed = True
            caretakers_sms = ["sriram@khoofia.com"] # Should be in config or DB
            for to_email in caretakers_sms:
                await email_sms_client.send_message(to_email, f"Assistance needed for alert: {alert.description}. Room: {alert.room_name}")

        session.commit()
        session.refresh(alert)
        return {
            "status": "ok",
            "alert_id": alert.id,
            "resolved": alert.resolved,
            "assistance_needed": alert.assistance_needed
        }
    finally:
        session.close()


@app.post("/analyze")
async def analyze_media(
    prompt: str = "Describe this content.",
    file: UploadFile = File(...)
):
    request_id = uuid.uuid4().hex
    ext = Path(file.filename).suffix.lower()
    input_path = settings.TEMP_DIR / f"{request_id}_in{ext}"
    processed_path = settings.TEMP_DIR / f"{request_id}_out.mp4"
    
    try:
        with input_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        is_video = ext in ['.mp4', '.mov', '.avi', '.mkv', '.webm']
        media_type = "video" if is_video else "image"
        final_media_path = str(input_path)
        object_name = f"{request_id}{ext}"
        
        if is_video:
            object_name = f"{request_id}_processed.mp4"
            await asyncio.to_thread(process_video, str(input_path), str(processed_path))
            final_media_path = str(processed_path)
            
            video_info = await asyncio.to_thread(get_video_info, final_media_path)
            logger.info(f"Video metadata: {video_info}")
            
        # Upload and call analysis engine
        await asyncio.to_thread(minio_client.upload_file, final_media_path, object_name)
        
        result = await call_vllm_cosmos(
            settings.VLLM_COSMOS_URL, 
            prompt, 
            media_paths=[final_media_path], 
            media_type=media_type
        )
        return {"result": result}

    except Exception as e:
        logger.exception("Analysis failed")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        for p in [input_path, processed_path]:
            if p.exists():
                p.unlink()


@app.post("/translate")
async def translate_text(request: TranslationRequest):
    try:
        result = await call_vllm_translate(settings.VLLM_TRANSLATE_URL, request.prompt)
        if "error" in result:
             raise HTTPException(status_code=500, detail=result["error"])
        logger.info(f"Translation result: {result}")
        return {"result": result}
    except Exception as e:
        logger.error(f"Translation failed: {e}")
        raise HTTPException(status_code=500, detail="Translation service error")
