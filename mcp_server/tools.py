"""
Email Agent MCP Server
Gmail tools: send_email, read_inbox, get_email, reply_email
"""

import os
import base64
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

TOKEN_PATH = os.path.join(os.path.dirname(__file__), "..", "token.json")
CREDS_PATH = os.path.join(os.path.dirname(__file__), "..", "credentials.json")
SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]


def _get_service():
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
    if not creds or not creds.valid:
        raise Exception("Invalid credentials. Please run OAuth flow again.")
    return build("gmail", "v1", credentials=creds)


def send_email(to: str, subject: str, body: str) -> dict:
    """Send an email to a recipient."""
    try:
        service = _get_service()
        message = MIMEMultipart()
        message["to"] = to
        message["subject"] = subject
        message.attach(MIMEText(body, "plain"))
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return {
            "success": True,
            "message_id": sent["id"],
            "to": to,
            "subject": subject,
            "sent_at": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def read_inbox(max_results: int = 10) -> dict:
    """Read recent emails from inbox."""
    try:
        service = _get_service()
        results = service.users().messages().list(
            userId="me", labelIds=["INBOX"], maxResults=max_results
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


def get_email(message_id: str) -> dict:
    """Get full content of a specific email by ID."""
    try:
        service = _get_service()
        m = service.users().messages().get(
            userId="me", id=message_id, format="full"
        ).execute()
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


def reply_email(message_id: str, body: str) -> dict:
    """Reply to an existing email."""
    try:
        service = _get_service()
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
        return {
            "success": True,
            "message_id": sent["id"],
            "replied_to": to,
            "subject": subject,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


MCP_TOOLS = {
    "send_email": send_email,
    "read_inbox": read_inbox,
    "get_email": get_email,
    "reply_email": reply_email,
}
