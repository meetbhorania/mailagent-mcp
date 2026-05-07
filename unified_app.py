"""
MailAgent — Unified App
Single URL, Google OAuth, persistent sessions.
Each user signs in with their own Gmail — no session IDs ever exposed.
"""

import os
import base64
import hashlib
import secrets
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types

# ── Config ────────────────────────────────────────────────────────────────────

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]

import json, tempfile
_creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
if _creds_json:
    _tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
    _tmp.write(_creds_json)
    _tmp.close()
    CREDENTIALS_FILE = _tmp.name
else:
    CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), "credentials.json")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

# In-memory stores
_tokens: dict[str, dict] = {}       # session_id -> Gmail token
_oauth_state: dict[str, dict] = {}  # state -> {code_verifier}

_adk_sessions = InMemorySessionService()
APP_NAME = "mailagent"

# ── Cookie helpers ────────────────────────────────────────────────────────────

def _get_sid(request: Request) -> Optional[str]:
    return request.cookies.get("ma_sid")

def _require_token(request: Request) -> dict:
    sid = _get_sid(request)
    if not sid or sid not in _tokens:
        raise HTTPException(401, "Not authenticated")
    return _tokens[sid]

# ── Gmail helpers ─────────────────────────────────────────────────────────────

def _get_gmail(token_data: dict):
    creds = Credentials(
        token=token_data.get("token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri=token_data.get("token_uri"),
        client_id=token_data.get("client_id"),
        client_secret=token_data.get("client_secret"),
        scopes=token_data.get("scopes"),
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleRequest())
        token_data["token"] = creds.token
    return build("gmail", "v1", credentials=creds)

def _send_email(token, to, subject, body):
    try:
        service = _get_gmail(token)
        msg = MIMEMultipart()
        msg["to"] = to
        msg["subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return {"success": True, "message_id": sent["id"], "to": to, "subject": subject}
    except Exception as e:
        return {"success": False, "error": str(e)}

def _read_inbox(token, max_results=10):
    try:
        service = _get_gmail(token)
        results = service.users().messages().list(
            userId="me", labelIds=["INBOX"], maxResults=min(max_results, 50)
        ).execute()
        emails = []
        for msg in results.get("messages", []):
            m = service.users().messages().get(
                userId="me", id=msg["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date"]
            ).execute()
            h = {x["name"]: x["value"] for x in m["payload"]["headers"]}
            emails.append({
                "id": msg["id"],
                "from": h.get("From", ""),
                "subject": h.get("Subject", ""),
                "date": h.get("Date", ""),
                "snippet": m.get("snippet", ""),
            })
        return {"success": True, "count": len(emails), "emails": emails}
    except Exception as e:
        return {"success": False, "error": str(e), "emails": []}

def _get_email(token, message_id):
    try:
        service = _get_gmail(token)
        m = service.users().messages().get(userId="me", id=message_id, format="full").execute()
        h = {x["name"]: x["value"] for x in m["payload"]["headers"]}
        body = ""
        if "parts" in m["payload"]:
            for part in m["payload"]["parts"]:
                if part["mimeType"] == "text/plain":
                    data = part["body"].get("data", "")
                    body = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
                    break
        else:
            data = m["payload"]["body"].get("data", "")
            if data:
                body = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
        return {"success": True, "from": h.get("From", ""), "subject": h.get("Subject", ""), "date": h.get("Date", ""), "body": body}
    except Exception as e:
        return {"success": False, "error": str(e)}

def _reply_email(token, message_id, body):
    try:
        service = _get_gmail(token)
        original = service.users().messages().get(
            userId="me", id=message_id, format="metadata",
            metadataHeaders=["From", "Subject"]
        ).execute()
        h = {x["name"]: x["value"] for x in original["payload"]["headers"]}
        msg = MIMEMultipart()
        msg["to"] = h.get("From", "")
        msg["subject"] = "Re: " + h.get("Subject", "")
        msg.attach(MIMEText(body, "plain"))
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        sent = service.users().messages().send(
            userId="me", body={"raw": raw, "threadId": original.get("threadId")}
        ).execute()
        return {"success": True, "message_id": sent["id"], "replied_to": h.get("From", "")}
    except Exception as e:
        return {"success": False, "error": str(e)}

def _search_emails(token, query, max_results=10):
    try:
        service = _get_gmail(token)
        results = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
        emails = []
        for msg in results.get("messages", []):
            m = service.users().messages().get(
                userId="me", id=msg["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date"]
            ).execute()
            h = {x["name"]: x["value"] for x in m["payload"]["headers"]}
            emails.append({
                "id": msg["id"],
                "from": h.get("From", ""),
                "subject": h.get("Subject", ""),
                "date": h.get("Date", ""),
                "snippet": m.get("snippet", ""),
            })
        return {"success": True, "query": query, "count": len(emails), "emails": emails}
    except Exception as e:
        return {"success": False, "error": str(e), "emails": []}

# ── ADK Agent ─────────────────────────────────────────────────────────────────

def _make_tools(token):
    def send_email(to: str, subject: str, body: str) -> dict:
        """Send an email. Args: to, subject, body."""
        return _send_email(token, to, subject, body)
    def read_inbox(max_results: int = 10) -> dict:
        """Read inbox emails. Args: max_results."""
        return _read_inbox(token, max_results)
    def get_email(message_id: str) -> dict:
        """Get full email content. Args: message_id."""
        return _get_email(token, message_id)
    def reply_to_email(message_id: str, body: str) -> dict:
        """Reply to an email. Args: message_id, body."""
        return _reply_email(token, message_id, body)
    def search_emails(query: str, max_results: int = 10) -> dict:
        """Search emails. Args: query, max_results."""
        return _search_emails(token, query, max_results)
    return [FunctionTool(func=f) for f in [send_email, read_inbox, get_email, reply_to_email, search_emails]]

async def run_agent(token, message, session_id, user_email=""):
    user_name = user_email.split("@")[0].replace(".", " ").title()
    os.environ["GOOGLE_API_KEY"] = GOOGLE_API_KEY
    agent = LlmAgent(
        name="MailAgent",
        model="gemini-2.5-flash",
        description="Executive email assistant with Gmail access.",
        instruction="""You are an executive email assistant with direct Gmail access.
- Send emails immediately when asked, no confirmation needed
- Write professional well-formatted emails automatically
- Never use placeholders like [Your Name]
- Give clean summaries when reading inbox
- Be decisive and action-oriented
- Sign emails as """ + user_name + """
Use tools: send_email, read_inbox, get_email, reply_to_email, search_emails""",
        tools=_make_tools(token),
    )
    runner = Runner(agent=agent, app_name=APP_NAME, session_service=_adk_sessions)
    existing = await _adk_sessions.get_session(app_name=APP_NAME, user_id=session_id, session_id=session_id)
    if not existing:
        await _adk_sessions.create_session(app_name=APP_NAME, user_id=session_id, session_id=session_id)
    content = genai_types.Content(role="user", parts=[genai_types.Part(text=message)])
    final_text = ""
    tool_calls = []
    async for event in runner.run_async(user_id=session_id, session_id=session_id, new_message=content):
        if event.is_final_response():
            if event.content and event.content.parts:
                final_text = event.content.parts[0].text or ""
        if hasattr(event, "content") and event.content:
            for part in event.content.parts:
                if hasattr(part, "function_call") and part.function_call:
                    tool_calls.append(f"🔧 {part.function_call.name}(...)")
    return {"response": final_text, "tool_calls": tool_calls}

# ── FastAPI ───────────────────────────────────────────────────────────────────

app = FastAPI(title="MailAgent", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# ── Auth ──────────────────────────────────────────────────────────────────────

@app.get("/auth/login")
async def auth_login(request: Request):
    if not os.path.exists(CREDENTIALS_FILE):
        raise HTTPException(500, "credentials.json not found")
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b"=").decode()
    flow = Flow.from_client_secrets_file(
        CREDENTIALS_FILE, scopes=SCOPES,
        redirect_uri=f"{BASE_URL}/auth/callback",
    )
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        code_challenge=code_challenge,
        code_challenge_method="S256",
    )
    _oauth_state[state] = {"code_verifier": code_verifier}
    return RedirectResponse(auth_url)

@app.get("/auth/callback")
async def auth_callback(request: Request):
    state = request.query_params.get("state")
    code = request.query_params.get("code")
    if not state or not code or state not in _oauth_state:
        return RedirectResponse("/")
    code_verifier = _oauth_state.pop(state, {}).get("code_verifier")
    flow = Flow.from_client_secrets_file(
        CREDENTIALS_FILE, scopes=SCOPES, state=state,
        redirect_uri=f"{BASE_URL}/auth/callback",
    )
    flow.fetch_token(code=code, code_verifier=code_verifier)
    creds = flow.credentials
    user_service = build("oauth2", "v2", credentials=creds)
    user_info = user_service.userinfo().get().execute()
    user_email = user_info.get("email", "")
    session_id = secrets.token_urlsafe(32)
    _tokens[session_id] = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or SCOPES),
        "email": user_email,
    }
    response = RedirectResponse(f"{BASE_URL}/")
    response.set_cookie(
        key="ma_sid",
        value=session_id,
        max_age=86400 * 7,
        httponly=True,
        samesite="lax",
        secure=False,
    )
    return response

