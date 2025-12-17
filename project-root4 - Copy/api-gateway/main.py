"""
API Gateway
Single entry point for all microservices
"""
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx
import os
import logging
from datetime import datetime
import jwt
from typing import Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="API Gateway", version="1.0.0")

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Service URLs
SERVICES = {
    "tts": os.getenv("TTS_SERVICE_URL", "http://localhost:8001"),
    "stt": os.getenv("STT_SERVICE_URL", "http://localhost:8002"),
    "chat": os.getenv("CHAT_SERVICE_URL", "http://localhost:8003"),
    "document": os.getenv("DOCUMENT_SERVICE_URL", "http://localhost:8004"),
    "quiz": os.getenv("QUIZ_SERVICE_URL", "http://localhost:8005"),
}

# JWT Configuration
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"

# Rate limiting (simple in-memory implementation)
# In production, use Redis
request_counts = {}
RATE_LIMIT = 100  # requests per minute
RATE_WINDOW = 60  # seconds

def verify_token(token: str) -> dict:
    """Verify JWT token"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

def check_rate_limit(client_id: str) -> bool:
    """Check if client has exceeded rate limit"""
    current_time = datetime.utcnow().timestamp()
    
    if client_id not in request_counts:
        request_counts[client_id] = []
    
    # Remove old requests outside window
    request_counts[client_id] = [
        req_time for req_time in request_counts[client_id]
        if current_time - req_time < RATE_WINDOW
    ]
    
    # Check limit
    if len(request_counts[client_id]) >= RATE_LIMIT:
        return False
    
    # Add current request
    request_counts[client_id].append(current_time)
    return True

async def proxy_request(service_url: str, path: str, request: Request):
    """Forward request to microservice with proper file handling"""
    try:
        # Build target URL
        target_url = f"{service_url}{path}"
        
        # Get request body if present
        body = None
        if request.method in ["POST", "PUT", "PATCH"]:
            body = await request.body()
        
        # Forward request
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method=request.method,
                url=target_url,
                params=request.query_params,
                headers={k: v for k, v in request.headers.items() 
                        if k.lower() not in ['host', 'content-length']},
                content=body
            )
        
        # Check if response is a file (audio, binary, etc.)
        content_type = response.headers.get('content-type', '')
        
        # For file downloads, stream the response directly without buffering
        if (any(x in content_type.lower() for x in ['audio', 'video', 'image', 'application/octet-stream']) 
            or 'download' in path.lower()):
            
            logger.info(f"Streaming file response: {content_type}")
            
            async def generate():
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    yield chunk
            
            # Build response headers
            response_headers = {
                'content-type': content_type,
                'accept-ranges': response.headers.get('accept-ranges', 'bytes'),
            }
            
            # Add content-disposition if present
            if 'content-disposition' in response.headers:
                response_headers['content-disposition'] = response.headers['content-disposition']
            
            return StreamingResponse(
                generate(),
                status_code=response.status_code,
                headers=response_headers,
                media_type=content_type
            )
        
        # For JSON responses
        if 'application/json' in content_type:
            return JSONResponse(
                content=response.json(),
                status_code=response.status_code,
                headers={k: v for k, v in response.headers.items() 
                        if k.lower() not in ['content-length', 'transfer-encoding']}
            )
        
        # For other text responses
        return JSONResponse(
            content={"data": response.text},
            status_code=response.status_code,
            headers={k: v for k, v in response.headers.items() 
                    if k.lower() not in ['content-length', 'transfer-encoding']}
        )
        
    except httpx.TimeoutException:
        logger.error(f"Timeout calling {service_url}{path}")
        raise HTTPException(status_code=504, detail="Service timeout")
    except httpx.ConnectError:
        logger.error(f"Cannot connect to {service_url}")
        raise HTTPException(status_code=503, detail="Service unavailable")
    except Exception as e:
        logger.error(f"Error proxying request: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all requests"""
    start_time = datetime.utcnow()
    
    # Log request
    logger.info(f"{request.method} {request.url.path} - Start")
    
    response = await call_next(request)
    
    # Log response
    duration = (datetime.utcnow() - start_time).total_seconds()
    logger.info(f"{request.method} {request.url.path} - {response.status_code} - {duration:.3f}s")
    
    return response

