from fastapi import FastAPI
from app.api.routers import clip, auth, transcript
from app.core.config import settings
from app.core.tasks import start_cleanup_worker, start_sheets_worker
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start the background cleanup worker
    start_cleanup_worker()
    
    # Mode-based workers
    run_mode = settings.RUN_MODE.lower()
    import logging
    logger = logging.getLogger("app.main")
    
    if run_mode == "compilation" or run_mode == "both":
        logger.info("Starting Compilation Worker...")
        from app.core.tasks import start_compilation_worker
        start_compilation_worker()
        
    if run_mode == "clipper" or run_mode == "both":
        logger.info("Starting Clipper Worker...")
        # Add clipper worker if needed, or sheets worker
        start_sheets_worker()
        
    yield
    # Shutdown logic (if any)

app = FastAPI(
    title=settings.PROJECT_NAME,
    lifespan=lifespan
)

# Include routers
app.include_router(clip.router)
app.include_router(auth.router)
app.include_router(transcript.router)

@app.get("/")
async def root():
    return {"message": "YouTube Clip Downloader API is running"}

if __name__ == "__main__":
    import uvicorn
    # Enable reload=True for development (requires string import pattern)
    uvicorn.run("app.main:app", host="0.0.0.0", port=8888, reload=True)
