import asyncio
import hmac
import json
import os
import re
import shutil
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

import bot
import pipeline
import storage
from connectors import REGISTRY
from connectors.base import ReleaseMetadata

REPLICATE_TOKEN = os.getenv("REPLICATE_API_TOKEN", "")
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:8080").split(",")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
BOT_ENABLED = os.getenv("BOT_ENABLED", "1") == "1"
JOB_ID = r"^[A-Za-z0-9_-]{4,64}$"


def require_admin(authorization: str = Header(default="")):
    """Protect operator-only and sensitive resource endpoints."""
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=503, detail="ADMIN_TOKEN is not configured.")
    scheme, _, credentials = authorization.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(credentials, ADMIN_TOKEN):
        raise HTTPException(status_code=401, detail="Missing or invalid admin token.")


@asynccontextmanager
async def lifespan(_: FastAPI):
    storage.init()
    task = asyncio.create_task(bot.run_forever()) if BOT_ENABLED and REPLICATE_TOKEN else None
    yield
    if task:
        task.cancel()


app = FastAPI(title="AI Music Ops API", version="0.03", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in ALLOWED_ORIGINS],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class GenerationRequest(BaseModel):
    track_name: str = Field(default="Untitled track", max_length=80)
    prompt: str = Field(min_length=3, max_length=1000)
    duration: int = Field(default=190, ge=pipeline.MIN_TRACK_SECONDS, le=300)
    lyrics: str = Field(default="", max_length=6000)
    lyrics_mode: str = Field(default="ai", pattern="^(ai|user)$")
    vocal_style: str = Field(default="", max_length=160)


class ReleaseRequest(BaseModel):
    job_id: str = Field(pattern=JOB_ID)
    connector: str = "routenote"
    metadata: ReleaseMetadata


class SubmitMark(BaseModel):
    routenote_ref: str = Field(min_length=1, max_length=300, description="Release URL or UPC from RouteNote")


class BotBrief(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    prompt: str = Field(min_length=3, max_length=1000)
    artist: str = Field(default="AI Music Ops", max_length=120)
    genre: str = "Electronic"
    label: str = "AI Music Ops"
    duration: int = Field(default=190, ge=pipeline.MIN_TRACK_SECONDS, le=300)



@app.get("/")
async def root():
    return {"name": "AI Music Ops API", "version": "0.03", "docs": "/docs"}


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "provider_configured": bool(REPLICATE_TOKEN),
        "auth_required": bool(ADMIN_TOKEN),
        "bot": BOT_ENABLED,
        "connectors": list(REGISTRY),
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "model": pipeline.MODEL,
        "vocal_model_configured": os.getenv("MODEL_SUPPORTS_VOCALS", "0") == "1",
        "lyrics_model_configured": bool(os.getenv("LYRICS_MODEL", "")),
        "license_commercial_confirmed": pipeline.MODEL_COMMERCIAL,
        "min_track_seconds": pipeline.MIN_TRACK_SECONDS,
    }


@app.post("/api/generations")
async def create_generation(request: GenerationRequest, _: None = Depends(require_admin)):
    if not REPLICATE_TOKEN:
        raise HTTPException(status_code=503, detail="Backend is missing REPLICATE_API_TOKEN.")
    if os.getenv("MODEL_SUPPORTS_VOCALS", "0") != "1":
        raise HTTPException(status_code=503, detail="Configure a vocal-capable Replicate model and set MODEL_SUPPORTS_VOCALS=1. Instrumental-only generation is intentionally disabled in Zi Studio.")
    if not shutil.which("ffmpeg"):
        raise HTTPException(status_code=503, detail="ffmpeg is not installed on the backend.")
    try:
        job = await pipeline.start_long_generation(request.track_name, request.prompt, request.duration, request.lyrics, request.vocal_style)
    except (httpx.HTTPError, RuntimeError) as e:
        raise HTTPException(status_code=502, detail=f"Could not start generation: {e}")
    return pipeline.public(job)



class LyricsRequest(BaseModel):
    prompt: str = Field(min_length=5, max_length=1000)
    title: str = Field(default="Untitled song", max_length=80)
    genre: str = Field(default="Pop", max_length=60)
    mood: str = Field(default="Uplifting", max_length=60)
    language: str = Field(default="English", max_length=40)