@app.middleware("http")
async def authentication_middleware(request: Request, call_next):
    """Authenticate requests (except health and login endpoints)"""
    
    # Skip auth for health checks and public endpoints
    if request.url.path in ["/health", "/", "/docs", "/openapi.json"] or request.url.path.startswith("/auth"):
        return await call_next(request)
    
    # For demo purposes, allow requests without token
    # In production, uncomment this:
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    
    token = auth_header.split(" ")[1]
    user_data = verify_token(token)
    
    # Add user data to request state
    request.state.user = user_data
    """
    
    return await call_next(request)

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Rate limit requests"""
    
    # Skip rate limiting for health checks
    if request.url.path in ["/health", "/"]:
        return await call_next(request)
    
    # Get client identifier (IP or user_id)
    client_id = request.client.host
    
    if not check_rate_limit(client_id):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    
    return await call_next(request)

# Health check
@app.get("/health")
async def health():
    """Gateway health check"""
    service_health = {}
    
    async with httpx.AsyncClient(timeout=5.0) as client:
        for service_name, service_url in SERVICES.items():
            try:
                response = await client.get(f"{service_url}/health")
                service_health[service_name] = "healthy" if response.status_code == 200 else "unhealthy"
            except:
                service_health[service_name] = "unreachable"
    
    return {
        "gateway": "healthy",
        "services": service_health,
        "timestamp": datetime.utcnow().isoformat()
    }

# Root endpoint
@app.get("/")
async def root():
    """Gateway information"""
    return {
        "service": "API Gateway",
        "version": "1.0.0",
        "services": list(SERVICES.keys()),
        "timestamp": datetime.utcnow().isoformat()
    }

# TTS Service Routes
@app.api_route("/api/tts/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def tts_proxy(path: str, request: Request):
    """Proxy requests to TTS service"""
    return await proxy_request(SERVICES["tts"], f"/api/tts/{path}", request)

# STT Service Routes
@app.api_route("/api/stt/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def stt_proxy(path: str, request: Request):
    """Proxy requests to STT service"""
    return await proxy_request(SERVICES["stt"], f"/api/stt/{path}", request)

# Chat Service Routes
@app.api_route("/api/chat/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def chat_proxy(path: str, request: Request):
    """Proxy requests to Chat service"""
    return await proxy_request(SERVICES["chat"], f"/api/chat/{path}", request)

# Document Service Routes
@app.api_route("/api/documents/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def document_proxy(path: str, request: Request):
    """Proxy requests to Document service"""
    return await proxy_request(SERVICES["document"], f"/api/documents/{path}", request)

@app.api_route("/api/documents", methods=["GET", "POST"])
async def document_list_proxy(request: Request):
    """Proxy requests to Document service"""
    return await proxy_request(SERVICES["document"], f"/api/documents", request)

# Quiz Service Routes
@app.api_route("/api/quiz/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def quiz_proxy(path: str, request: Request):
    """Proxy requests to Quiz service"""
    return await proxy_request(SERVICES["quiz"], f"/api/quiz/{path}", request)

@app.api_route("/api/quiz", methods=["GET", "POST"])
async def quiz_list_proxy(request: Request):
    """Proxy requests to Quiz service"""
    return await proxy_request(SERVICES["quiz"], f"/api/quiz", request)

# Authentication endpoint (mock)
@app.post("/auth/login")
async def login(username: str, password: str):
    """Mock login endpoint - returns JWT token"""
    # In production, validate against database
    if username and password:
        token_data = {
            "user_id": username,
            "exp": datetime.utcnow().timestamp() + 3600  # 1 hour
        }
        token = jwt.encode(token_data, JWT_SECRET, algorithm=JWT_ALGORITHM)
        return {"access_token": token, "token_type": "bearer"}
    
    raise HTTPException(status_code=401, detail="Invalid credentials")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
