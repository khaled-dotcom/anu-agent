from __future__ import annotations

import json
import logging
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import facebook, groq_client
from .config import ROOT, settings
from .prompts import FALLBACK, build_system_prompt, guard
from .retriever import Retriever, build_context

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("anu-agent")

app = FastAPI(title="ANU Agent", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins or ["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

retriever = Retriever()
PUBLIC = ROOT / "public"
UNANSWERED = ROOT / "data" / "unanswered.jsonl"

_hits: dict[str, deque] = defaultdict(deque)
_fb_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=6))


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    history: list[dict] = Field(default_factory=list)


def rate_limited(key: str) -> bool:
    now = time.time()
    bucket = _hits[key]
    while bucket and now - bucket[0] > 60:
        bucket.popleft()
    if len(bucket) >= settings.rate_limit_per_min:
        return True
    bucket.append(now)
    return False


def log_gap(question: str, hits: list, channel: str, blocked: bool = False) -> None:
    """Record questions the KB could not answer — this list drives KB updates."""
    if hits and not blocked:
        return
    UNANSWERED.parent.mkdir(parents=True, exist_ok=True)
    with UNANSWERED.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "channel": channel,
                    "question": question[:400],
                    "reason": "guard_blocked" if blocked else "no_match",
                },
                ensure_ascii=False,
            )
            + "\n"
        )


def build_messages(message: str, history: list[dict]) -> tuple[list[dict], str, list]:
    hits = retriever.search(message)
    context = build_context(hits)
    system = build_system_prompt(context, getattr(retriever, "last_sync", "غير معروف"))

    messages = [{"role": "system", "content": system}]
    for turn in history[-6:]:
        role = turn.get("role")
        content = (turn.get("content") or "")[:1000]
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})
    return messages, context, hits


@app.get("/api/health")
async def health():
    return {
        "ok": True,
        "chunks": len(retriever.chunks),
        "model": settings.groq_model,
        "groq_key": bool(settings.groq_api_key),
        "facebook": settings.facebook_enabled,
    }


@app.post("/api/chat")
async def chat(request: Request, body: ChatRequest):
    client_ip = request.headers.get("x-forwarded-for", request.client.host).split(",")[0]
    if rate_limited(client_ip):
        return JSONResponse(
            {"error": "استنى شوية وجرّب تاني — في أسئلة كتير في نفس الوقت."},
            status_code=429,
        )

    messages, context, hits = build_messages(body.message, body.history)
    sources = [{"title": h.get("title"), "url": h.get("url")} for h in hits[:3]]

    async def event_stream():
        buffer = []
        try:
            async for token in groq_client.stream(messages):
                buffer.append(token)
                yield f"data: {json.dumps({'type': 'token', 'text': token}, ensure_ascii=False)}\n\n"
        except groq_client.GroqError as exc:
            log.error("groq failed: %s", exc)
            yield f"data: {json.dumps({'type': 'error', 'text': 'الخدمة مش متاحة دلوقتي، جرّب تاني بعد شوية.'}, ensure_ascii=False)}\n\n"
            return

        answer, blocked = guard("".join(buffer), context)
        if blocked:
            log.warning("guard blocked an answer containing unverified numbers")
            yield f"data: {json.dumps({'type': 'replace', 'text': answer}, ensure_ascii=False)}\n\n"

        log_gap(body.message, hits, "web", blocked)
        payload = {"type": "done", "sources": sources if not blocked else []}
        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------- Messenger

@app.get("/webhook")
async def webhook_verify(request: Request):
    params = request.query_params
    if (
        params.get("hub.mode") == "subscribe"
        and params.get("hub.verify_token") == settings.fb_verify_token
        and settings.fb_verify_token
    ):
        return PlainTextResponse(params.get("hub.challenge", ""))
    return PlainTextResponse("verification failed", status_code=403)


async def answer_on_messenger(sender_id: str, text: str) -> None:
    await facebook.send_action(sender_id, "typing_on")
    history = list(_fb_history[sender_id])
    messages, context, hits = build_messages(text, history)
    try:
        raw = await groq_client.complete(messages)
        answer, blocked = guard(raw, context)
    except groq_client.GroqError as exc:
        log.error("groq failed on messenger: %s", exc)
        answer, blocked = FALLBACK, False

    if hits and not blocked:
        links = "\n".join(f"- {h['url']}" for h in hits[:2] if h.get("url"))
        if links and "http" not in answer:
            answer = f"{answer}\n\nالمصدر:\n{links}"

    _fb_history[sender_id].append({"role": "user", "content": text})
    _fb_history[sender_id].append({"role": "assistant", "content": answer})
    log_gap(text, hits, "messenger", blocked)
    await facebook.send_text(sender_id, answer)


@app.post("/webhook")
async def webhook_receive(request: Request, tasks: BackgroundTasks):
    raw = await request.body()
    if not facebook.verify_signature(raw, request.headers.get("x-hub-signature-256")):
        return PlainTextResponse("bad signature", status_code=403)

    payload = json.loads(raw or b"{}")
    if payload.get("object") != "page":
        return PlainTextResponse("ignored")

    # Reply 200 immediately; do the slow work after, or Meta disables the hook.
    for sender_id, text in facebook.extract_messages(payload):
        tasks.add_task(answer_on_messenger, sender_id, text)
    return PlainTextResponse("EVENT_RECEIVED")


# ------------------------------------------------------------------ static

@app.get("/")
async def index():
    return FileResponse(PUBLIC / "index.html")


app.mount("/", StaticFiles(directory=PUBLIC), name="public")