@app.get("/auth/logout")
async def auth_logout(request: Request):
    sid = _get_sid(request)
    if sid and sid in _tokens:
        del _tokens[sid]
    response = RedirectResponse("/")
    response.delete_cookie("ma_sid")
    return response

# ── API ───────────────────────────────────────────────────────────────────────

@app.get("/api/me")
async def me(request: Request):
    sid = _get_sid(request)
    if not sid or sid not in _tokens:
        return {"authenticated": False}
    return {"authenticated": True, "email": _tokens[sid].get("email", "")}

class ChatRequest(BaseModel):
    message: str

@app.post("/api/chat")
async def chat(req: ChatRequest, request: Request):
    token = _require_token(request)
    sid = _get_sid(request)
    user_email = _tokens[sid].get("email", "")
    result = await run_agent(token, req.message.strip(), sid, user_email)
    return result

class SendRequest(BaseModel):
    to: str
    subject: str
    body: str

@app.post("/api/send")
async def send(req: SendRequest, request: Request):
    token = _require_token(request)
    result = _send_email(token, req.to, req.subject, req.body)
    if not result["success"]:
        raise HTTPException(500, result.get("error"))
    return result

@app.get("/api/inbox")
async def inbox(request: Request, limit: int = 15):
    token = _require_token(request)
    return _read_inbox(token, limit)

@app.get("/api/email/{message_id}")
async def get_email_route(message_id: str, request: Request):
    token = _require_token(request)
    return _get_email(token, message_id)

@app.get("/api/health")
async def health():
    return {"status": "ok", "active_sessions": len(_tokens)}

# ── Serve React frontend ──────────────────────────────────────────────────────

_dist = os.path.join(os.path.dirname(__file__), "frontend", "dist")

if os.path.exists(_dist):
    app.mount("/assets", StaticFiles(directory=os.path.join(_dist, "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def spa(full_path: str):
        from fastapi.responses import FileResponse
        return FileResponse(os.path.join(_dist, "index.html"))

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    print(f"MailAgent running at http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)