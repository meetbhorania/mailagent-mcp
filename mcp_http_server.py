"""
Gmail MCP Server — FastMCP over Streamable HTTP
Public URL, multi-user, works with any MCP client or browser.

Run:
    python mcp_http_server.py

Connect as developer:
    MCP endpoint: https://your-domain.com/mcp
    
Connect as user:
    Visit: https://your-domain.com
"""

import os
import json
import base64
import secrets
import sys
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.requests import Request
from starlette.middleware.sessions import SessionMiddleware

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

# ── Config ──────────────────────────────────────────────────────────────────

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]

CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), "credentials.json")
SECRET_KEY = os.getenv("SESSION_SECRET", secrets.token_hex(32))
BASE_URL = os.getenv("BASE_URL", "http://localhost:8002")

# In-memory session store (swap for Redis in production)
_user_tokens: dict[str, dict] = {}


# ── Gmail helpers ────────────────────────────────────────────────────────────

def _get_service_for_token(token_data: dict):
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


def _get_token_for_session(session_id: str) -> Optional[dict]:
    return _user_tokens.get(session_id)


# ── FastMCP server ───────────────────────────────────────────────────────────

mcp = FastMCP(
    name="Gmail MCP Server",
    instructions="""You have access to the user's Gmail account.
You can send emails, read their inbox, search emails, and reply.
Always be professional. Ask for session_id when tools require authentication.""",
)


@mcp.tool()
def send_gmail(session_id: str, to: str, subject: str, body: str) -> dict:
    """
    Send an email via the user's Gmail account.

    Args:
        session_id: User session ID (from login)
        to: Recipient email address
        subject: Email subject line
        body: Full email body text
    """
    token = _get_token_for_session(session_id)
    if not token:
        return {"success": False, "error": "Not authenticated. Please login first at /auth/login"}
    try:
        service = _get_service_for_token(token)
        message = MIMEMultipart()
        message["to"] = to
        message["subject"] = subject
        message.attach(MIMEText(body, "plain"))
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return {"success": True, "message_id": sent["id"], "to": to, "subject": subject}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def read_inbox(session_id: str, max_results: int = 10) -> dict:
    """
    Read recent emails from the user's Gmail inbox.

    Args:
        session_id: User session ID (from login)
        max_results: Number of emails to retrieve (default 10, max 50)
    """
    token = _get_token_for_session(session_id)
    if not token:
        return {"success": False, "error": "Not authenticated. Please login first at /auth/login"}
    try:
        service = _get_service_for_token(token)
        results = service.users().messages().list(
            userId="me", labelIds=["INBOX"], maxResults=min(max_results, 50)
        ).execute()
        messages = results.get("messages", [])
        emails = []
        for msg in messages:
            m = service.users().messages().get(
                userId="me", id=msg["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date"]
            ).execute()
            headers = {h["name"]: h["value"] for h in m["payload"]["headers"]}
            emails.append({
                "id": msg["id"],
                "from": headers.get("From", ""),
                "subject": headers.get("Subject", ""),
                "date": headers.get("Date", ""),
                "snippet": m.get("snippet", ""),
            })
        return {"success": True, "count": len(emails), "emails": emails}
    except Exception as e:
        return {"success": False, "error": str(e), "emails": []}


