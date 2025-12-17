"""
Chat Service (Event-Driven)
- Receives chat messages via API
- Builds context from Kafka events
- Generates responses (mock / AI later)
- No shared storage, no S3
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from kafka import KafkaProducer, KafkaConsumer
import json
import uuid
import os
import threading
import logging
from datetime import datetime
from typing import List, Dict, Optional

# -------------------------------------------------
# Config & App
# -------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Chat Service")

KAFKA_BOOTSTRAP = os.getenv(
    "KAFKA_BOOTSTRAP",
    "10.0.1.186:9092,10.0.1.206:9092,10.0.1.183:9092"
)

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
class ChatRequest(BaseModel):
    conversation_id: Optional[str] = None
    user_id: str
    message: str


class ChatResponse(BaseModel):
    conversation_id: str
    message: str
    timestamp: str


class Message(BaseModel):
    role: str
    content: str
    timestamp: str


class Conversation(BaseModel):
    conversation_id: str
    user_id: str
    messages: List[Message]
    created_at: str
    updated_at: str

# -------------------------------------------------
# Service-Owned Storage (Local)
# -------------------------------------------------
conversations: Dict[str, Dict] = {}

# Context built ONLY from events
document_context: Dict[str, str] = {}
audio_context: Dict[str, str] = {}

# -------------------------------------------------
# Kafka Consumer (Context Builder)
# -------------------------------------------------
def kafka_consumer_worker():
    consumer = KafkaConsumer(
        "document.processed",
        "notes.generated",
        "audio.transcription.completed",
        bootstrap_servers=KAFKA_BOOTSTRAP.split(","),
        group_id="chat-service",
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        auto_offset_reset="latest"
    )

    logger.info("📡 Chat Service Kafka consumer started")

    for message in consumer:
        try:
            event = message.value
            topic = message.topic

            if topic == "document.processed":
                document_id = event["document_id"]
                document_context[document_id] = event.get("extracted_text", "")
                logger.info(f"📄 Context stored for document {document_id}")

            elif topic == "notes.generated":
                document_id = event["document_id"]
                notes = event.get("notes", "")
                document_context[document_id] = (
                    document_context.get(document_id, "") + "\n" + notes
                )
                logger.info(f"📝 Notes added for document {document_id}")

            elif topic == "audio.transcription.completed":
                transcription_id = event["transcription_id"]
                audio_context[transcription_id] = event.get("text", "")
                logger.info(f"🎙️ Audio context stored {transcription_id}")

        except Exception as e:
            logger.error(f"❌ Error processing Kafka event: {e}")

# -------------------------------------------------
# Startup Hook
# -------------------------------------------------
@app.on_event("startup")
def startup_event():
    thread = threading.Thread(
        target=kafka_consumer_worker,
        daemon=True
    )
    thread.start()

# -------------------------------------------------
# Core Chat Logic (Mock AI)
# -------------------------------------------------
def generate_response(user_message: str, context: str) -> str:
    if context:
        return (
            "Based on the available context, here is a helpful response:\n\n"
            f"{context[:300]}\n\n"
            f"Your question was: {user_message}"
        )
    return f"I received your message: '{user_message}'. How can I help you?"

# -------------------------------------------------
# API Endpoints
# -------------------------------------------------
@app.post("/api/chat/message", response_model=ChatResponse)
async def send_message(request: ChatRequest):
    conversation_id = request.conversation_id or str(uuid.uuid4())
    timestamp = datetime.utcnow().isoformat()

    if conversation_id not in conversations:
        conversations[conversation_id] = {
            "conversation_id": conversation_id,
            "user_id": request.user_id,
            "messages": [],
            "created_at": timestamp,
            "updated_at": timestamp
        }

    conversation = conversations[conversation_id]

    # Add user message
    conversation["messages"].append(
        Message(
            role="user",
            content=request.message,
            timestamp=timestamp
        )
    )

    # Build context from events only
    combined_context = "\n".join(document_context.values()) + "\n"
    combined_context += "\n".join(audio_context.values())

    # Generate response
    response_text = generate_response(request.message, combined_context)

    conversation["messages"].append(
        Message(
            role="assistant",
            content=response_text,
            timestamp=timestamp
        )
    )

    conversation["updated_at"] = timestamp

    # ---------------------------
    # Kafka Event (Chat Message)
    # ---------------------------
    event = {
        "type": "chat.message",
        "conversation_id": conversation_id,
        "user_id": request.user_id,
        "message": request.message,
        "response": response_text,
        "timestamp": timestamp
    }

    producer.send("chat.message", value=event)
    producer.flush()

    return ChatResponse(
        conversation_id=conversation_id,
        message=response_text,
        timestamp=timestamp
    )

@app.get("/api/chat/conversations/{conversation_id}", response_model=Conversation)
async def get_conversation(conversation_id: str):
    if conversation_id not in conversations:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversations[conversation_id]

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "chat-service",
        "conversations": len(conversations),
        "documents_loaded": len(document_context),
        "audio_loaded": len(audio_context)
    }

# -------------------------------------------------
# Run
# -------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)
