import os
import json
import asyncio
import logging
import time
from typing import List, Dict, Any, Tuple, Callable, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from google import genai
from google.genai import types

from config import settings

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")


router = APIRouter(prefix="/ws", tags=["websocket"])

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.prompt_queue = asyncio.Queue()
        self.current_callback = None
        self.current_text = ""
        self.current_transcript = ""

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"New client connected. Total connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"Client disconnected. Total connections: {len(self.active_connections)}")

    async def broadcast(self, command: Dict[str, Any]):
        """
        Broadcast a command or notification to all active clients (Watchdog push mechanism)
        """
        disconnected = []
        for connection in self.active_connections:
            try:
                payload = {"type": "command", **command}
                if payload.get("type") == "emergency_alert" and "alert_id" not in payload and "id" in payload:
                    payload["alert_id"] = payload["id"]
                await connection.send_json(payload)
            except Exception as e:
                logger.error(f"Failed to send to client: {e}")
                disconnected.append(connection)

        for conn in disconnected:
            self.disconnect(conn)

    async def send_gemini_task(self, prompt: str, callback: Optional[Callable[[str], None]] = None):
        """
        Enqueues a task for the Gemini Live API.
        The task will be picked up by the first available web socket connection.
        If no connection picks it up within 5 minutes, it will expire and be dropped.
        """
        expiration_time = time.time() + 300  # 5 minutes
        await self.prompt_queue.put((prompt, callback, expiration_time))
        logger.info(f"Queued new Gemini task. Queue size: {self.prompt_queue.qsize()}")


manager = ConnectionManager()

# Initialize Gemini Client if API key is present
client = genai.Client(api_key=GEMINI_API_KEY, http_options={"api_version": "v1alpha"}) if GEMINI_API_KEY else None

MODEL_ID = "gemini-2.5-flash-native-audio-preview-12-2025"

BASE_SYSTEM_INSTRUCTION = (
    "The user is a senior citizen living in Knoxville, Tennessee. They are originally from India. They may have limited mobility and may not be tech-savvy. "
    "Process and respond in either simple English (Tamil accent), or in simple Chennai Tamil or  "
    "Tanglish (a mix of Tamil spoken in Chennai mixed with English words)."
    "DO NOT use any other languages or accents. Keep responses concise and easy to understand."
    "DO NOT infer the emotional state of the user. If the user shares an emotional state, reflect it back in your response but do not add any inferred emotions of your own."
    "Ignore Minimal Input such as '...' or 'um' unless the user explicitly says to interpret them."
)

# How long to wait with no activity before sending a keepalive (seconds).
# Gemini Live typically times out after ~60s of silence; ping at half that.
KEEPALIVE_INTERVAL = 25

def build_gemini_config(conversation_history: str = "") -> dict:
    """
    Build the Gemini session config, optionally injecting a prior conversation
    summary so context survives across reconnects.
    """
    system_text = BASE_SYSTEM_INSTRUCTION
    if conversation_history:
        system_text += (
            "\n\nThis is a RESUMED conversation. Here is the transcript of what was discussed so far "
            "— use it to maintain full context and continuity:\n\n"
            + conversation_history
        )
    return {
        "response_modalities": ["AUDIO"],
        "system_instruction": {"parts": [{"text": system_text}]},
        "proactivity": {"proactive_audio": True},
        "enable_affective_dialog": True,
        "output_audio_transcription": {},
        "input_audio_transcription": {}
    }


