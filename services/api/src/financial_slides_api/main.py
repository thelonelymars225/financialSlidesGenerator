from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from financial_slides_api.generation import router as generation_router
from financial_slides_api.jobs import router as jobs_router
from financial_slides_api.operations import health
from financial_slides_api.privacy import router as privacy_router

app = FastAPI(title="financialSlidesGenerator API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.get("/health", tags=["operations"])(health)
app.include_router(jobs_router, prefix="/api")
app.include_router(generation_router, prefix="/api")
app.include_router(privacy_router, prefix="/api")
