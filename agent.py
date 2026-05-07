"""
Email Agent — Google ADK + Gmail MCP Tools
Capabilities: send, read inbox, get full email, reply
"""

import os
import json
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types

from mcp_server.tools import send_email, read_inbox, get_email, reply_email

# ── ADK Agent ────────────────────────────────────────────────────────────────

email_agent = LlmAgent(
    name="EmailAgent",
    model="gemini-2.5-flash",
    description="An AI email agent that can send, read, and reply to Gmail emails.",
    instruction="""You are a highly intelligent executive email assistant. You have direct access to Gmail.

RULES:
- When asked to send an email, DO IT immediately — do not ask for confirmation or extra details
- Write professional, concise, well-formatted emails automatically
- Never use placeholder text like [Your Name] — sign off as "Meet" 
- Never ask "what should I write?" — use context to draft it yourself
- When reading inbox, give a clean structured summary
- When replying, match the tone of the original email
- Be decisive and action-oriented like a real executive assistant

EMAIL STYLE:
- Professional but warm tone
- Clear subject lines
- Proper greeting and sign-off
- Concise paragraphs
- Always sign as: Meet Bhorania""",
    tools=[
        FunctionTool(func=send_email),
        FunctionTool(func=read_inbox),
        FunctionTool(func=get_email),
        FunctionTool(func=reply_email),
    ],
)

session_service = InMemorySessionService()
APP_NAME = "email-agent"


async def run_agent(user_message: str, session_id: str = "default") -> dict:
    os.environ["GOOGLE_API_KEY"] = os.getenv("GOOGLE_API_KEY", "")

    runner = Runner(
        agent=email_agent,
        app_name=APP_NAME,
        session_service=session_service,
    )

    existing = await session_service.get_session(
        app_name=APP_NAME, user_id="user", session_id=session_id
    )
    if not existing:
        await session_service.create_session(
            app_name=APP_NAME, user_id="user", session_id=session_id
        )

    message = genai_types.Content(
        role="user",
        parts=[genai_types.Part(text=user_message)],
    )

    final_text = ""
    tool_calls = []

    async for event in runner.run_async(
        user_id="user",
        session_id=session_id,
        new_message=message,
    ):
        if event.is_final_response():
            if event.content and event.content.parts:
                final_text = event.content.parts[0].text or ""
        if hasattr(event, "content") and event.content:
            for part in event.content.parts:
                if hasattr(part, "function_call") and part.function_call:
                    tool_calls.append(f"🔧 {part.function_call.name}(...)")

    return {
        "response": final_text,
        "tool_calls": tool_calls,
        "session_id": session_id,
    }


# ── FastAPI ──────────────────────────────────────────────────────────────────

app = FastAPI(title="Email Agent API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = "default"


class SendRequest(BaseModel):
    to: str
    subject: str
    body: str


@app.post("/api/chat")
async def chat(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(400, "Message cannot be empty.")
    result = await run_agent(req.message.strip(), req.session_id or "default")
    return result


@app.post("/api/send")
async def send(req: SendRequest):
    """Direct send endpoint — no agent needed."""
    result = send_email(req.to, req.subject, req.body)
    if not result["success"]:
        raise HTTPException(500, result.get("error"))
    return result


@app.get("/api/inbox")
async def inbox(limit: int = 10):
    result = read_inbox(limit)
    if not result["success"]:
        raise HTTPException(500, result.get("error"))
    return result


@app.get("/api/email/{message_id}")
async def email(message_id: str):
    result = get_email(message_id)
    if not result["success"]:
        raise HTTPException(500, result.get("error"))
    return result


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "agent": "EmailAgent",
        "tools": ["send_email", "read_inbox", "get_email", "reply_email"],
    }


# Serve frontend in production
_frontend = os.path.join(os.path.dirname(__file__), "frontend", "dist")
if os.path.exists(_frontend):
    app.mount("/assets", StaticFiles(directory=os.path.join(_frontend, "assets")), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        return FileResponse(os.path.join(_frontend, "index.html"))
