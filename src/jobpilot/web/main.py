"""Main entry point for FastAPI web server."""

import uvicorn
from jobpilot.web.api import app

if __name__ == "__main__":
    uvicorn.run(
        "applypilot.web.api:app",
        host="0.0.0.0",
        port=8000,
        reload=True,  # Auto-reload on code changes
    )
