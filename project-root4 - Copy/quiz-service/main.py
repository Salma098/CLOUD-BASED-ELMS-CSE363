"""
Quiz Service (Event-Driven)
- Consumes document.processed events from Kafka
- Generates quizzes from event payload
- Stores quizzes locally (service-owned storage)
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from kafka import KafkaConsumer
import json
import uuid
import os
import threading
import logging
import re
import random
from datetime import datetime
from typing import List, Dict, Optional

# -------------------------------------------------
# Config & App
# -------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Quiz Service")

KAFKA_BOOTSTRAP = os.getenv(
    "KAFKA_BOOTSTRAP",
    "10.0.1.186:9092,10.0.1.206:9092,10.0.1.183:9092"
)

# -------------------------------------------------
# Models
# -------------------------------------------------
class Question(BaseModel):
    question_id: str
    question_text: str
    question_type: str
    options: Optional[List[str]] = None
    correct_answer: Optional[str] = None


class Quiz(BaseModel):
    quiz_id: str
    document_id: str
    questions: List[Question]
    created_at: str
    status: str


class AnswerSubmission(BaseModel):
    answers: Dict[str, str]


class QuizResult(BaseModel):
    quiz_id: str
    score: float
    total_questions: int
    correct_answers: int
    feedback: List[Dict]
    submitted_at: str

# -------------------------------------------------
# Service-Owned Storage (Local)
# -------------------------------------------------
quizzes: Dict[str, Dict] = {}
quiz_results: Dict[str, QuizResult] = {}

# -------------------------------------------------
# Text Processing Helpers
# -------------------------------------------------
def extract_sentences(text: str) -> List[str]:
    sentences = re.split(r"[.!?]+", text)
    return [s.strip() for s in sentences if len(s.strip()) > 20]


def extract_keywords(text: str) -> List[str]:
    words = re.findall(r"\b[a-zA-Z]{5,}\b", text.lower())
    freq = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    return sorted(freq, key=freq.get, reverse=True)[:10]


def generate_questions(text: str, num_questions: int = 5) -> List[Question]:
    sentences = extract_sentences(text)
    keywords = extract_keywords(text)

    questions: List[Question] = []

    for sentence in sentences[:num_questions]:
        if not keywords:
            break

        keyword = random.choice(keywords)
        options = [
            sentence[:50] + "...",
            f"Related to {random.choice(keywords)}",
            "Not mentioned in the document",
            "None of the above"
        ]
        random.shuffle(options)

        questions.append(
            Question(
                question_id=str(uuid.uuid4()),
                question_text=f"What does the document mention about '{keyword}'?",
                question_type="multiple_choice",
                options=options,
                correct_answer=options[0]
            )
        )

    if not questions:
        questions.append(
            Question(
                question_id=str(uuid.uuid4()),
                question_text="What is the main topic of the document?",
                question_type="true_false",
                options=["True", "False"],
                correct_answer="True"
            )
        )

    return questions

# -------------------------------------------------
# Kafka Consumer (Event-Driven Core)
# -------------------------------------------------
def kafka_consumer_worker():
    consumer = KafkaConsumer(
        "document.processed",
        bootstrap_servers=KAFKA_BOOTSTRAP.split(","),
        group_id="quiz-service",
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        auto_offset_reset="latest"
    )

    logger.info("📡 Quiz Service Kafka consumer started")

    for message in consumer:
        try:
            event = message.value
            document_id = event["document_id"]
            text = event.get("extracted_text", "")

            quiz_id = str(uuid.uuid4())
            questions = generate_questions(text)

            quizzes[quiz_id] = {
                "quiz_id": quiz_id,
                "document_id": document_id,
                "questions": questions,
                "created_at": datetime.utcnow().isoformat(),
                "status": "ready"
            }

            logger.info(f"📝 Quiz generated for document {document_id}")

        except Exception as e:
            logger.error(f"❌ Failed to generate quiz: {e}")

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
# API Endpoints
# -------------------------------------------------
@app.get("/api/quiz/{quiz_id}", response_model=Quiz)
async def get_quiz(quiz_id: str):
    if quiz_id not in quizzes:
        raise HTTPException(status_code=404, detail="Quiz not found")

    quiz = quizzes[quiz_id]

    # Hide correct answers
    questions = []
    for q in quiz["questions"]:
        q_dict = q.dict()
        q_dict["correct_answer"] = None
        questions.append(Question(**q_dict))

    return Quiz(
        quiz_id=quiz["quiz_id"],
        document_id=quiz["document_id"],
        questions=questions,
        created_at=quiz["created_at"],
        status=quiz["status"]
    )


@app.post("/api/quiz/{quiz_id}/submit", response_model=QuizResult)
async def submit_quiz(quiz_id: str, submission: AnswerSubmission):
    if quiz_id not in quizzes:
        raise HTTPException(status_code=404, detail="Quiz not found")

    quiz = quizzes[quiz_id]
    correct = 0
    feedback = []

    for q in quiz["questions"]:
        user_answer = submission.answers.get(q.question_id, "")
        is_correct = user_answer.strip().lower() == q.correct_answer.strip().lower()
        if is_correct:
            correct += 1

        feedback.append({
            "question": q.question_text,
            "your_answer": user_answer,
            "correct_answer": q.correct_answer,
            "is_correct": is_correct
        })

    total = len(quiz["questions"])
    score = (correct / total) * 100 if total > 0 else 0

    result = QuizResult(
        quiz_id=quiz_id,
        score=score,
        total_questions=total,
        correct_answers=correct,
        feedback=feedback,
        submitted_at=datetime.utcnow().isoformat()
    )

    quiz_results[quiz_id] = result
    return result


@app.get("/api/quiz/{quiz_id}/results", response_model=QuizResult)
async def get_results(quiz_id: str):
    if quiz_id not in quiz_results:
        raise HTTPException(status_code=404, detail="Results not found")
    return quiz_results[quiz_id]


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "quiz-service",
        "quizzes_count": len(quizzes)
    }

# -------------------------------------------------
# Run
# -------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8005)
