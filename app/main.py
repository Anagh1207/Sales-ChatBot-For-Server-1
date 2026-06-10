"""
FastAPI application entrypoint.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import OperationalError

from app.api.routes import router as api_router
from app.api.text_to_sql_routes import router as text_to_sql_router
from app.api.designer_routes import router as designer_router
from app.db.session import Base, engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create any static models if added later; Excel tables are created on ingest.
    try:
        Base.metadata.create_all(bind=engine)
    except OperationalError as exc:
        hint = (
            "PostgreSQL is not reachable. Start it first, for example from the project folder: "
            "`docker compose up -d` (Docker Desktop must be running on Windows). "
            "Then confirm DATABASE_URL in `.env` matches host, port, user, password, and database name."
        )
        logger.error("%s Original error: %s", hint, exc)
        raise RuntimeError(hint) from exc
    yield


app = FastAPI(
    title="Business Information Retrieval Chatbot",
    description="Phase-1 MVP: Excel → PostgreSQL, rule-based NL → safe SQL.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
app.include_router(text_to_sql_router)
app.include_router(designer_router)


@app.get("/health")
def health():
    return {"status": "ok"}