@mcp.tool()
def get_email(session_id: str, message_id: str) -> dict:
    """
    Get the full content of a specific Gmail message.

    Args:
        session_id: User session ID (from login)
        message_id: The Gmail message ID
    """
    token = _get_token_for_session(session_id)
    if not token:
        return {"success": False, "error": "Not authenticated. Please login first at /auth/login"}
    try:
        service = _get_service_for_token(token)
        m = service.users().messages().get(userId="me", id=message_id, format="full").execute()
        headers = {h["name"]: h["value"] for h in m["payload"]["headers"]}
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
        return {
            "success": True,
            "id": message_id,
            "from": headers.get("From", ""),
            "subject": headers.get("Subject", ""),
            "date": headers.get("Date", ""),
            "body": body,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def search_gmail(session_id: str, query: str, max_results: int = 10) -> dict:
    """
    Search Gmail using Gmail search syntax.

    Args:
        session_id: User session ID (from login)
        query: Gmail search query e.g. 'from:john@example.com', 'subject:meeting', 'is:unread'
        max_results: Maximum results to return
    """
    token = _get_token_for_session(session_id)
    if not token:
        return {"success": False, "error": "Not authenticated. Please login first at /auth/login"}
    try:
        service = _get_service_for_token(token)
        results = service.users().messages().list(
            userId="me", q=query, maxResults=max_results
        ).execute()
        messages = results.get("messages", [])
        emails = []
        for msg in messages:
            m = service.users().messages().get(
                userId="me", id=msg["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date"]
            ).execute()
            headers = {h["name"]: h["value"] for h in m["payload"]["headers"]}
            emails.append({
                "id": msg["id"],
                "from": headers.get("From", ""),
                "subject": headers.get("Subject", ""),
                "date": headers.get("Date", ""),
                "snippet": m.get("snippet", ""),
            })
        return {"success": True, "query": query, "count": len(emails), "emails": emails}
    except Exception as e:
        return {"success": False, "error": str(e), "emails": []}


@mcp.tool()
def reply_to_email(session_id: str, message_id: str, body: str) -> dict:
    """
    Reply to an existing Gmail email.

    Args:
        session_id: User session ID (from login)
        message_id: The Gmail message ID to reply to
        body: The reply body text
    """
    token = _get_token_for_session(session_id)
    if not token:
        return {"success": False, "error": "Not authenticated. Please login first at /auth/login"}
    try:
        service = _get_service_for_token(token)
        original = service.users().messages().get(
            userId="me", id=message_id, format="metadata",
            metadataHeaders=["From", "Subject", "Message-ID"]
        ).execute()
        headers = {h["name"]: h["value"] for h in original["payload"]["headers"]}
        to = headers.get("From", "")
        subject = "Re: " + headers.get("Subject", "")
        thread_id = original.get("threadId")
        message = MIMEMultipart()
        message["to"] = to
        message["subject"] = subject
        message.attach(MIMEText(body, "plain"))
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        sent = service.users().messages().send(
            userId="me", body={"raw": raw, "threadId": thread_id}
        ).execute()
        return {"success": True, "message_id": sent["id"], "replied_to": to}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── OAuth routes ─────────────────────────────────────────────────────────────

async def homepage(request: Request):
    session_id = request.session.get("session_id")
    user_email = request.session.get("user_email", "")
    is_logged_in = session_id and session_id in _user_tokens

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Gmail MCP Server</title>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600&family=DM+Mono:wght@300;400&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Outfit',sans-serif;background:#fff;color:#0f0f10;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}}
.card{{max-width:480px;width:100%;text-align:center}}
.logo{{width:52px;height:52px;background:linear-gradient(135deg,#7c3aed,#ec4899);border-radius:14px;display:flex;align-items:center;justify-content:center;margin:0 auto 24px;font-size:22px}}
h1{{font-size:28px;font-weight:600;letter-spacing:-0.03em;margin-bottom:8px}}
.sub{{font-size:14px;color:#6b6b7a;margin-bottom:32px;line-height:1.6}}
.btn{{display:inline-flex;align-items:center;gap:10px;background:linear-gradient(135deg,#7c3aed,#ec4899);color:#fff;border:none;border-radius:10px;padding:13px 28px;font-family:'Outfit',sans-serif;font-size:14px;font-weight:500;cursor:pointer;text-decoration:none;transition:opacity 0.2s}}
.btn:hover{{opacity:0.87}}
.btn-outline{{background:transparent;border:1px solid rgba(0,0,0,0.12);color:#0f0f10;margin-left:10px}}
.btn-outline:hover{{background:#f5f5f7}}
.status{{display:inline-flex;align-items:center;gap:6px;background:#f0fdf4;border:1px solid #bbf7d0;color:#16a34a;border-radius:100px;padding:6px 14px;font-size:12px;font-family:'DM Mono',monospace;margin-bottom:24px}}
.dot{{width:6px;height:6px;border-radius:50%;background:#16a34a}}
.features{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:32px 0;text-align:left}}
.feature{{background:#f9f9fb;border:1px solid rgba(0,0,0,0.06);border-radius:10px;padding:14px 16px}}
.feature-title{{font-size:13px;font-weight:500;margin-bottom:3px}}
.feature-sub{{font-size:11px;color:#6b6b7a;font-family:'DM Mono',monospace}}
.dev-section{{background:#f9f9fb;border:1px solid rgba(0,0,0,0.07);border-radius:10px;padding:16px;margin-top:24px;text-align:left}}
.dev-title{{font-size:12px;font-family:'DM Mono',monospace;color:#6b6b7a;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:8px}}
.endpoint{{font-family:'DM Mono',monospace;font-size:12px;background:#fff;border:1px solid rgba(0,0,0,0.08);border-radius:6px;padding:8px 12px;color:#7c3aed;word-break:break-all}}
</style>
</head>
<body>
<div class="card">
  <div class="logo">✉</div>
  <h1>Gmail MCP Server</h1>
  <p class="sub">A public MCP server that gives AI agents access to Gmail.<br>Sign in with Google to get your session ID.</p>

  {'<div class="status"><span class="dot"></span>Signed in as ' + user_email + '</div><br>' if is_logged_in else ''}

  <div>
    {'<a href="/auth/logout" class="btn btn-outline">Sign out</a><a href="/session" class="btn">Get Session ID</a>' if is_logged_in else '<a href="/auth/login" class="btn">Sign in with Google</a>'}
  </div>

  <div class="features">
    <div class="feature"><div class="feature-title">Send Emails</div><div class="feature-sub">send_gmail tool</div></div>
    <div class="feature"><div class="feature-title">Read Inbox</div><div class="feature-sub">read_inbox tool</div></div>
    <div class="feature"><div class="feature-title">Search Gmail</div><div class="feature-sub">search_gmail tool</div></div>
    <div class="feature"><div class="feature-title">Reply to Emails</div><div class="feature-sub">reply_to_email tool</div></div>
  </div>

  <div class="dev-section">
    <div class="dev-title">MCP Endpoint for developers</div>
    <div class="endpoint">{BASE_URL}/mcp</div>
  </div>
</div>
</body>
</html>"""
    return HTMLResponse(html)


async def auth_login(request: Request):
    if not os.path.exists(CREDENTIALS_FILE):
        return HTMLResponse("<h2>credentials.json not found.</h2>", status_code=500)

    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

    import hashlib
    import base64 as b64

    # Generate PKCE code verifier and challenge
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = b64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b"=").decode()

    flow = Flow.from_client_secrets_file(
        CREDENTIALS_FILE,
        scopes=SCOPES,
        redirect_uri=f"{BASE_URL}/auth/callback",
    )

    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        code_challenge=code_challenge,
        code_challenge_method="S256",
    )

    request.session["oauth_state"] = state
    request.session["code_verifier"] = code_verifier
    return RedirectResponse(auth_url)


async def auth_callback(request: Request):
    state = request.session.get("oauth_state")
    code_verifier = request.session.get("code_verifier")

    if not state:
        return RedirectResponse("/")

    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

    flow = Flow.from_client_secrets_file(
        CREDENTIALS_FILE,
        scopes=SCOPES,
        state=state,
        redirect_uri=f"{BASE_URL}/auth/callback",
    )

    code = request.query_params.get("code")
    if not code:
        return RedirectResponse("/")

    flow.fetch_token(
        code=code,
        code_verifier=code_verifier,
    )

    creds = flow.credentials

    # Get user email
    user_service = build("oauth2", "v2", credentials=creds)
    user_info = user_service.userinfo().get().execute()
    user_email = user_info.get("email", "")

    # Store token
    session_id = secrets.token_urlsafe(32)
    _user_tokens[session_id] = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or SCOPES),
        "email": user_email,
    }

    request.session["session_id"] = session_id
    request.session["user_email"] = user_email

    return RedirectResponse("/session")


async def session_page(request: Request):
    session_id = request.session.get("session_id")
    user_email = request.session.get("user_email", "")

    if not session_id or session_id not in _user_tokens:
        return RedirectResponse("/auth/login")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Your Session — Gmail MCP</title>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600&family=DM+Mono:wght@300;400&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Outfit',sans-serif;background:#fff;color:#0f0f10;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}}
.card{{max-width:540px;width:100%}}
h1{{font-size:24px;font-weight:600;letter-spacing:-0.02em;margin-bottom:6px}}
.sub{{font-size:14px;color:#6b6b7a;margin-bottom:28px}}
.label{{font-size:11px;font-family:'DM Mono',monospace;color:#aaaab8;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:6px}}
.token-box{{background:#f9f9fb;border:1px solid rgba(0,0,0,0.08);border-radius:10px;padding:14px 16px;font-family:'DM Mono',monospace;font-size:12px;color:#7c3aed;word-break:break-all;margin-bottom:16px;cursor:pointer;transition:background 0.15s}}
.token-box:hover{{background:#f0ebff}}
.copy-hint{{font-size:11px;color:#aaaab8;margin-bottom:24px}}
.step{{background:#f9f9fb;border:1px solid rgba(0,0,0,0.06);border-radius:10px;padding:14px 16px;margin-bottom:10px}}
.step-num{{display:inline-block;width:20px;height:20px;background:linear-gradient(135deg,#7c3aed,#ec4899);color:#fff;border-radius:50%;font-size:10px;font-weight:600;text-align:center;line-height:20px;margin-right:8px}}
.step-text{{font-size:13px;color:#0f0f10}}
.code{{font-family:'DM Mono',monospace;font-size:11px;background:#fff;border:1px solid rgba(0,0,0,0.08);border-radius:5px;padding:2px 6px;color:#7c3aed}}
.back{{display:inline-flex;align-items:center;gap:6px;color:#6b6b7a;font-size:13px;text-decoration:none;margin-top:20px}}
.back:hover{{color:#0f0f10}}
</style>
</head>
<body>
<div class="card">
  <h1>You're connected ✓</h1>
  <p class="sub">Signed in as <strong>{user_email}</strong></p>

  <div class="label">Your Session ID</div>
  <div class="token-box" onclick="navigator.clipboard.writeText('{session_id}');this.innerText='Copied!';" title="Click to copy">
    {session_id}
  </div>
  <p class="copy-hint">Click to copy · Keep this private · It gives access to your Gmail</p>

  <div class="label">How to use with the AI agent</div>
  <div class="step"><span class="step-num">1</span><span class="step-text">Visit <strong>{BASE_URL}</strong> and sign in with Google</span></div>
  <div class="step"><span class="step-num">2</span><span class="step-text">Copy your Session ID above</span></div>
  <div class="step"><span class="step-num">3</span><span class="step-text">In the chat, say: <span class="code">"My session ID is {session_id[:16]}... send an email to..."</span></span></div>
  <div class="step"><span class="step-num">4</span><span class="step-text">For developers: connect to <span class="code">{BASE_URL}/mcp</span> using any MCP client</span></div>

  <a href="/" class="back">← Back to home</a>
</div>
</body>
</html>"""
    return HTMLResponse(html)


async def auth_logout(request: Request):
    session_id = request.session.get("session_id")
    if session_id and session_id in _user_tokens:
        del _user_tokens[session_id]
    request.session.clear()
    return RedirectResponse("/")


async def api_status(request: Request):
    return JSONResponse({
        "status": "ok",
        "server": "Gmail MCP Server",
        "version": "1.0.0",
        "mcp_endpoint": f"{BASE_URL}/mcp",
        "tools": ["send_gmail", "read_inbox", "get_email", "search_gmail", "reply_to_email"],
        "active_sessions": len(_user_tokens),
    })


# ── App assembly ─────────────────────────────────────────────────────────────

mcp_app = mcp.http_app(path="/mcp")

routes = [
    Route("/", homepage),
    Route("/auth/login", auth_login),
    Route("/auth/callback", auth_callback),
    Route("/auth/logout", auth_logout),
    Route("/session", session_page),
    Route("/api/status", api_status),
    Mount("/", app=mcp_app),
]

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    async with mcp_app.lifespan(app):
        yield

app = Starlette(routes=routes, lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, max_age=86400 * 7)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8002))
    print(f"Gmail MCP Server running at http://localhost:{port}")
    print(f"MCP endpoint: http://localhost:{port}/mcp")
    uvicorn.run(app, host="0.0.0.0", port=port)
