import React, { useState, useEffect, useRef, useCallback } from "react";
import {
  X,
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
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import { useUIStore } from "@/store/uiStore";
import { useAuthStore } from "@/auth/authStore";
import { Button } from "@/components/ui/Button";
import { API_BASE, getAuthToken } from "@/api/client";
import { ArtifactViewerModal } from "./ArtifactViewerModal";
import { DataTableWidget, type DataTablePayload } from "./DataTableWidget";
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

export const AssistantDrawer: React.FC = () => {
  const { isAssistantOpen, setAssistantOpen, assistantPrompt, clearAssistantPrompt } = useUIStore();
  const { role } = useAuthStore();

  const [messages, setMessages] = useState<Message[]>([
    {
      id: "welcome-1",
      sender: "assistant",
      text: "Namaste! I am the **AAGAM Weather Decision Assistant**. Ask me about model agreements, regional heavy rainfall risks, extreme weather rules, or request raw multi-model forecast comparisons.\n\n*Notice: Decision support, not an official IMD warning.*",
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
  const lastHandledPromptRef = useRef<string | null>(null);

  // Suggested prompts tailored to persona
  const samplePrompts = [
    "What is the blended rainfall forecast for Bhubaneswar over the next 3 days?",
    "Compare ECMWF IFS vs GFS skill across coastal stations this week.",
    "Are there any severe heatwave thresholds triggered in the Central region?",
    "Explain the dominant model weights for Day+3 forecast in East & North-East.",
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
          let errorDetail = `Chat request returned HTTP ${res.status}`;
          try {
            const errJson = await res.json();
            if (errJson?.detail?.message) errorDetail = errJson.detail.message;
            else if (errJson?.message) errorDetail = errJson.message;
          } catch {
            // fallback to status code
          }
          throw new Error(errorDetail);
        }

        const reader = res.body?.getReader();
        const decoder = new TextDecoder();
        let accumulatedText = "";
        let buffer = "";

        if (reader) {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const blocks = buffer.split("\n\n");
            buffer = blocks.pop() || "";

            for (const block of blocks) {
              if (!block.trim()) continue;
              const lines = block.split("\n");
              let currentEvent = "message";
              const dataLines: string[] = [];

              for (const line of lines) {
                if (line.startsWith("event: ")) {
                  currentEvent = line.slice(7).trim();
                } else if (line.startsWith("data: ")) {
                  dataLines.push(line.slice(6));
                } else if (line === "data:") {
                  dataLines.push("");
                }
              }

              const rawData = dataLines.join("\n");
              if (!rawData && currentEvent !== "end") continue;

              try {
                const payload = rawData ? JSON.parse(rawData) : {};

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
                      m.id === assistantMsgId ? { ...m, citations: Array.isArray(payload) ? payload : [payload] } : m
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
                            model: payload.model || m.model,
                            isStreaming: false,
                          }
                        : m
                    )
                  );
                } else if (currentEvent === "error") {
                  const errorMsg = payload.message || "An error occurred during response generation.";
                  setMessages((prev) =>
                    prev.map((m) =>
                      m.id === assistantMsgId
                        ? {
                            ...m,
                            error: payload,
                            text: (accumulatedText ? accumulatedText + "\n\n" : "") + `*AAGAM Error:* ${errorMsg}`,
                            isStreaming: false,
                          }
                        : m
                    )
                  );
                }
              } catch {
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

  const handleSendRef = useRef(handleSend);
  useEffect(() => {
    handleSendRef.current = handleSend;
  }, [handleSend]);

  // Escape key and body scroll lock
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setAssistantOpen(false);
    };
    if (isAssistantOpen) {
      document.body.style.overflow = "hidden";
      window.addEventListener("keydown", handleKeyDown);
    }
    return () => {
      document.body.style.overflow = "unset";
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [isAssistantOpen, setAssistantOpen]);

  useEffect(() => {
    if (assistantPrompt && assistantPrompt !== lastHandledPromptRef.current) {
      const promptToSend = assistantPrompt;
      lastHandledPromptRef.current = promptToSend;
      clearAssistantPrompt();
      handleSendRef.current(promptToSend);
    }
  }, [assistantPrompt, clearAssistantPrompt]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const handleStop = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      setIsStreaming(false);
      toast.info("Assistant stream halted.");
    }
  };

  const handleFeedback = (msgId: string, type: "up" | "down") => {
    setMessages((prev) =>
      prev.map((m) => (m.id === msgId ? { ...m, feedback: type } : m))
    );
    toast.success("Feedback recorded");
  };

  if (!isAssistantOpen) return null;

  return (
    <>
      <div
        className="fixed inset-0 z-[2000] bg-[rgba(26,23,18,0.45)] backdrop-blur-sm"
        onClick={() => setAssistantOpen(false)}
        aria-hidden="true"
      />
      <div className="fixed inset-y-0 right-0 z-[2000] w-full sm:w-[500px] bg-surface border-l border-[rgba(26,23,18,0.10)] shadow-2xl flex flex-col font-sans animate-in slide-in-from-right duration-200">
        {/* Header */}
        <div className="px-4 py-3 border-b border-[rgba(26,23,18,0.09)] bg-surface flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 bg-accent-soft rounded-full">
              <Sparkles className="w-4 h-4 text-accent" />
            </div>
          <div>
            <h3 className="text-xs font-bold text-text-primary flex items-center gap-1.5">
              <span>AAGAM Meteorological Assistant</span>
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-[#EBF2FD] text-brand-blue font-mono border border-brand-blue/25">
                Groq 120B
              </span>
            </h3>
            <p className="text-[10px] text-text-muted">
              Role: <span className="capitalize text-text-secondary">{role}</span> ·
              Decision support, not official warning
            </p>
          </div>
        </div>

        <button
          onClick={() => setAssistantOpen(false)}
          className="p-1.5 rounded-full text-text-muted hover:text-text-primary hover:bg-[#F0EDE7] transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Mode Bar */}
      <div className="px-4 py-2 border-b border-[rgba(26,23,18,0.07)] bg-[#F5F2EC] flex items-center justify-between text-xs flex-wrap gap-2">
        <span className="text-[10px] text-text-muted uppercase tracking-wider font-semibold">
          Response Mode:
        </span>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-0.5 bg-[#F0EDE7] p-0.5 rounded-full border border-[rgba(26,23,18,0.10)]">
            {(["explain", "raw", "both"] as const).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={`px-2.5 py-0.5 rounded-full text-[10px] font-semibold capitalize transition-all duration-150 ${
                  mode === m
                    ? "bg-accent text-white shadow-pill"
                    : "text-text-muted hover:text-text-primary"
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
            className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium text-text-muted hover:text-text-primary border border-[rgba(26,23,18,0.10)] bg-[#F0EDE7] transition-colors"
            title="Inspect stored assistant data artifact"
          >
            <FileCode className="w-3 h-3 text-brand-blue" />
            <span>Artifacts</span>
          </button>
        </div>
      </div>

      {/* Messages Feed */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-4 text-xs select-text">
        {messages.map((m) => {
          const isUser = m.sender === "user";
          return (
            <div
              key={m.id}
              className={`flex gap-2.5 ${isUser ? "justify-end" : "justify-start"}`}
            >
              {!isUser && (
                <div className="w-6 h-6 rounded bg-brand-blue/15 border border-brand-blue/30 flex items-center justify-center text-brand-blue shrink-0 mt-0.5">
                  <Bot className="w-3.5 h-3.5" />
                </div>
              )}

              <div
                className={`max-w-[90%] rounded-lg p-3 space-y-2.5 ${
                  isUser
                    ? "bg-brand-blue text-white"
                    : "bg-[#F0EDE7] text-text-secondary border border-[rgba(26,23,18,0.10)]"
                }`}
              >
                {/* Meta Header */}
                {!isUser && (
                  <div className="flex items-center justify-between gap-2 pb-1.5 border-b border-border/40 text-[10px] text-text-muted">
                    <div className="flex items-center gap-1.5">
                      <span className="font-mono text-brand-blue font-semibold">
                        {m.model || "openai/gpt-oss-120b"}
                      </span>
                      {m.cached && (
                        <span className="px-1.5 py-0.2 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 flex items-center gap-0.5">
                          <Zap className="w-2.5 h-2.5" /> Cached
                        </span>
                      )}
                    </div>
                    {m.latency_ms && (
                      <span className="font-mono text-[9px] opacity-70">
                        {m.latency_ms}ms · {m.tokens_used || 50}t
                      </span>
                    )}
                  </div>
                )}

                {/* Tool calls badges */}
                {!isUser && m.toolCalls && m.toolCalls.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {m.toolCalls.map((tc, idx) => (
                      <span
                        key={idx}
                        className="px-1.5 py-0.5 rounded bg-surface border border-[rgba(26,23,18,0.10)] text-[10px] font-mono text-text-secondary flex items-center gap-1"
                      >
                        <Zap className="w-2.5 h-2.5 text-brand-orange" />
                        <span>tool: {tc.name}</span>
                      </span>
                    ))}
                  </div>
                )}

                {/* Data Table Widget */}
                {!isUser && m.dataTable && (
                  <DataTableWidget
                    dataTable={m.dataTable}
                    onInspectArtifact={(id) => setSelectedArtifactId(id)}
                  />
                )}

                {/* Markdown Text Body */}
                <div className="markdown-body text-xs leading-relaxed text-text-primary">
                  <ReactMarkdown
                    components={{
                      a: ({ href, children }) => {
                        if (href?.startsWith("#artifact-") || href?.includes("/artifacts/")) {
                          const artId = href.split("/").pop()?.replace("#artifact-", "");
                          return (
                            <button
                              onClick={() => setSelectedArtifactId(artId || null)}
                              className="text-brand-blue underline inline-flex items-center gap-0.5 font-mono cursor-pointer"
                              title="Inspect stored assistant artifact (PRD §12)"
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

                {/* Warning Alert */}
                {!isUser && m.warning && (
                  <div className="p-2 rounded bg-amber-500/10 border border-amber-500/30 flex items-center gap-1.5 text-[11px] text-amber-300">
                    <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
                    <span>{m.warning}</span>
                  </div>
                )}

                {/* Citations */}
                {!isUser && m.citations && m.citations.length > 0 && (
                  <div className="pt-1.5 border-t border-border/40 flex flex-wrap items-center gap-1.5 text-[9px] text-text-muted">
                    <span className="font-semibold">Data used:</span>
                    {m.citations.map((c, idx) => (
                      <span
                        key={idx}
                        className="px-1.5 py-0.5 rounded bg-surface border border-[rgba(26,23,18,0.10)] font-mono text-text-secondary"
                      >
                        {c.tool} (v: {c.model_version})
                      </span>
                    ))}
                  </div>
                )}

                {/* Footer: Timestamp & Feedback */}
                <div className="mt-1 flex items-center justify-between text-[10px] opacity-70">
                  <span>{m.timestamp}</span>
                  {!isUser && (
                    <div className="flex items-center gap-1 ml-4">
                      <button
                        onClick={() => handleFeedback(m.id, "up")}
                        className={`hover:text-text-primary transition-colors ${
                          m.feedback === "up" ? "text-emerald-400" : ""
                        }`}
                        title="Helpful"
                      >
                        <ThumbsUp className="w-3 h-3" />
                      </button>
                      <button
                        onClick={() => handleFeedback(m.id, "down")}
                        className={`hover:text-text-primary transition-colors ${
                          m.feedback === "down" ? "text-rose-400" : ""
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
                <div className="w-6 h-6 rounded bg-[#F0EDE7] border border-[rgba(26,23,18,0.10)] flex items-center justify-center text-text-muted shrink-0 mt-0.5">
                  <User className="w-3.5 h-3.5" />
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Suggested Starters */}
      {messages.length <= 2 && (
        <div className="px-4 py-2 border-t border-border/40 bg-surface/30 space-y-1.5">
          <span className="text-[10px] text-text-muted uppercase font-semibold block">
            Suggested Briefings:
          </span>
          <div className="space-y-1">
            {samplePrompts.map((p, idx) => (
              <button
                key={idx}
                onClick={() => handleSend(p)}
                className="w-full text-left px-2.5 py-1.5 rounded bg-[#F0EDE7]/60 hover:bg-[#F0EDE7] border border-border/40 text-[11px] text-text-secondary hover:text-text-primary transition-colors truncate block"
              >
                {p}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Input Footer */}
      <div className="p-3 border-t border-[rgba(26,23,18,0.10)] bg-surface">
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
            placeholder="Ask AAGAM Assistant about forecasts, weights, skill, alerts..."
            disabled={isStreaming}
            className="flex-1 bg-canvas border border-[rgba(26,23,18,0.10)] rounded px-3 py-2 text-xs text-text-primary placeholder:text-text-muted focus:outline-none focus:border-brand-blue"
          />

          {isStreaming ? (
            <Button
              variant="outline"
              size="sm"
              onClick={handleStop}
              className="border-rose-500/40 text-rose-400 hover:bg-rose-500/10 px-3"
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
              className="px-3"
            >
              <Send className="w-3.5 h-3.5" />
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
  </>
  );
};
