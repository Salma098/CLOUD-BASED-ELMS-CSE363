"""
Document Reader Service (Event-Driven)
- Upload documents
- Process documents locally
- Publish events to Kafka
- No other service reads from this service storage
"""

from fastapi import FastAPI, HTTPException, UploadFile, File, BackgroundTasks
from pydantic import BaseModel
from kafka import KafkaProducer
import json
import uuid
import os
from datetime import datetime
import logging
import PyPDF2
import docx

# -------------------------------------------------
# Config & App
# -------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Document Reader Service")

KAFKA_BOOTSTRAP = os.getenv(
    "KAFKA_BOOTSTRAP",
    "10.0.1.186:9092,10.0.1.206:9092,10.0.1.183:9092"
)

LOCAL_STORAGE = "/app/storage/documents"
os.makedirs(LOCAL_STORAGE, exist_ok=True)

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
class DocumentResponse(BaseModel):
    document_id: str
    filename: str
    status: str
    uploaded_at: str

# -------------------------------------------------
# In-Memory Metadata (Service-Owned)
# -------------------------------------------------
documents = {}

# -------------------------------------------------
# Helpers
# -------------------------------------------------
def extract_text_from_pdf(path: str) -> str:
    text = ""
    with open(path, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        for page in reader.pages:
            text += page.extract_text() or ""
    return text


def extract_text_from_docx(path: str) -> str:
    doc = docx.Document(path)
    return "\n".join(p.text for p in doc.paragraphs)


def extract_text_from_txt(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def generate_notes(text: str) -> str:
    # Mock notes generation (AI later)
    return (
        "SUMMARY:\n"
        f"Characters: {len(text)}\n"
        f"Words: {len(text.split())}\n\n"
        f"Preview:\n{text[:500]}"
    )

# -------------------------------------------------
# Core Processing (Event Producer)
# -------------------------------------------------
def process_document(document_id: str, filename: str, file_path: str):
    try:
        logger.info(f"📄 Processing document {document_id}")

        if filename.endswith(".pdf"):
            text = extract_text_from_pdf(file_path)
        elif filename.endswith(".docx"):
            text = extract_text_from_docx(file_path)
        elif filename.endswith(".txt"):
            text = extract_text_from_txt(file_path)
        else:
            raise ValueError("Unsupported file type")

        notes = generate_notes(text)

        documents[document_id]["status"] = "processed"

        # ---------------------------
        # Kafka Events (DATA PAYLOAD)
        # ---------------------------
        document_event = {
            "type": "document.processed",
            "document_id": document_id,
            "filename": filename,
            "extracted_text": text[:2000],
            "timestamp": datetime.utcnow().isoformat()
        }

        notes_event = {
            "type": "notes.generated",
            "document_id": document_id,
            "notes": notes[:1000],
            "timestamp": datetime.utcnow().isoformat()
        }

        producer.send("document.processed", value=document_event)
        producer.send("notes.generated", value=notes_event)
        producer.flush()

        logger.info(f"✅ Events published for {document_id}")

    except Exception as e:
        logger.error(f"❌ Processing failed: {e}")
        documents[document_id]["status"] = "failed"

# -------------------------------------------------
# API Endpoints
# -------------------------------------------------
@app.post("/api/documents/upload", response_model=DocumentResponse)
async def upload_document(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = None
):
    if not file.filename.endswith((".pdf", ".docx", ".txt")):
        raise HTTPException(
            status_code=400,
            detail="Supported formats: PDF, DOCX, TXT"
        )

    document_id = str(uuid.uuid4())
    upload_time = datetime.utcnow().isoformat()

    file_path = f"{LOCAL_STORAGE}/{document_id}_{file.filename}"

    with open(file_path, "wb") as f:
        f.write(await file.read())

    documents[document_id] = {
        "document_id": document_id,
        "filename": file.filename,
        "status": "processing",
        "uploaded_at": upload_time
    }

    # Fire event: document uploaded
    upload_event = {
        "type": "document.uploaded",
        "document_id": document_id,
        "filename": file.filename,
        "timestamp": upload_time
    }
    producer.send("document.uploaded", value=upload_event)
    producer.flush()

    # Background processing
    background_tasks.add_task(
        process_document,
        document_id,
        file.filename,
        file_path
    )

    return DocumentResponse(
        document_id=document_id,
        filename=file.filename,
        status="processing",
        uploaded_at=upload_time
    )

@app.get("/api/documents/{document_id}")
async def get_document(document_id: str):
    if document_id not in documents:
        raise HTTPException(status_code=404, detail="Document not found")
    return documents[document_id]

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "document-reader-service",
        "documents_count": len(documents)
    }

# -------------------------------------------------
# Run
# -------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8004)
