"""
Speech-To-Text (STT) Service
- Upload audio files
- Transcribe locally
- Publish transcription events to Kafka
- No shared storage, no S3
"""

from fastapi import FastAPI, HTTPException, UploadFile, File, BackgroundTasks
from pydantic import BaseModel
from kafka import KafkaProducer
import speech_recognition as sr
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

app = FastAPI(title="STT Service")

KAFKA_BOOTSTRAP = os.getenv(
    "KAFKA_BOOTSTRAP",
    "10.0.1.186:9092,10.0.1.206:9092,10.0.1.183:9092"
)

LOCAL_AUDIO_DIR = "/app/storage/audio"
LOCAL_TRANSCRIPT_DIR = "/app/storage/transcriptions"

os.makedirs(LOCAL_AUDIO_DIR, exist_ok=True)
os.makedirs(LOCAL_TRANSCRIPT_DIR, exist_ok=True)

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
class TranscriptionResponse(BaseModel):
    transcription_id: str
    status: str
    uploaded_at: str
    text: Optional[str] = None

# -------------------------------------------------
# Service-Owned Storage (Local)
# -------------------------------------------------
jobs = {}

# -------------------------------------------------
# Core Processing
# -------------------------------------------------
def transcribe_audio(
    transcription_id: str,
    audio_path: str,
    language: str = "en-US"
):
    try:
        logger.info(f"🎙️ Transcribing {transcription_id}")

        recognizer = sr.Recognizer()

        with sr.AudioFile(audio_path) as source:
            audio_data = recognizer.record(source)

        text = recognizer.recognize_google(audio_data, language=language)

        jobs[transcription_id]["status"] = "completed"
        jobs[transcription_id]["text"] = text

        # Save transcription locally (service-owned)
        transcript_path = f"{LOCAL_TRANSCRIPT_DIR}/{transcription_id}.txt"
        with open(transcript_path, "w", encoding="utf-8") as f:
            f.write(text)

        # ---------------------------
        # Kafka Event (DATA PAYLOAD)
        # ---------------------------
        event = {
            "type": "audio.transcription.completed",
            "transcription_id": transcription_id,
            "text": text,
            "language": language,
            "timestamp": datetime.utcnow().isoformat()
        }

        producer.send("audio.transcription.completed", value=event)
        producer.flush()

        logger.info(f"✅ Transcription event published ({transcription_id})")

    except sr.UnknownValueError:
        error = "Audio not clear enough for transcription"
        jobs[transcription_id]["status"] = "failed"
        jobs[transcription_id]["error"] = error
        logger.warning(error)

    except Exception as e:
        jobs[transcription_id]["status"] = "failed"
        jobs[transcription_id]["error"] = str(e)
        logger.error(f"❌ Transcription failed: {e}")

# -------------------------------------------------
# API Endpoints
# -------------------------------------------------
@app.post("/api/stt/transcribe", response_model=TranscriptionResponse)
async def upload_audio(
    file: UploadFile = File(...),
    language: str = "en-US",
    background_tasks: BackgroundTasks = None
):
    if not file.filename.endswith((".wav", ".aiff", ".flac")):
        raise HTTPException(
            status_code=400,
            detail="Supported formats: WAV, AIFF, FLAC"
        )

    transcription_id = str(uuid.uuid4())
    upload_time = datetime.utcnow().isoformat()

    audio_path = f"{LOCAL_AUDIO_DIR}/{transcription_id}_{file.filename}"

    with open(audio_path, "wb") as f:
        f.write(await file.read())

    jobs[transcription_id] = {
        "transcription_id": transcription_id,
        "status": "processing",
        "uploaded_at": upload_time
    }

    # Fire event: audio uploaded
    upload_event = {
        "type": "audio.uploaded",
        "transcription_id": transcription_id,
        "filename": file.filename,
        "timestamp": upload_time
    }
    producer.send("audio.uploaded", value=upload_event)
    producer.flush()

    # Background transcription (Lambda-like)
    background_tasks.add_task(
        transcribe_audio,
        transcription_id,
        audio_path,
        language
    )

    return TranscriptionResponse(
        transcription_id=transcription_id,
        status="processing",
        uploaded_at=upload_time
    )

@app.get("/api/stt/{transcription_id}", response_model=TranscriptionResponse)
async def get_transcription(transcription_id: str):
    if transcription_id not in jobs:
        raise HTTPException(status_code=404, detail="Transcription not found")

    job = jobs[transcription_id]
    return TranscriptionResponse(**job)

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "stt-service",
        "jobs_count": len(jobs)
    }

# -------------------------------------------------
# Run
# -------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