@router.websocket("/audio")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)

    # Queue for audio/text chunks coming from the client, forwarded to the Gemini session.
    # Decoupling this from the Gemini session allows us to reconnect Gemini without
    # losing the client connection.
    client_to_gemini_queue: asyncio.Queue = asyncio.Queue()

    # Signals to coordinate shutdown
    client_disconnected = asyncio.Event()

    # ------------------------------------------------------------------ #
    # Task 1 – Permanently reads from the client WebSocket.               #
    # Only exits on a genuine WebSocketDisconnect; all other errors are   #
    # logged and ignored so the connection stays alive.                   #
    # ------------------------------------------------------------------ #
    async def receive_from_client():
        try:
            while True:
                msg = await websocket.receive()
                if "bytes" in msg:
                    await client_to_gemini_queue.put(("audio", msg["bytes"]))
                elif "text" in msg:
                    data = json.loads(msg["text"])
                    if data.get("type") == "end_of_turn":
                        logger.info("Received end_of_turn from client.")
                        await client_to_gemini_queue.put(("end_of_turn", None))
        except WebSocketDisconnect:
            logger.info("Client WebSocket disconnected.")
            client_disconnected.set()
        except Exception as e:
            logger.error(f"Unexpected error reading from client: {e}")
            client_disconnected.set()

    # ------------------------------------------------------------------ #
    # Gemini session runner – reconnects automatically when the Gemini    #
    # session drops, until the client itself disconnects.                 #
    # Context is preserved across reconnects via a rolling transcript     #
    # injected into the system prompt of each new session.               #
    # A periodic keepalive ping prevents idle-timeout disconnects.        #
    # ------------------------------------------------------------------ #
    async def run_gemini_session():
        """Runs (and restarts) the Gemini Live session until the client disconnects."""

        RETRY_DELAY = 2  # seconds between reconnect attempts

        # Rolling conversation log — survives reconnects.
        # Each entry: {"user": "...", "assistant": "..."}
        # We keep the last 40 turns to stay well within context limits.
        conversation_log: list[dict] = []

        # Buffers for the in-progress turn (reset each turn_complete)
        pending_user_text: list[str] = []
        pending_prompt_text: list[str] = []
        pending_assistant_text: list[str] = []

        def get_history_text() -> str:
            lines = []
            for turn in conversation_log[-40:]:
                if turn.get("user"):
                    lines.append(f"User: {turn['user']}")
                if turn.get("assistant"):
                    lines.append(f"Assistant: {turn['assistant']}")
            return "\n".join(lines)

        while not client_disconnected.is_set():
            try:
                config = build_gemini_config(get_history_text())
                async with client.aio.live.connect(model=MODEL_ID, config=config) as session:
                    logger.info("Connected to Gemini Live session.")
                    await websocket.send_json({"type": "status", "message": "gemini_connected"})

                    # Track last activity time to drive the keepalive
                    last_activity: list[float] = [time.time()]

                    # -------------------------------------------------- #
                    # Inner task A – forwards client chunks → Gemini      #
                    # -------------------------------------------------- #
                    async def forward_to_gemini():
                        while True:
                            kind, payload = await client_to_gemini_queue.get()
                            last_activity[0] = time.time()
                            if kind == "audio":
                                # await session.send(
                                #     input={"data": payload, "mime_type": "audio/pcm"},
                                #     end_of_turn=False,
                                # )
                                await session.send_realtime_input(
                                    audio=types.Blob(
                                        data=payload,
                                        mime_type="audio/pcm"
                                    )
                                )
                            elif kind == "end_of_turn":
                                logger.info("Sent end_of_turn signal to Gemini.")
                                # await session.send(input="", end_of_turn=True)
                            elif kind == "prompt":
                                text, callback, exp = payload
                                if time.time() > exp:
                                    logger.info(f"Dropped expired backend prompt: {text[:50]}…")
                                    continue
                                logger.info(f"Sending backend prompt to Gemini: {text[:50]}…")
                                manager.current_callback = callback
                                pending_prompt_text.append(text)
                                await session.send_realtime_input(text=text)

                    # -------------------------------------------------- #
                    # Inner task B – receives Gemini responses → client   #
                    # -------------------------------------------------- #
                    async def receive_from_gemini():
                        async for response in session.receive():
                            last_activity[0] = time.time()
                            server_content = response.server_content
                            if server_content is None:
                                continue

                            model_turn = server_content.model_turn
                            if model_turn:
                                for part in model_turn.parts:
                                    if part.inline_data:
                                        await websocket.send_bytes(part.inline_data.data)
                                    # if part.text:
                                    #     pending_assistant_text.append(part.text)
                                    #     if manager.current_callback is not None:
                                    #         manager.current_text += part.text
                                    #     await websocket.send_json({
                                    #         "type": "transcript",
                                    #         "source": "system",
                                    #         "text": part.text,
                                    #     })

                            if server_content.output_transcription:
                                chunk = server_content.output_transcription.text
                                manager.current_transcript += chunk
                                manager.current_text += chunk
                                pending_assistant_text.append(chunk)
                            if server_content.input_transcription:
                                chunk = server_content.input_transcription.text
                                manager.current_transcript += chunk
                                pending_user_text.append(chunk)

                            if server_content.turn_complete:
                                logger.info("Gemini turn complete.")
                                pending_user_text.extend(pending_prompt_text)
                                # Commit this turn to the persistent conversation log
                                conversation_log.append({
                                    "user": "".join(pending_user_text).strip(),
                                    "assistant": "".join(pending_assistant_text).strip(),
                                })
                                if len(pending_user_text)>0:
                                    await websocket.send_json({
                                        "type": "transcript",
                                        "source": "user",
                                        "text": "".join(pending_user_text).strip(),
                                    })
                                if len(pending_assistant_text)>0:
                                    await websocket.send_json({
                                        "type": "transcript",
                                        "source": "system",
                                        "text": "".join(pending_assistant_text).strip(),
                                    })
                                pending_user_text.clear()
                                pending_assistant_text.clear()
                                pending_prompt_text.clear()
                                manager.current_transcript = ""

                                if manager.current_callback is not None:
                                    asyncio.create_task(manager.current_callback(manager.current_text))
                                    manager.current_callback = None
                                    manager.current_text = ""

                                

                    # -------------------------------------------------- #
                    # Inner task C – drains the backend prompt queue      #
                    # -------------------------------------------------- #
                    async def process_backend_tasks():
                        while True:
                            prompt, callback, expiration_time = await manager.prompt_queue.get()
                            await client_to_gemini_queue.put(
                                ("prompt", (prompt, callback, expiration_time))
                            )
                            manager.prompt_queue.task_done()

                    # -------------------------------------------------- #
                    # Inner task D – keepalive ping to prevent idle       #
                    # timeout (Gemini Live drops ~60s of silence)         #
                    # -------------------------------------------------- #
                    async def keepalive():
                        while True:
                            await asyncio.sleep(KEEPALIVE_INTERVAL)
                            idle_for = time.time() - last_activity[0]
                            if idle_for >= KEEPALIVE_INTERVAL:
                                try:
                                    # Send a silent, empty-ish text turn so the
                                    # session registers activity on Google's side.
                                    logger.debug(f"Sending keepalive after {idle_for:.0f}s idle.")
                                    await session.send(input=".", end_of_turn=True)
                                    last_activity[0] = time.time()
                                except Exception as e:
                                    logger.warning(f"Keepalive send failed: {e}")
                                    raise  # surface to asyncio.wait so we reconnect

                    forward_task = asyncio.create_task(forward_to_gemini())
                    gemini_task = asyncio.create_task(receive_from_gemini())
                    backend_task = asyncio.create_task(process_backend_tasks())
                    keepalive_task = asyncio.create_task(keepalive())

                    client_gone = asyncio.create_task(client_disconnected.wait())
                    done, pending = await asyncio.wait(
                        [forward_task, gemini_task, backend_task, keepalive_task, client_gone],
                        return_when=asyncio.FIRST_COMPLETED,
                    )

                    for task in pending:
                        task.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)

                    if client_disconnected.is_set():
                        logger.info("Client gone – stopping Gemini session loop.")
                        return  # clean exit, no reconnect

                    # Gemini session dropped — log and reconnect with full context
                    logger.warning(
                        f"Gemini session ended (conversation so far: {len(conversation_log)} turns). "
                        "Reconnecting with context…"
                    )
                    await websocket.send_json({"type": "status", "message": "gemini_reconnecting"})

            except Exception as e:
                if client_disconnected.is_set():
                    return
                logger.error(f"Gemini session error: {e}. Retrying in {RETRY_DELAY}s…")
                await websocket.send_json({"type": "status", "message": "gemini_reconnecting"})
                await asyncio.sleep(RETRY_DELAY)

    # ------------------------------------------------------------------ #
    # No Gemini key – keep the WebSocket alive for push notifications     #
    # ------------------------------------------------------------------ #
    async def no_gemini_fallback():
        await websocket.send_json({"type": "error", "message": "Backend AI not configured."})
        await client_disconnected.wait()

    # ------------------------------------------------------------------ #
    # Launch everything                                                    #
    # ------------------------------------------------------------------ #
    client_reader = asyncio.create_task(receive_from_client())
    gemini_runner = asyncio.create_task(
        run_gemini_session() if client else no_gemini_fallback()
    )

    await asyncio.gather(client_reader, gemini_runner, return_exceptions=True)

    manager.disconnect(websocket)
    logger.info("WebSocket handler exited cleanly.")
