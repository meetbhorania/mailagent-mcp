# MailAgent MCP

### AI-Powered Gmail Assistant with Public MCP Endpoint
**GDG London Assignment — Built by Meet Bhorania**

A production-grade AI email agent using Google ADK, Gemini 2.5 Flash, and Gmail API — with a public MCP endpoint for developers.

![Google ADK](https://img.shields.io/badge/Google%20ADK-Latest-blue)
![Gemini](https://img.shields.io/badge/Gemini-2.5%20Flash-orange)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green)
![License](https://img.shields.io/badge/License-MIT-purple)

---

## 🏗️ Architecture Overview

```
User (Browser)
     │
     ▼
┌─────────────────────────────────────────┐
│         React Frontend (Vite)           │
│     Sign in with Google · Chat UI       │
└─────────────────┬───────────────────────┘
                  │ HTTPS
                  ▼
┌─────────────────────────────────────────┐
│       FastAPI Backend (unified_app.py)  │
│  ┌─────────────────────────────────┐    │
│  │     Google OAuth 2.0 (PKCE)     │    │
│  │     Session Management          │    │
│  └──────────────┬──────────────────┘    │
│                 │                       │
│  ┌──────────────▼──────────────────┐    │
│  │   Google ADK LlmAgent           │    │
│  │   Model: Gemini 2.5 Flash       │    │
│  └──────────────┬──────────────────┘    │
│                 │ MCP Tools             │
└─────────────────┼───────────────────────┘
                  │
    ┌─────────────┼──────────────┐
    │             │              │
    ▼             ▼              ▼
send_email   read_inbox    get_email
    ▼             ▼              ▼
reply_to     search_       /mcp HTTP
email        emails        endpoint
```

---

## ✅ Features Implemented

| Feature | Status | Details |
|---|---|---|
| Google OAuth 2.0 | ✅ | PKCE flow — each user connects their own Gmail |
| Persistent Sessions | ✅ | 7-day cookie-based sessions, no re-login needed |
| Send Email | ✅ | `send_email` tool — instant Gmail delivery |
| Read Inbox | ✅ | `read_inbox` tool — fetches recent messages |
| Get Email | ✅ | `get_email` tool — full message content |
| Reply to Email | ✅ | `reply_to_email` tool — threaded replies |
| Search Gmail | ✅ | `search_emails` tool — full Gmail search syntax |
| Public MCP Endpoint | ✅ | `/mcp` — any MCP client can connect |
| Multi-user Support | ✅ | Each user has their own isolated Gmail session |
| Single URL Deployment | ✅ | Frontend + backend + MCP served from one URL |
| Dynamic Signature | ✅ | Emails signed with the authenticated user's name |

---

## 🚀 Live Demo

**[https://mailagent-mcp.onrender.com](https://mailagent-mcp.onrender.com)**

Sign in with your Google account to get started instantly.

---

## 🔌 MCP Endpoint (for developers)

Connect any MCP-compatible client to:

```
https://mailagent-mcp.onrender.com/mcp
```

### Available Tools

| Tool | Description |
|---|---|
| `send_email` | Send an email via the authenticated user's Gmail |
| `read_inbox` | Fetch recent inbox messages with metadata |
| `get_email` | Get full content of a specific message by ID |
| `reply_to_email` | Reply to an existing email thread |
| `search_emails` | Search Gmail using Gmail search syntax |

### Example MCP client config

```json
{
  "mcpServers": {
    "mailagent": {
      "url": "https://mailagent-mcp.onrender.com/mcp"
    }
  }
}
```

---

## 📁 Project Structure

```
mailagent-mcp/
├── unified_app.py          # Main app — OAuth, ADK agent, MCP, static files
├── mcp_server/
│   └── tools.py            # Gmail tool functions
├── frontend/
│   ├── src/
│   │   ├── App.jsx         # React UI — chat, compose, inbox
│   │   └── App.css         # Styles (Linear-inspired white + purple/pink)
│   └── dist/               # Built frontend served by FastAPI
├── requirements.txt
└── README.md
```

---

## 🚀 Quick Start

### 1. Clone the repo

```bash
git clone https://github.com/meetbhorania/mailagent-mcp.git
cd mailagent-mcp
```

### 2. Create virtual environment

```bash
python -m venv venv
source venv/bin/activate        # Mac/Linux
# venv\Scripts\activate         # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Set up Google Cloud

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a project and enable **Gmail API**
3. Create an **OAuth 2.0 Web Application** credential
4. Add `http://localhost:8000/auth/callback` as an authorised redirect URI
5. Download `credentials.json` to the project root

### 5. Set up environment variables

Create a `.env` file:

```env
GOOGLE_API_KEY=your_gemini_api_key_here
SESSION_SECRET=any_random_secret_string
BASE_URL=http://localhost:8000
```

Get your free Gemini API key at: [aistudio.google.com](https://aistudio.google.com/apikey)

### 6. Build frontend and run

```bash
cd frontend
npm install
VITE_API_URL=http://localhost:8000 npm run build
cd ..
python unified_app.py
```

Open [http://localhost:8000](http://localhost:8000) and sign in with Google.

---

## 💬 Example Queries to Try

| Query | What happens |
|---|---|
| `"Send a test email to john@example.com"` | Agent sends email immediately via Gmail |
| `"Read my last 5 emails and summarise them"` | Agent fetches inbox and returns clean summary |
| `"Reply to the latest email professionally"` | Agent reads thread and sends a reply |
| `"Search for emails from my boss this week"` | Agent runs Gmail search and returns results |
| `"Send a meeting invite to team@company.com"` | Agent composes and sends professional email |

---

## 🔧 Technical Details

### Authentication (OAuth 2.0 PKCE)
- Users sign in once — session cookie persists for 7 days
- Each user's Gmail token stored server-side, never exposed to the browser
- No session IDs ever shown or typed — fully transparent auth flow

### AI Agent
- Built on **Google ADK `LlmAgent`**
- Model: **Gemini 2.5 Flash** for fast, high-quality responses
- Tools bound per user session — each user's agent has access to their own Gmail only
- Agent instructions dynamically include the authenticated user's name for email signatures

### MCP Server
- Built with **FastMCP** over Streamable HTTP transport
- Public endpoint at `/mcp` — works with any MCP-compatible client
- Same Gmail tools exposed via both the web UI and the MCP protocol

---

## 🌐 Deployment (Render)

| Setting | Value |
|---|---|
| Runtime | Python 3 |
| Build Command | `pip install -r requirements.txt && cd frontend && npm install && VITE_API_URL=https://mailagent-mcp.onrender.com npm run build && cd ..` |
| Start Command | `uvicorn unified_app:app --host 0.0.0.0 --port 10000` |

### Environment Variables on Render

| Key | Description |
|---|---|
| `GOOGLE_API_KEY` | Gemini API key from Google AI Studio |
| `GOOGLE_CREDENTIALS_JSON` | Full contents of `credentials.json` |
| `BASE_URL` | `https://mailagent-mcp.onrender.com` |
| `SESSION_SECRET` | Random secret string for session signing |

---

## 📄 License

MIT License — see LICENSE

---

## 👤 Author

**Meet Bhorania**
AI Engineer & Builder · GDG London Speaker · Hackathon Winner

[GitHub](https://github.com/meetbhorania) · [LinkedIn](https://linkedin.com/in/meetbhorania)

---

*Built for GDG London ADK Assignment — demonstrating MCP server architecture, multi-user OAuth, and production AI agent deployment with Google ADK*