@app.post("/api/lyrics")
async def generate_lyrics(req: LyricsRequest, _: None = Depends(require_admin)):
    model = os.getenv("LYRICS_MODEL", "meta/meta-llama-3-8b-instruct")
    if not REPLICATE_TOKEN or not model:
        raise HTTPException(status_code=503, detail="Configure REPLICATE_API_TOKEN on the backend to enable AI-written lyrics.")
    prompt = (f"Write original, singable {req.language} song lyrics for '{req.title}'. Genre: {req.genre}. Mood: {req.mood}. "
              f"Creative brief: {req.prompt}. Structure: [Verse 1], [Pre-Chorus], [Chorus], [Verse 2], [Bridge], [Final Chorus]. Keep the full lyric sheet under 3500 characters. "
              "Use memorable but original phrasing. Output only lyrics with section labels.")
    async with httpx.AsyncClient(timeout=90) as client:
        meta = await client.get(f"https://api.replicate.com/v1/models/{model}", headers={"Authorization": f"Bearer {REPLICATE_TOKEN}"})
        meta.raise_for_status()
        version = (meta.json().get("latest_version") or {}).get("id")
        extra = json.loads(os.getenv("LYRICS_EXTRA_INPUT", '{"max_new_tokens": 1200, "temperature": 0.8}'))
        payload = {"input": {os.getenv("LYRICS_PROMPT_KEY", "prompt"): prompt, **extra}}
        if version:
            payload["version"] = version
            url = "https://api.replicate.com/v1/predictions"
        else:
            url = f"https://api.replicate.com/v1/models/{model}/predictions"
        response = await client.post(url, headers={"Authorization": f"Bearer {REPLICATE_TOKEN}", "Content-Type":"application/json"}, json=payload)
        response.raise_for_status()
        prediction = response.json()
        pid = prediction.get("id")
        for _ in range(60):
            if prediction.get("status") in ("succeeded", "failed", "canceled"):
                break
            await asyncio.sleep(2)
            check = await client.get(f"https://api.replicate.com/v1/predictions/{pid}", headers={"Authorization": f"Bearer {REPLICATE_TOKEN}"})
            check.raise_for_status(); prediction = check.json()
        if prediction.get("status") != "succeeded":
            raise HTTPException(status_code=502, detail="Lyrics model did not complete successfully.")
        output = prediction.get("output")
        lyrics = "\n".join(map(str, output)) if isinstance(output, list) else str(output or "")
        return {"lyrics": lyrics.strip()}

@app.get("/api/generations/{job_id}")
async def get_generation(job_id: str, _: None = Depends(require_admin)):
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,64}", job_id):
        raise HTTPException(status_code=400, detail="Invalid job id.")
    try:
        return pipeline.public(await pipeline.refresh_job(job_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="Generation job not found.")
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Could not retrieve generation status from Replicate.")


@app.get("/api/generations/{job_id}/audio")
async def get_audio(job_id: str, _: None = Depends(require_admin)):
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,64}", job_id):
        raise HTTPException(status_code=400, detail="Invalid job id.")
    job = storage.get("jobs", job_id)
    path = (job or {}).get("preview_path")
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Audio not available.")
    return FileResponse(path, media_type="audio/mpeg", filename=f"{job_id}.mp3")


@app.post("/api/releases/validate")
async def validate_release(req: ReleaseRequest):
    if req.connector not in REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown connector.")
    return REGISTRY[req.connector].validate(req.metadata)


@app.post("/api/releases")
async def create_release(req: ReleaseRequest, _: None = Depends(require_admin)):
    if req.connector not in REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown connector.")
    try:
        return await pipeline.build_release(req.job_id, req.metadata, req.connector)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except (httpx.HTTPError, OSError) as e:
        raise HTTPException(status_code=502, detail=f"Could not prepare release files: {e}")


@app.get("/api/releases")
async def list_releases(_: None = Depends(require_admin)):
    return storage.list_("releases")


@app.get("/api/releases/{release_id}")
async def get_release(release_id: str, _: None = Depends(require_admin)):
    rel = storage.get("releases", release_id)
    if not rel:
        raise HTTPException(status_code=404, detail="Release not found.")
    return rel


@app.get("/api/releases/{release_id}/package")
async def download_package(release_id: str, _: None = Depends(require_admin)):
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,64}", release_id):
        raise HTTPException(status_code=400, detail="Invalid release id.")
    rel = storage.get("releases", release_id)
    if not rel:
        raise HTTPException(status_code=404, detail="Package not available.")
    path = rel.get("package_path")
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Package not available.")
    return FileResponse(path, media_type="application/zip",
                        filename=os.path.basename(path))


@app.post("/api/releases/{release_id}/submitted")
async def mark_submitted(release_id: str, body: SubmitMark, _: None = Depends(require_admin)):
    if not storage.get("releases", release_id):
        raise HTTPException(status_code=404, detail="Release not found.")
    storage.put("releases", {"id": release_id, "status": "submitted", "routenote_ref": body.routenote_ref})
    return storage.get("releases", release_id)


@app.post("/api/bot/queue")
async def bot_enqueue(brief: BotBrief, _: None = Depends(require_admin)):
    return bot.enqueue(brief.model_dump())


@app.get("/api/bot/queue")
async def bot_queue(_: None = Depends(require_admin)):
    return storage.list_("queue")
