"""FastAPI surface. Port 8001 (classifier owns 8000, UI owns 3000).

Run:  uvicorn agent.api:app --reload --host 0.0.0.0 --port 8001

POST /analyze accepts EITHER:
  - application/json: Reed's parser output (structured entries, or the
    current minimal {"filename","status"} shape), or
  - multipart/form-data with a `file` field: a raw log file, parsed by the
    built-in fallback parser.
Both return an AnalysisResult. Mirrors the classifier's conventions,
including CORS for the Next.js dev server on localhost:3000.
"""

import json

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .adapters import to_parsed_log
from .contracts import AnalysisResult
from .core import analyze
from .providers import get_provider

app = FastAPI(title="Rosetta Analysis Agent", version=__version__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/analyze", response_model=AnalysisResult)
async def analyze_endpoint(request: Request, mock: bool = False) -> AnalysisResult:
    content_type = request.headers.get("content-type", "")

    if content_type.startswith("multipart/"):
        form = await request.form()
        upload = form.get("file")
        if upload is None or isinstance(upload, str):
            raise HTTPException(422, "multipart request must include a 'file' field")
        raw = (await upload.read()).decode("utf-8", errors="replace")
        if not raw.strip():
            raise HTTPException(422, "uploaded file is empty")
        try:
            parsed = to_parsed_log(raw, log_source=upload.filename or "upload")
        except ValueError as exc:
            raise HTTPException(422, str(exc))
    else:
        try:
            body = await request.json()
        except json.JSONDecodeError:
            raise HTTPException(
                415, "send application/json (parser output) or multipart/form-data "
                     "with a 'file' field (raw log)")
        try:
            parsed = to_parsed_log(body)
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    return analyze(parsed, provider=get_provider(mock=mock or None))
