import os
from fastapi import FastAPI
from dotenv import load_dotenv

from .exotel_gateway import router as exotel_router

load_dotenv()

app = FastAPI(title="Vocode + Sarvam + Exotel")

@app.get("/healthz")
def health():
    return {"ok": True}

app.include_router(exotel_router)
