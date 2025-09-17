from fastapi import FastAPI
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(title="YetAI Backend Test", version="0.1.0")


@app.get("/")
async def root():
    return {
        "message": "YetAI Backend Test",
        "status": "running",
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@app.get("/test-db")
async def test_db():
    try:
        from app.core.database import check_db_connection

        db_status = check_db_connection()
        return {
            "database_connection": "success" if db_status else "failed",
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {
            "database_connection": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
        }


if __name__ == "__main__":
    import uvicorn
    import os

    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
