from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.navigation import router as navigation_router
from app.core.config import settings


app = FastAPI(
    title="GNSS Navigation Agent System",
    description="Educational multi-agent GNSS heading and integrity demo based on baseline-constraint papers.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {
        "message": "GNSS Navigation Agent backend is running.",
        "docs": "/docs",
    }


app.include_router(navigation_router)
