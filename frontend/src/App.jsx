import React, { useState, useEffect, useRef } from "react";

// API Base URL
const API_BASE = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1"
  ? "http://127.0.0.1:8000"
  : "";

// Distinct database insights captured for Sales Info V2
const FEATURED_PRODUCTS = [
  { code: "BL", name: "Blown-in Cavity Wall Insulation", type: "Insulation" },
  { code: "BU", name: "Built-in Cavity Wall Insulation", type: "Insulation" },
  { code: "EW", name: "External Wall Insulation", type: "Insulation" },
  { code: "FI", name: "Floor Insulation", type: "Insulation" },
  { code: "II", name: "Internal Wall Insulation System", type: "Insulation" },
  { code: "RI", name: "Roof Insulation", type: "Insulation" },
  { code: "CL", name: "Cladding", type: "Cladding" },
  { code: "CS", name: "Cladding Slate", type: "Cladding" },
  { code: "LP", name: "PVC-U Cladding", type: "Cladding" },
  { code: "BQ", name: "PVC-U Barge, Facia or Soffit Board", type: "Cladding" },
  { code: "TM", name: "Building System", type: "MMC" },
  { code: "TR", name: "Building - Relocatable", type: "MMC" },
  { code: "TB", name: "Building Block", type: "MMC" }
];

const FEATURED_JOBS = [
  "Assessment",
  "Technical Reissue",
  "Audit",
  "Standard",
  "Replacement",
  "Amendment",
  "Contract Variation"
];

// Inline Markdown parsing for premium styling without packages
function parseInlineStyles(text) {
  const parts = [];
  const regex = /(\*\*.*?\*\*|`.*?`)/g;
  const matches = text.split(regex);
  return matches.map((part, idx) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={idx}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={idx} className="md-inline-code">{part.slice(1, -1)}</code>;
    }
    return part;
  });
}

function Markdown({ content }) {
  if (!content) return null;
  const lines = content.split("\n");
  const elements = [];
  let currentList = [];

  const flushList = (key) => {
    if (currentList.length > 0) {
      elements.push(
        <ul key={`list-${key}`} className="md-list">
          {currentList.map((item, idx) => (
            <li key={idx}>{parseInlineStyles(item)}</li>
          ))}
        </ul>
      );
      currentList = [];
    }
  };

  lines.forEach((line, idx) => {
    const trimmed = line.trim();
    if (trimmed.startsWith("### ")) {
      flushList(idx);
      elements.push(<h3 key={idx} className="md-h3">{parseInlineStyles(trimmed.slice(4))}</h3>);
    } else if (trimmed.startsWith("## ")) {
      flushList(idx);
      elements.push(<h2 key={idx} className="md-h2">{parseInlineStyles(trimmed.slice(3))}</h2>);
    } else if (trimmed.startsWith("# ")) {
      flushList(idx);
      elements.push(<h1 key={idx} className="md-h1">{parseInlineStyles(trimmed.slice(2))}</h1>);
    } else if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
      currentList.push(trimmed.slice(2));
    } else if (trimmed.match(/^\d+\.\s/)) {
      flushList(idx);
      const dotIndex = trimmed.indexOf(".");
      elements.push(
        <div key={idx} className="md-num-item">
          <span className="md-num">{trimmed.slice(0, dotIndex + 1)}</span>
          <span className="md-num-text">{parseInlineStyles(trimmed.slice(dotIndex + 1).trim())}</span>
        </div>
      );
    } else if (!trimmed) {
      flushList(idx);
    } else {
      flushList(idx);
      elements.push(<p key={idx} className="md-paragraph">{parseInlineStyles(line)}</p>);
    }
  });

  flushList(lines.length);
  return <div className="markdown-body">{elements}</div>;
}

