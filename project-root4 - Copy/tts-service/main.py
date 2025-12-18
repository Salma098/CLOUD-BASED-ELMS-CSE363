"""
Text-To-Speech (TTS) Service
- Receive text
- Generate speech locally
- Publish audio metadata event to Kafka
- No shared storage, no S3
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from kafka import KafkaProducer
from gtts import gTTS
import uuid
import os
import json
import logging
from datetime import datetime
from typing import Optional

# -------------------------------------------------
# Config & App
# -------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="TTS Service")

KAFKA_BOOTSTRAP = os.getenv(
    "KAFKA_BOOTSTRAP",
    "kafka:9092"
)


LOCAL_AUDIO_DIR = "/app/storage/tts_audio"
os.makedirs(LOCAL_AUDIO_DIR, exist_ok=True)

# -------------------------------------------------
# Kafka Producer
# -------------------------------------------------
producer = KafkaProducer(
    bootstrap_servers=KAFKA_BOOTSTRAP.split(","),
    value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    retries=5
)

# -------------------------------------------------
# Models
# -------------------------------------------------
class TTSRequest(BaseModel):
    text: str
    language: Optional[str] = "en"
    slow: Optional[bool] = False


class TTSResponse(BaseModel):
    tts_id: str
    status: str
    created_at: str

# -------------------------------------------------
# Service-Owned Storage
# -------------------------------------------------
jobs = {}

# -------------------------------------------------
# Core Processing
# -------------------------------------------------
def generate_audio(
    tts_id: str,
    text: str,
    language: str,
    slow: bool
):
    try:
        logger.info(f"🔊 Generating speech for {tts_id}")

        audio_path = f"{LOCAL_AUDIO_DIR}/{tts_id}.mp3"

        tts = gTTS(text=text, lang=language, slow=slow)
        tts.save(audio_path)

        jobs[tts_id]["status"] = "completed"
        jobs[tts_id]["audio_path"] = audio_path

        # ---------------------------
        # Kafka Event (DATA PAYLOAD)
        # ---------------------------
        event = {
            "type": "tts.generated",
            "tts_id": tts_id,
            "language": language,
            "text_preview": text[:200],
            "timestamp": datetime.utcnow().isoformat()
        }

        producer.send("tts.generated", value=event)
        producer.flush()

        logger.info(f"✅ TTS event published ({tts_id})")

    except Exception as e:
        jobs[tts_id]["status"] = "failed"
        jobs[tts_id]["error"] = str(e)
        logger.error(f"❌ TTS failed: {e}")

# -------------------------------------------------
# API Endpoints
# -------------------------------------------------
@app.post("/synthesize", response_model=TTSResponse)
async def generate_tts(
    request: TTSRequest,
    background_tasks: BackgroundTasks
):
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty")

    tts_id = str(uuid.uuid4())
    created_at = datetime.utcnow().isoformat()

    jobs[tts_id] = {
        "tts_id": tts_id,
        "status": "processing",
        "created_at": created_at
    }

    # Fire event: TTS requested
    request_event = {
        "type": "tts.requested",
        "tts_id": tts_id,
        "language": request.language,
        "timestamp": created_at
    }
    producer.send("tts.requested", value=request_event)
    producer.flush()

    # Background generation (Lambda-like)
    background_tasks.add_task(
        generate_audio,
        tts_id,
        request.text,
        request.language,
        request.slow
    )

    return TTSResponse(
        tts_id=tts_id,
        status="processing",
        created_at=created_at
    )

@app.get("/{tts_id}", response_model=TTSResponse)
async def get_tts_status(tts_id: str):
    if tts_id not in jobs:
        raise HTTPException(status_code=404, detail="TTS job not found")

    job = jobs[tts_id]
    return TTSResponse(
        tts_id=tts_id,
        status=job["status"],
        created_at=job["created_at"]
    )

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "tts-service",
        "jobs_count": len(jobs)
    }
@app.get("/audio/{audio_id}/download")  # Add this if missing
async def download_audio(audio_id: str):
    # Return the audio file
    pass

# -------------------------------------------------
# Run
# -------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
