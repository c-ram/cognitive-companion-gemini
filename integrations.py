import os
import asyncio
import httpx
import smtplib
import ssl
from openai import AsyncOpenAI
from typing import Optional
import json
import uuid
from email.message import EmailMessage
from minio_utils import minio_client

# Environment Variables
TTS_API_URL = os.getenv("TTS_API_URL", "http://192.168.1.31:6060/v1/")
HOME_ASSISTANT_URL = os.getenv("HOME_ASSISTANT_URL", "http://homeassistant.local:8123")
HOME_ASSISTANT_TOKEN = os.getenv("HOME_ASSISTANT_TOKEN", "")
WHATSAPP_API_URL = os.getenv("WHATSAPP_API_URL", "https://graph.facebook.com/v17.0/")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() in ("1", "true", "yes", "on")
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USERNAME)

class TTSClient:
    def __init__(self):
        # Adjust URL for OpenAI client if needed
        base_url = TTS_API_URL
        if "/v1" not in base_url and not base_url.endswith("/"):
             base_url += "/v1"
        self.client = AsyncOpenAI(api_key="EMPTY", base_url=base_url)

    async def generate_audio(self, text: str, output_path: str, voice: str = "en-IN-NeerjaExpressiveNeural", speed=0.85) -> Optional[str]:
        """
        Generates audio from text using OpenAI-compatible TTS endpoint.
        Saves to output_path.
        """
        try:
            response = await self.client.audio.speech.create(
                model="tts-1",
                voice=voice,
                input=text,
                speed=speed,
            )
            response.stream_to_file(output_path)
            print(f"Generated TTS for: {text}, path: {output_path}")
            return output_path
        except Exception as e:
            print(f"TTS Error: {e}")
            return None

class HomeAssistantClient:
    def __init__(self):
        self.headers = {
            "Authorization": f"Bearer {HOME_ASSISTANT_TOKEN}",
            "Content-Type": "application/json",
        }
        self.base_url = HOME_ASSISTANT_URL.rstrip('/')
        self.tts_client = TTSClient()

    async def announce(self, message: str, media_url: Optional[str] = None):
        """
        Sends a notification or plays a media file on Home Assistant.
        For now, we'll assume a generic 'notify' service or 'media_player'.
        """
        try:
            async with httpx.AsyncClient() as client:
                # Example: Send a text notification
                payload = {"message": message}
                url = f"{self.base_url}/api/services/notify/persistent_notification" # Adjust service as needed
                
                print(f"Sending HA notification: {message}")
                resp = await client.post(url, headers=self.headers, json=payload)
                resp.raise_for_status()
                
                # If functionality for playing audio is needed
                # url = f"{self.base_url}/api/services/media_player/play_media"
                # payload = {
                #     "entity_id": "all",
                #     "media_content_id": media_url,
                #     "media_content_type": "music"
                # }
                # await client.post(url, headers=self.headers, json=payload)
                
        except Exception as e:
            print(f"Home Assistant Error: {e}")

    async def play_audio(self, audio_url: str, entity_id: str = "media_player.living_room_speaker"):
        """
        Plays audio from a URL on a specific media player.
        """
        try:
            async with httpx.AsyncClient() as client:
                url = f"{self.base_url}/api/services/media_player/play_media"
                payload = {
                    "entity_id": entity_id,
                    "media_content_id": audio_url,
                    "media_content_type": "music"
                }
                print(f"Playing audio on HA: {audio_url}")
                resp = await client.post(url, headers=self.headers, json=payload)
                resp.raise_for_status()
        except Exception as e:
            print(f"Home Assistant Audio Error: {e}")
    
    async def play_message_as_audio(self, message: str, voice="en-IN-NeerjaExpressiveNeural", speed=0.85, entity_id: str = "media_player.living_room_speaker"):
        """
        Converts text to speech and plays it on a specific media player.
        """
        request_id = str(uuid.uuid4())
        audio_path = f"/tmp/{request_id}.mp3"
        await self.tts_client.generate_audio(message, audio_path, voice=voice, speed=speed)
        audio_url = await asyncio.to_thread(minio_client.upload_file, audio_path, f"{request_id}.mp3")
        if audio_url:
            await self.play_audio(audio_url)
        asyncio.to_thread(minio_client.delete_object, f"{request_id}.mp3")

    async def get_person_info_state(self, sensor_id: str) -> Optional[str]:
        """
        Retrieves the person information state for a given sensor id.
        """
        entity_id = f"binary_sensor.{sensor_id}_person_information"
        try:
            async with httpx.AsyncClient() as client:
                url = f"{self.base_url}/api/states/{entity_id}"
                resp = await client.get(url, headers=self.headers)
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("state")
                return None
        except Exception as e:
            print(f"Home Assistant Error fetching person info for {sensor_id}: {e}")
            return None

    async def get_distance_entity_state(self, sensor_id: str) -> Optional[str]:
        """
        Retrieves the distance to detection object state for a given sensor id.
        """
        entity_id = f"sensor.{sensor_id}_distance_to_detection_object"
        try:
            async with httpx.AsyncClient() as client:
                url = f"{self.base_url}/api/states/{entity_id}"
                resp = await client.get(url, headers=self.headers)
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("state")
                return None
        except Exception as e:
            print(f"Home Assistant Error fetching distance for {sensor_id}: {e}")
            return None


class WhatsAppClient:
    def __init__(self):
        self.headers = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json",
        }
        self.url = WHATSAPP_API_URL 

    async def send_message(self, to_number: str, message: str):
        """
        Sends a WhatsApp message.
        """
        if not WHATSAPP_TOKEN or "replace_me" in WHATSAPP_TOKEN:
            print("WhatsApp token not configured, skipping.")
            return

        try:
            async with httpx.AsyncClient() as client:
                payload = {
                    "messaging_product": "whatsapp",
                    "to": to_number,
                    "type": "text",
                    "text": {"body": message}
                }
                # Ensure URL is correct for sending messages (usually includes phone number ID)
                # Assuming WHATSAPP_API_URL includes the phone ID: e.g. https://graph.facebook.com/v17.0/PHONE_NUMBER_ID/messages
                # If not, we might need to adjust.
                
                print(f"Sending WhatsApp to {to_number}: {message}")
                resp = await client.post(self.url, headers=self.headers, json=payload)
                resp.raise_for_status()
        except Exception as e:
            print(f"WhatsApp Error: {e}")


class EmailToSMSClient:
    def __init__(self):
        self.host = SMTP_HOST
        self.port = SMTP_PORT
        self.use_tls = SMTP_USE_TLS
        self.username = SMTP_USERNAME
        self.password = SMTP_PASSWORD
        self.from_addr = SMTP_FROM

    async def send_message(self, to_email: str, message: str, subject: str = "Cognitive Companion Alert"):
        """
        Sends an email intended for SMS gateways (e.g., 10digit@tmomail.net).
        """
        if not self.username or not self.password:
            print("SMTP credentials not configured, skipping.")
            return
        if not to_email:
            print("Recipient email not configured, skipping.")
            return

        msg = EmailMessage()
        msg["From"] = self.from_addr or self.username
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.set_content(message)

        def _send():
            context = ssl.create_default_context()
            with smtplib.SMTP(self.host, self.port, timeout=15) as server:
                server.ehlo()
                if self.use_tls:
                    server.starttls(context=context)
                    server.ehlo()
                server.login(self.username, self.password)
                server.send_message(msg)

        try:
            await asyncio.to_thread(_send)
            print(f"Sent email-to-SMS to {to_email}: {message}")
        except Exception as e:
            print(f"Email-to-SMS Error: {e}")
