"""
Minimal FastAPI application for Railway deployment testing
This will help us isolate and fix the deployment issues
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="YetAI Sports Betting MVP",
    description="AI-Powered Sports Betting Platform",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure properly for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {
        "message": "YetAI Sports Betting MVP API",
        "version": "1.0.0",
        "status": "running",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "environment": os.getenv("ENVIRONMENT", "development")
    }

@app.get("/api/status")
async def api_status():
    """API status endpoint for frontend"""
    return {
        "api_status": "online",
        "database_status": "connected",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/test-db")
async def test_database():
    """Test database connection"""
    try:
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            return {
                "database": "No DATABASE_URL configured",
                "status": "warning"
            }
        
        # Simple connection test
        import psycopg2
        conn = psycopg2.connect(database_url)
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        
        return {
            "database": "connected",
            "status": "success",
            "result": result[0] if result else None,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return {
            "database": "connection failed",
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)