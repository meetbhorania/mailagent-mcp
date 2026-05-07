import { useState, useEffect, useRef } from "react";
import "./App.css";

const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

export default function App() {
  const [user, setUser] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [tab, setTab] = useState("chat");
  const [messages, setMessages] = useState([
    { role: "agent", text: "Good day. I'm your executive email assistant. I can send emails, read your inbox, and compose professional replies instantly." }
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [inbox, setInbox] = useState([]);
  const [inboxLoading, setInboxLoading] = useState(false);
  const [selectedEmail, setSelectedEmail] = useState(null);
  const [compose, setCompose] = useState({ to: "", subject: "", body: "" });
  const [sendStatus, setSendStatus] = useState("");
  const bottomRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    fetch(`${API}/api/me`, { credentials: "include" })
      .then(r => r.json())
      .then(data => {
        if (data.authenticated) setUser({ email: data.email });
        setAuthLoading(false);
      })
      .catch(() => setAuthLoading(false));
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function sendChat(msgOverride) {
    const msg = (msgOverride || input).trim();
    if (!msg || loading) return;
    setInput("");
    setMessages(p => [...p, { role: "user", text: msg }]);
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ message: msg }),
      });
      if (res.status === 401) {
        setMessages(p => [...p, { role: "agent", text: "Session expired. Please sign in again.", error: true }]);
        setUser(null);
        return;
      }
      const data = await res.json();
      setMessages(p => [...p, { role: "agent", text: data.response, tools: data.tool_calls }]);
    } catch {
      setMessages(p => [...p, { role: "agent", text: "Unable to reach the server.", error: true }]);
    } finally {
      setLoading(false);
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  }

  async function loadInbox() {
    setInboxLoading(true);
    setSelectedEmail(null);
    try {
      const res = await fetch(`${API}/api/inbox?limit=20`, { credentials: "include" });
      const data = await res.json();
      setInbox(data.emails || []);
    } catch { setInbox([]); }
    finally { setInboxLoading(false); }
  }

  async function openEmail(id) {
    const res = await fetch(`${API}/api/email/${id}`, { credentials: "include" });
    const data = await res.json();
    setSelectedEmail(data);
  }

  async function sendCompose() {
    if (!compose.to || !compose.subject || !compose.body) { setSendStatus("error:Please fill in all fields."); return; }
    setSendStatus("sending");
    try {
      const res = await fetch(`${API}/api/send`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(compose),
      });
      const data = await res.json();
      if (data.success) { setSendStatus("success:Email sent successfully."); setCompose({ to: "", subject: "", body: "" }); setTimeout(() => setSendStatus(""), 3000); }
      else setSendStatus(`error:${data.error}`);
    } catch { setSendStatus("error:Failed to send."); }
  }

  function replyViaChat(email) {
    setTab("chat");
    setInput(`Reply to the email from ${email.from} with subject "${email.subject}". Draft a concise professional reply and send it immediately.`);
  }

  function fmtDate(d) {
    try {
      const dt = new Date(d), now = new Date(), diff = now - dt;
      if (diff < 86400000) return dt.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
      if (diff < 604800000) return dt.toLocaleDateString("en-GB", { weekday: "short" });
      return dt.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
    } catch { return ""; }
  }

  function initials(from) {
    const n = from.split("<")[0].trim().split(" ");
    return n.length >= 2 ? (n[0][0] + n[1][0]).toUpperCase() : (n[0][0] || "?").toUpperCase();
  }

  const COLORS = ["#7C3AED", "#EC4899", "#0EA5E9", "#F97316", "#22C55E", "#6366F1", "#EF4444", "#F59E0B"];
  function vc(s) { let h = 0; for (let i = 0; i < s.length; i++) h = s.charCodeAt(i) + ((h << 5) - h); return COLORS[Math.abs(h) % COLORS.length]; }

  if (authLoading) return <div className="auth-screen"><div className="spinner" /></div>;

  if (!user) return (
    <div className="auth-screen">
      <div className="auth-card">
        <div className="auth-logo">✉</div>
        <h1 className="auth-title">MailAgent</h1>
        <p className="auth-sub">Your AI-powered Gmail assistant.<br />Sign in to get started.</p>
        <a href={`/auth/login`} className="auth-btn">
          <svg viewBox="0 0 18 18" width="16" height="16">
            <path d="M16.51 8H8.98v3h4.3c-.18 1-.74 1.48-1.6 2.04v2.01h2.6a7.8 7.8 0 002.38-5.88c0-.57-.05-.66-.15-1.18z" fill="#4285F4" />
            <path d="M8.98 17c2.16 0 3.97-.72 5.3-1.94l-2.6-2a4.8 4.8 0 01-7.18-2.54H1.83v2.07A8 8 0 008.98 17z" fill="#34A853" />
            <path d="M4.5 10.52a4.8 4.8 0 010-3.04V5.41H1.83a8 8 0 000 7.18l2.67-2.07z" fill="#FBBC05" />
            <path d="M8.98 4.18c1.17 0 2.23.4 3.06 1.2l2.3-2.3A8 8 0 001.83 5.4L4.5 7.49a4.77 4.77 0 014.48-3.31z" fill="#EA4335" />
          </svg>
          Sign in with Google
        </a>
        <p className="auth-note">Your Gmail data is never stored permanently.</p>
      </div>
    </div>
  );

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="logo">
          <div className="logo-mark">✉</div>
          <span className="logo-name">MailAgent</span>
        </div>
        <nav className="nav">
          <button className={`nb ${tab === "chat" ? "nb-active" : ""}`} onClick={() => setTab("chat")}>
            <span className="nb-icon">💬</span><span>Assistant</span>
            {loading && <span className="nb-live" />}
          </button>
          <button className={`nb ${tab === "compose" ? "nb-active" : ""}`} onClick={() => setTab("compose")}>
            <span className="nb-icon">✏️</span><span>Compose</span>
          </button>
          <button className={`nb ${tab === "inbox" ? "nb-active" : ""}`} onClick={() => { setTab("inbox"); loadInbox(); }}>
            <span className="nb-icon">📥</span><span>Inbox</span>
            {inbox.length > 0 && <span className="nb-count">{inbox.length}</span>}
          </button>
        </nav>
        <div className="sidebar-foot">
          <div className="user-row">
            <div className="u-av">{user.email[0].toUpperCase()}</div>
            <div className="u-info">
              <span className="u-name">{user.email.split("@")[0]}</span>
              <span className="u-handle">{user.email}</span>
            </div>
            <span className="u-dot" />
          </div>
          <a href={`/auth/logout`} className="sign-out-btn">Sign out</a>
        </div>
      </aside>

      <main className="main">
        {tab === "chat" && (
          <div className="page">
            <div className="topbar">
              <div>
                <h1 className="ptitle">Executive Email Assistant</h1>
                <p className="psub">Read · Send · Reply </p>
              </div>
              <div className="model-tag">gemini-2.5-flash</div>
            </div>
            <div className="msgs">
              {messages.map((m, i) => (
                <div key={i} className={`msg ${m.role === "user" ? "msg-user" : "msg-agent"}`}>
                  {m.role === "agent" && <div className="av av-agent">EA</div>}
                  <div className={`bubble ${m.role === "user" ? "bubble-user" : m.error ? "bubble-error" : "bubble-agent"}`}>
                    <p>{m.text}</p>
                    {m.tools?.length > 0 && (
                      <div className="tool-row">
                        {m.tools.map((t, j) => <span key={j} className="tool-pill">⚡ {t.replace("🔧 ", "")}</span>)}
                      </div>
                    )}
                  </div>
                  {m.role === "user" && <div className="av av-user">{user.email[0].toUpperCase()}</div>}
                </div>
              ))}
              {loading && (
                <div className="msg msg-agent">
                  <div className="av av-agent">EA</div>
                  <div className="bubble bubble-agent typing-bubble"><span /><span /><span /></div>
                </div>
              )}
              <div ref={bottomRef} />
            </div>
            <div className="chat-foot">
              <div className="quick-row">
                {["Summarise my inbox", "Send a test email to myself", "Latest unread emails"].map(s => (
                  <button key={s} className="qchip" onClick={() => sendChat(s)}>{s}</button>
                ))}
              </div>
              <div className="input-bar">
                <input ref={inputRef} className="chat-input" type="text" value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={e => e.key === "Enter" && sendChat()}
                  placeholder='e.g. "Send an email to john@example.com about our meeting"'
                  autoFocus />
                <button className="send-btn" onClick={() => sendChat()} disabled={loading || !input.trim()}>➤</button>
              </div>
            </div>
          </div>
        )}

        {tab === "compose" && (
          <div className="page">
            <div className="topbar">
              <div><h1 className="ptitle">New Message</h1><p className="psub">Compose a professional email</p></div>
            </div>
            <div className="compose-wrap">
              <div className="compose-card">
                <div className="compose-row">
                  <label className="compose-label">To</label>
                  <input className="compose-input" type="email" placeholder="recipient@example.com"
                    value={compose.to} onChange={e => setCompose({ ...compose, to: e.target.value })} />
                </div>
                <div className="compose-sep" />
                <div className="compose-row">
                  <label className="compose-label">Subject</label>
                  <input className="compose-input" type="text" placeholder="Email subject"
                    value={compose.subject} onChange={e => setCompose({ ...compose, subject: e.target.value })} />
                </div>
                <div className="compose-sep" />
                <div className="compose-row compose-body">
                  <label className="compose-label">Body</label>
                  <textarea className="compose-textarea" placeholder="Write your message here…"
                    value={compose.body} onChange={e => setCompose({ ...compose, body: e.target.value })} />
                </div>
                {sendStatus && (
                  <div className={`compose-notice ${sendStatus.startsWith("error") ? "notice-error" : sendStatus === "sending" ? "notice-pending" : "notice-success"}`}>
                    {sendStatus === "sending" ? "Sending…" : sendStatus.split(":")[1]}
                  </div>
                )}
                <div className="compose-actions">
                  <button className="btn-primary" onClick={sendCompose} disabled={sendStatus === "sending"}>➤ Send Email</button>
                  <button className="btn-ghost" onClick={() => setCompose({ to: "", subject: "", body: "" })}>Discard</button>
                </div>
              </div>
            </div>
          </div>
        )}

        {tab === "inbox" && (
          <div className="page">
            <div className="topbar">
              <div>
                <h1 className="ptitle">Inbox</h1>
                <p className="psub">{inbox.length > 0 ? `${inbox.length} messages` : "Your recent emails"}</p>
              </div>
              <button className="btn-outline" onClick={loadInbox}>↻ Refresh</button>
            </div>
            {selectedEmail ? (
              <div className="detail-wrap">
                <button className="back-btn" onClick={() => setSelectedEmail(null)}>← Back</button>
                <div className="detail-card">
                  <h2 className="detail-subject">{selectedEmail.subject}</h2>
                  <p className="detail-from">From: {selectedEmail.from}</p>
                  <p className="detail-date">{selectedEmail.date}</p>
                </div>
                <div className="detail-body">{selectedEmail.body}</div>
                <button className="btn-primary" onClick={() => replyViaChat(selectedEmail)}>↩ AI Reply</button>
              </div>
            ) : (
              <div className="email-list">
                {inboxLoading && <div className="list-loading"><div className="spinner" /><span>Loading inbox…</span></div>}
                {!inboxLoading && inbox.length === 0 && <div className="list-empty"><div className="empty-icon">✉</div><p>No emails found</p></div>}
                {!inboxLoading && inbox.map(e => (
                  <div key={e.id} className="email-row" onClick={() => openEmail(e.id)}>
                    <div className="e-avatar" style={{ background: vc(e.from) }}>{initials(e.from)}</div>
                    <div className="e-content">
                      <div className="e-top">
                        <span className="e-sender">{e.from.split("<")[0].trim()}</span>
                        <span className="e-time">{fmtDate(e.date)}</span>
                      </div>
                      <div className="e-subject">{e.subject}</div>
                      <div className="e-snippet">{e.snippet}</div>
                    </div>
                    <span className="e-arrow">›</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}