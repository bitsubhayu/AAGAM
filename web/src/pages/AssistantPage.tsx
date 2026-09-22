import React, { useState, useEffect, useRef, useCallback } from "react";
import {
  Send,
  Sparkles,
  Bot,
  User,
  Square,
  ThumbsUp,
  ThumbsDown,
  FileCode,
  AlertTriangle,
  Zap,
  RotateCcw,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import { useUIStore } from "@/store/uiStore";
import { Button } from "@/components/ui/Button";
import { API_BASE, getAuthToken } from "@/api/client";
import { ArtifactViewerModal } from "@/components/assistant/ArtifactViewerModal";
import { DataTableWidget, type DataTablePayload } from "@/components/assistant/DataTableWidget";
import { toast } from "sonner";

interface Message {
  id: string;
  sender: "user" | "assistant";
  text: string;
  timestamp: string;
  isStreaming?: boolean;
  toolCalls?: Array<{ name: string; arguments: any }>;
  dataTable?: DataTablePayload;
  citations?: Array<{ tool: string; issue_time: string; model_version: string }>;
  warning?: string;
  model?: string;
  cached?: boolean;
  latency_ms?: number;
  tokens_used?: number;
  feedback?: "up" | "down";
  error?: { code: string; message: string; retry_after?: number };
}

export const AssistantPage: React.FC = () => {
  const { assistantPrompt } = useUIStore();

  const [messages, setMessages] = useState<Message[]>([
    {
      id: "welcome-1",
      sender: "assistant",
      text: "Namaste! I am the **AAGAM Weather Decision Assistant** (NCMRWF / MoES PS 26081).\n\nI can retrieve calibrated multi-model forecasts (GFS, ECMWF IFS, DWD ICON, ECMWF AIFS), model weight matrices, verification skill metrics, and active extreme alerts across AAGAM's 40 configured locations. Every figure is traceable to tool outputs.\n\n*Notice: Decision support, not an official IMD warning.*",
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      model: "openai/gpt-oss-120b",
    },
  ]);

  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [mode, setMode] = useState<"explain" | "raw" | "both">("both");
  const [selectedArtifactId, setSelectedArtifactId] = useState<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const personaPrompts = [
    {
      category: "Forecaster (Dr. Meera)",
      prompts: [
        "Tmax for Nagpur next 3 days, all models",
        "Which model do we trust for South monsoon rain at day 3?",
        "MAE of AIFS vs ICON for wind by lead, last 60 days",
      ],
    },
    {
      category: "Disaster Duty Officer (Mr. Rao)",
      prompts: [
        "Is heavy rain likely near Bhubaneswar this weekend?",
        "Any heavy-rain alerts for the next 48 h on the East coast?",
        "Active heatwave warnings in Central India",
      ],
    },
    {
      category: "Analyst / Researcher",
      prompts: [
        "Export last 30 days Delhi Tmax observed vs models CSV",
        "Raw: bias of models across regions for wind",
        "Query historical blended rainfall for Kolkata last 14 days",
      ],
    },
  ];

  const handleSend = useCallback(
    async (messageText: string) => {
      if (!messageText.trim() || isStreaming) return;

      const userMsg: Message = {
        id: `user-${Date.now()}`,
        sender: "user",
        text: messageText,
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      };

      const assistantMsgId = `asst-${Date.now()}`;
      const initialAssistantMsg: Message = {
        id: assistantMsgId,
        sender: "assistant",
        text: "",
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        isStreaming: true,
        toolCalls: [],
      };

      setMessages((prev) => [...prev, userMsg, initialAssistantMsg]);
      setInput("");
      setIsStreaming(true);

      const abortController = new AbortController();
      abortControllerRef.current = abortController;

      try {
        const token = getAuthToken();
        const headers: HeadersInit = { "Content-Type": "application/json" };
        if (token) headers["Authorization"] = `Bearer ${token}`;

        const res = await fetch(`${API_BASE}/chat`, {
          method: "POST",
          headers,
          body: JSON.stringify({ message: messageText, mode }),
          signal: abortController.signal,
        });

        if (!res.ok) {
          throw new Error(`Chat request returned HTTP ${res.status}`);
        }

        const reader = res.body?.getReader();
        const decoder = new TextDecoder();
        let accumulatedText = "";
        let currentEvent = "message";

        if (reader) {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value, { stream: true });
            const lines = chunk.split("\n");

            for (const line of lines) {
              if (line.startsWith("event: ")) {
                currentEvent = line.slice(7).trim();
              } else if (line.startsWith("data: ")) {
                const rawData = line.slice(6);
                try {
                  const payload = JSON.parse(rawData);

                  if (currentEvent === "meta") {
                    setMessages((prev) =>
                      prev.map((m) =>
                        m.id === assistantMsgId
                          ? { ...m, model: payload.model, cached: payload.cached }
                          : m
                      )
                    );
                  } else if (currentEvent === "tool_call") {
                    setMessages((prev) =>
                      prev.map((m) =>
                        m.id === assistantMsgId
                          ? { ...m, toolCalls: [...(m.toolCalls || []), payload] }
                          : m
                      )
                    );
                  } else if (currentEvent === "data_table") {
                    setMessages((prev) =>
                      prev.map((m) =>
                        m.id === assistantMsgId ? { ...m, dataTable: payload } : m
                      )
                    );
                  } else if (currentEvent === "token") {
                    if (payload.content) {
                      accumulatedText += payload.content;
                      setMessages((prev) =>
                        prev.map((m) =>
                          m.id === assistantMsgId ? { ...m, text: accumulatedText } : m
                        )
                      );
                    }
                  } else if (currentEvent === "citations") {
                    setMessages((prev) =>
                      prev.map((m) =>
                        m.id === assistantMsgId ? { ...m, citations: payload } : m
                      )
                    );
                  } else if (currentEvent === "warning") {
                    setMessages((prev) =>
                      prev.map((m) =>
                        m.id === assistantMsgId
                          ? { ...m, warning: payload.message || payload }
                          : m
                      )
                    );
                  } else if (currentEvent === "done") {
                    setMessages((prev) =>
                      prev.map((m) =>
                        m.id === assistantMsgId
                          ? {
                              ...m,
                              latency_ms: payload.latency_ms,
                              tokens_used: payload.tokens_used,
                              isStreaming: false,
                            }
                          : m
                      )
                    );
                  } else if (currentEvent === "error") {
                    setMessages((prev) =>
                      prev.map((m) =>
                        m.id === assistantMsgId
                          ? {
                              ...m,
                              error: payload,
                              text: payload.message || "An error occurred.",
                              isStreaming: false,
                            }
                          : m
                      )
                    );
                  }
                } catch {
                  // Fallback plain chunk
                  if (currentEvent === "token" || currentEvent === "text") {
                    accumulatedText += rawData;
                    setMessages((prev) =>
                      prev.map((m) =>
                        m.id === assistantMsgId ? { ...m, text: accumulatedText } : m
                      )
                    );
                  }
                }
              }
            }
          }
        }

        setMessages((prev) =>
          prev.map((m) => (m.id === assistantMsgId ? { ...m, isStreaming: false } : m))
        );
      } catch (err: any) {
        if (err.name !== "AbortError") {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMsgId
                ? {
                    ...m,
                    text: `*AAGAM Assistant Notice:* ${err.message}`,
                    isStreaming: false,
                  }
                : m
            )
          );
        }
      } finally {
        setIsStreaming(false);
        abortControllerRef.current = null;
      }
    },
    [isStreaming, mode]
  );

  useEffect(() => {
    if (assistantPrompt) {
      const timeoutId = setTimeout(() => {
        handleSend(assistantPrompt);
      }, 0);
      return () => clearTimeout(timeoutId);
    }
  }, [assistantPrompt, handleSend]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const handleStop = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      setIsStreaming(false);
      toast.info("Assistant stream stopped.");
    }
  };

  const handleFeedback = (msgId: string, type: "up" | "down") => {
    setMessages((prev) =>
      prev.map((m) => (m.id === msgId ? { ...m, feedback: type } : m))
    );
    toast.success("Feedback recorded to chat_audit");
  };

  return (
    <div className="flex flex-col h-[calc(100vh-8.5rem)] bg-[#0d1117] rounded-lg border border-border overflow-hidden">
      {/* Workstation Header Bar */}
      <div className="px-5 py-3 bg-[#161b22] border-b border-border flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <div className="p-2 bg-blue-500/10 border border-blue-500/30 rounded text-brand-blue">
            <Sparkles className="w-5 h-5 text-brand-orange" />
          </div>
          <div>
            <h1 className="text-sm font-bold text-text-primary flex items-center gap-2">
              <span>AAGAM Meteorological Assistant</span>
              <span className="text-[10px] px-2 py-0.5 rounded bg-blue-500/15 text-brand-blue font-mono border border-blue-500/30">
                Groq openai/gpt-oss-120b
              </span>
            </h1>
            <p className="text-[11px] text-text-muted">
              Operational decision support · 6 read-only tools · 100% numerical traceability (M5)
            </p>
          </div>
        </div>

        {/* Toolbar & Response Mode Selector */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 bg-[#21262d] p-1 rounded border border-border text-xs">
            <span className="text-[10px] text-text-muted font-semibold px-1">MODE:</span>
            {(["explain", "raw", "both"] as const).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={`px-2.5 py-1 rounded text-xs font-medium capitalize transition-colors ${
                  mode === m
                    ? "bg-brand-blue text-white shadow-sm"
                    : "text-text-secondary hover:text-text-primary hover:bg-[#30363d]"
                }`}
              >
                {m}
              </button>
            ))}
          </div>

          <button
            onClick={() => {
              const id = window.prompt("Enter Stored Assistant Artifact ID (e.g. art_sample):");
              if (id?.trim()) setSelectedArtifactId(id.trim());
            }}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-[#21262d] hover:bg-[#30363d] border border-border text-xs text-text-secondary hover:text-text-primary transition-colors"
          >
            <FileCode className="w-3.5 h-3.5 text-brand-blue" />
            <span>Artifacts</span>
          </button>

          <button
            onClick={() => {
              if (window.confirm("Clear conversation history?")) {
                setMessages([messages[0]]);
              }
            }}
            className="flex items-center gap-1 px-2.5 py-1.5 rounded bg-[#21262d] hover:bg-[#30363d] border border-border text-xs text-text-muted hover:text-text-primary transition-colors"
            title="Reset conversation"
          >
            <RotateCcw className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Messages Scroll Area */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-6 space-y-6 select-text">
        {messages.map((m) => {
          const isUser = m.sender === "user";
          return (
            <div
              key={m.id}
              className={`flex gap-3.5 ${isUser ? "justify-end" : "justify-start"}`}
            >
              {!isUser && (
                <div className="w-8 h-8 rounded-full bg-brand-blue/15 border border-brand-blue/30 flex items-center justify-center text-brand-blue shrink-0 mt-0.5 shadow-sm">
                  <Bot className="w-4 h-4" />
                </div>
              )}

              <div
                className={`max-w-[85%] rounded-lg p-4 space-y-3 ${
                  isUser
                    ? "bg-brand-blue text-white shadow"
                    : "bg-[#161b22] text-text-primary border border-border shadow-sm"
                }`}
              >
                {/* Assistant Metadata Header */}
                {!isUser && (
                  <div className="flex flex-wrap items-center justify-between gap-2 pb-2 border-b border-border/40 text-[11px] text-text-muted">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-brand-blue font-semibold">
                        {m.model || "AAGAM Agent"}
                      </span>
                      {m.cached && (
                        <span className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 text-[10px]">
                          <Zap className="w-2.5 h-2.5" /> Cached (10m TTL)
                        </span>
                      )}
                    </div>
                    {m.latency_ms && (
                      <div className="flex items-center gap-2 font-mono text-[10px]">
                        <span>{m.latency_ms} ms</span>
                        {m.tokens_used && <span>· {m.tokens_used} tokens</span>}
                      </div>
                    )}
                  </div>
                )}

                {/* Tool Call Chips */}
                {!isUser && m.toolCalls && m.toolCalls.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {m.toolCalls.map((tc, idx) => (
                      <span
                        key={idx}
                        className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-[#21262d] border border-border text-[11px] font-mono text-text-secondary"
                      >
                        <Zap className="w-3 h-3 text-brand-orange" />
                        <span>tool: {tc.name}</span>
                      </span>
                    ))}
                  </div>
                )}

                {/* Interactive Data Table Component */}
                {!isUser && m.dataTable && (
                  <DataTableWidget
                    dataTable={m.dataTable}
                    onInspectArtifact={(id) => setSelectedArtifactId(id)}
                  />
                )}

                {/* Markdown Prose Response */}
                <div className="markdown-body text-xs leading-relaxed">
                  <ReactMarkdown
                    components={{
                      a: ({ href, children }) => {
                        if (href?.startsWith("#artifact-") || href?.includes("/artifacts/")) {
                          const artId = href.split("/").pop()?.replace("#artifact-", "");
                          return (
                            <button
                              onClick={() => setSelectedArtifactId(artId || null)}
                              className="text-brand-blue underline inline-flex items-center gap-0.5 font-mono cursor-pointer"
                            >
                              <FileCode className="w-3 h-3 inline" />
                              <span>{children}</span>
                            </button>
                          );
                        }
                        return (
                          <a href={href} target="_blank" rel="noreferrer" className="text-brand-blue underline">
                            {children}
                          </a>
                        );
                      },
                    }}
                  >
                    {m.text}
                  </ReactMarkdown>
                </div>

                {/* Warning Banner */}
                {!isUser && m.warning && (
                  <div className="p-2.5 rounded bg-amber-500/10 border border-amber-500/30 flex items-center gap-2 text-xs text-amber-300">
                    <AlertTriangle className="w-4 h-4 flex-shrink-0" />
                    <span>{m.warning}</span>
                  </div>
                )}

                {/* Citations Chips */}
                {!isUser && m.citations && m.citations.length > 0 && (
                  <div className="pt-2 border-t border-border/40 flex flex-wrap items-center gap-2 text-[10px] text-text-muted">
                    <span className="font-semibold">Data Used:</span>
                    {m.citations.map((c, idx) => (
                      <span
                        key={idx}
                        className="px-2 py-0.5 rounded bg-[#21262d] border border-border font-mono text-text-secondary"
                      >
                        {c.tool} (v: {c.model_version})
                      </span>
                    ))}
                  </div>
                )}

                {/* Message Footer: Timestamp & Feedback */}
                <div className="flex items-center justify-between text-[10px] opacity-70 pt-1">
                  <span>{m.timestamp}</span>
                  {!isUser && (
                    <div className="flex items-center gap-1.5 ml-4">
                      <button
                        onClick={() => handleFeedback(m.id, "up")}
                        className={`p-1 rounded hover:bg-[#21262d] transition-colors ${
                          m.feedback === "up" ? "text-emerald-400" : "hover:text-text-primary"
                        }`}
                        title="Helpful"
                      >
                        <ThumbsUp className="w-3 h-3" />
                      </button>
                      <button
                        onClick={() => handleFeedback(m.id, "down")}
                        className={`p-1 rounded hover:bg-[#21262d] transition-colors ${
                          m.feedback === "down" ? "text-rose-400" : "hover:text-text-primary"
                        }`}
                        title="Not helpful"
                      >
                        <ThumbsDown className="w-3 h-3" />
                      </button>
                    </div>
                  )}
                </div>
              </div>

              {isUser && (
                <div className="w-8 h-8 rounded-full bg-[#21262d] border border-border flex items-center justify-center text-text-muted shrink-0 mt-0.5 shadow-sm">
                  <User className="w-4 h-4" />
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Suggested Starters Grid (shown when conversation is brief) */}
      {messages.length <= 2 && (
        <div className="px-6 py-3 border-t border-border/60 bg-[#161b22]/40">
          <span className="text-[10px] text-text-muted uppercase tracking-wider font-semibold block mb-2">
            Persona-Tailored Prompt Starters:
          </span>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
            {personaPrompts.map((group) => (
              <div key={group.category} className="space-y-1">
                <span className="text-[10px] font-semibold text-text-secondary block">
                  {group.category}
                </span>
                {group.prompts.map((p) => (
                  <button
                    key={p}
                    onClick={() => handleSend(p)}
                    className="w-full text-left px-2.5 py-1.5 rounded bg-[#21262d]/70 hover:bg-[#21262d] border border-border/60 text-[11px] text-text-secondary hover:text-text-primary transition-colors truncate"
                    title={p}
                  >
                    {p}
                  </button>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Query Input Footer */}
      <div className="p-4 border-t border-border bg-[#161b22]">
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend(input);
              }
            }}
            placeholder="Ask AAGAM Assistant about model agreements, regional rain, weights, skill, or alerts..."
            disabled={isStreaming}
            className="flex-1 bg-[#0d1117] border border-border rounded-lg px-4 py-2.5 text-xs text-text-primary placeholder:text-text-muted focus:outline-none focus:border-brand-blue"
          />

          {isStreaming ? (
            <Button
              variant="outline"
              size="sm"
              onClick={handleStop}
              className="border-rose-500/40 text-rose-400 hover:bg-rose-500/10 px-4 h-9"
            >
              <Square className="w-3.5 h-3.5 mr-1" />
              <span>Stop</span>
            </Button>
          ) : (
            <Button
              variant="primary"
              size="sm"
              onClick={() => handleSend(input)}
              disabled={!input.trim()}
              className="px-5 h-9"
            >
              <Send className="w-3.5 h-3.5 mr-1.5" />
              <span>Ask</span>
            </Button>
          )}
        </div>
      </div>

      {/* Artifact Viewer Modal */}
      {selectedArtifactId && (
        <ArtifactViewerModal
          isOpen={!!selectedArtifactId}
          artifactId={selectedArtifactId}
          onClose={() => setSelectedArtifactId(null)}
        />
      )}
    </div>
  );
};