// Interactive Data Table inside Assistant messages
function MessageTable({ columns, rows }) {
  if (!columns || !columns.length) return null;
  return (
    <div className="table-container">
      <div className="table-scroller">
        <table className="data-table">
          <thead>
            <tr>
              {columns.map((c, i) => (
                <th key={i}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, rIdx) => (
              <tr key={rIdx}>
                {row.map((cell, cIdx) => (
                  <td key={cIdx}>
                    {cell === null || cell === undefined
                      ? <span className="null-val">null</span>
                      : typeof cell === "number" && columns[cIdx]?.toLowerCase().includes("price")
                      ? `EDP ${Math.round(cell).toLocaleString()}`
                      : String(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="table-footer">
        {rows.length} row{rows.length !== 1 ? "s" : ""} fetched
      </div>
    </div>
  );
}

// Collapsible generated SQL details
function SqlBlock({ sql }) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  if (!sql) return null;

  const handleCopy = () => {
    navigator.clipboard.writeText(sql);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="sql-block">
      <div className="sql-header">
        <button className="sql-toggle" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
          <span className="sql-icon">⌗</span>
          {open ? "Hide PostgreSQL Query" : "View Generated SQL Query"}
          <span className="sql-chevron">{open ? "▲" : "▼"}</span>
        </button>
        {open && (
          <button className="copy-btn" onClick={handleCopy}>
            {copied ? "✓ Copied!" : "📋 Copy SQL"}
          </button>
        )}
      </div>
      {open && (
        <pre className="sql-code">
          <code>{sql}</code>
        </pre>
      )}
    </div>
  );
}

export default function SalesV2App() {
  const [messages, setMessages] = useState([
    {
      role: "assistant",
      content: "Welcome to the **Sales Info V2 Analytics Hub**!\n\nThis is a completely isolated, light-themed intelligence interface built specifically to query and analyze the single, consolidated **`sales_data`** table (representing `Sales Info V2 .xlsx` export sheet).\n\nEquipped with **Llama 3.3 70B** on OpenRouter, the system bypasses hardcoded templates to construct complex dynamic queries, performing advanced growth math, product associations, and deep business reasoning.\n\nTry asking any commercial question using the quick-chips below or type your own!",
    }
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState("connecting");
  const [rowCount, setRowCount] = useState(2136);
  const [cacheStatus, setCacheStatus] = useState("");
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  // Check API health status on mount
  useEffect(() => {
    fetch(`${API_BASE}/health`)
      .then((res) => res.json())
      .then((data) => {
        if (data.status === "ok") {
          setStatus("online");
        } else {
          setStatus("error");
        }
      })
      .catch(() => setStatus("offline"));
  }, []);

  const handleSend = async (customMessage) => {
    const textToSend = customMessage || input;
    const trimmed = textToSend.trim();
    if (!trimmed || loading) return;

    // Add user message
    setMessages((p) => [...p, { role: "user", content: trimmed }]);
    if (!customMessage) setInput("");
    setLoading(true);

    const history = messages
      .filter((m) => m.role === "user" || m.role === "assistant")
      .map((m) => ({ role: m.role, content: m.content }))
      .slice(-6);

    try {
      const res = await fetch(`${API_BASE}/text-to-sql/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: trimmed, history, backend: "llama" }),
      });

      if (!res.ok) {
        throw new Error((await res.text()) || res.statusText);
      }

      const data = await res.json();
      setMessages((p) => [
        ...p,
        {
          role: "assistant",
          content: data.message || "No explanation returned.",
          sql: data.sql,
          table: data.table,
          isError: !!data.error,
        }
      ]);
    } catch (err) {
      setMessages((p) => [
        ...p,
        {
          role: "assistant",
          content: `⚠️ Failed to fetch answer: ${err.message}`,
          isError: true,
        }
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleBustCache = async () => {
    setCacheStatus("clearing");
    try {
      const res = await fetch(`${API_BASE}/text-to-sql/bust-cache`, {
        method: "POST"
      });
      if (res.ok) {
        setCacheStatus("success");
        setTimeout(() => setCacheStatus(""), 3000);
      } else {
        setCacheStatus("error");
      }
    } catch {
      setCacheStatus("error");
    }
  };

  const sampleQueries = [
    "Sales difference between FY 2024/25 and FY 2025/26, and reason for it",
    "Which product types perform best in retrofit projects?",
    "Compare cladding-only customers vs insulation customers",
    "Show the top 5 customers and their total purchase amount"
  ];

  return (
    <div className="app-shell">
      {/* Dynamic Header */}
      <header className="header">
        <div className="header-inner">
          <div className="brand">
            <div className="brand-badge-light">v2</div>
            <div>
              <h1 className="brand-name">Sales Info V2 Client</h1>
              <p className="brand-sub">Light-themed Dynamic Querying & Analytical Reasoning Hub</p>
            </div>
          </div>
          <div className="header-stats">
            <span className={`status-pill ${status}`}>
              <span className="dot" /> {status.toUpperCase()}
            </span>
            <span className="stat-pill">💼 Sales Info V2</span>
            <span className="stat-pill">📊 {rowCount} Rows Ingested</span>
            <span className="stat-pill">🤖 Llama 3.3 70B</span>
          </div>
        </div>
      </header>

      <div className="main-layout">
        {/* Isolated Sidebar detailing Semantic Category Discovery */}
        <aside className="sidebar">
          <div className="sidebar-section">
            <h2 className="sidebar-title">🔍 Database Category Insights</h2>
            <p className="sidebar-subtitle">
              Dynamic category discoveries parsed directly from Excel and loaded into the database:
            </p>
            
            <h3 className="section-subtitle">Featured Product Types</h3>
            <div className="category-list">
              {FEATURED_PRODUCTS.map((p, idx) => (
                <div key={idx} className="category-pill">
                  <span className="cat-code">{p.code}</span>
                  <span className="cat-name">{p.name}</span>
                  <span className={`cat-tag ${p.type.toLowerCase()}`}>{p.type}</span>
                </div>
              ))}
            </div>

            <h3 className="section-subtitle">Featured Job Types</h3>
            <div className="category-list">
              {FEATURED_JOBS.map((j, idx) => (
                <div key={idx} className="job-pill">{j}</div>
              ))}
            </div>
          </div>

          <div className="sidebar-section border-top">
            <h2 className="sidebar-title">⚙️ Control Center</h2>
            <button className={`cache-btn ${cacheStatus}`} onClick={handleBustCache}>
              {cacheStatus === "clearing" ? "🔄 Invalidation Active..." : 
               cacheStatus === "success" ? "✓ Cache Cleared Successfully!" :
               cacheStatus === "error" ? "❌ Failed to clear cache" : "🧹 Clear Schema Cache"}
            </button>
            <p className="sidebar-desc">
              Forces backend schema reflection to run again, clearing all dynamic metadata caches.
            </p>
          </div>
        </aside>

        {/* Central Chat Panel */}
        <main className="chat-container">
          <div className="chat-scroller">
            <div className="messages-list">
              {messages.map((m, idx) => (
                <div key={idx} className={`message-row ${m.role}`}>
                  <div className={`avatar ${m.role}`}>
                    {m.role === "user" ? "👤" : "⚡"}
                  </div>
                  <div className={`message-bubble ${m.role} ${m.isError ? "error" : ""}`}>
                    <div className="bubble-meta">
                      {m.role === "user" ? "You" : "SalesChat V2 AI Agent"}
                    </div>
                    <div className="bubble-content">
                      <Markdown content={m.content} />
                    </div>
                    {m.sql && <SqlBlock sql={m.sql} />}
                    {m.table && <MessageTable columns={m.table.columns} rows={m.table.rows} />}
                  </div>
                </div>
              ))}
              {loading && (
                <div className="message-row assistant">
                  <div className="avatar assistant">⚡</div>
                  <div className="message-bubble assistant loading">
                    <span className="spinner" /> Analyzing database schema and writing SQL query...
                  </div>
                </div>
              )}
              <div ref={bottomRef} />
            </div>
          </div>

          {/* Quick chip queries */}
          <div className="chips-container">
            <span className="chips-label">Quick Queries:</span>
            <div className="chips-list">
              {sampleQueries.map((q, idx) => (
                <button key={idx} className="chip" onClick={() => handleSend(q)} disabled={loading}>
                  {q}
                </button>
              ))}
            </div>
          </div>

          {/* Input Composer */}
          <footer className="composer-footer">
            <form className="composer-form" onSubmit={(e) => { e.preventDefault(); handleSend(); }}>
              <textarea
                className="composer-textarea"
                rows={2}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleSend();
                  }
                }}
                placeholder="Ask any commercial question. E.g. 'Compare cladding-only customers vs insulation customers'..."
                disabled={loading}
              />
              <button className="send-btn" type="submit" disabled={loading || !input.trim()}>
                {loading ? "Thinking..." : "Send Query ↵"}
              </button>
            </form>
            <div className="composer-hint">
              Supported by Dynamic Category Discovery & Zero-Shot Semantic Lexicons on PostgreSQL.
            </div>
          </footer>
        </main>
      </div>
    </div>
  );
}
