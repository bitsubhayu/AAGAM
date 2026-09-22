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
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import { useUIStore } from "@/store/uiStore";
import { useAuthStore } from "@/auth/authStore";
import { Button } from "@/components/ui/Button";
import { API_BASE, getAuthToken } from "@/api/client";
import { ArtifactViewerModal } from "./ArtifactViewerModal";
import { toast } from "sonner";

interface Message {
  id: string;
  sender: "user" | "assistant";
  text: string;
  timestamp: string;
  isStreaming?: boolean;
}

export const AssistantDrawer: React.FC = () => {
  const { isAssistantOpen, setAssistantOpen, assistantPrompt } = useUIStore();
  const { role } = useAuthStore();

  const [messages, setMessages] = useState<Message[]>([
    {
      id: "welcome-1",
      sender: "assistant",
      text: "Namaste! I am the **AAGAM Weather Decision Assistant**. Ask me about model agreements, regional heavy rainfall risks, extreme weather rules, or request raw multi-model forecast comparisons.",
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    },
  ]);

  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [mode, setMode] = useState<"explain" | "raw" | "both">("both");
  const [selectedArtifactId, setSelectedArtifactId] = useState<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

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

        if (reader) {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value, { stream: true });
            const lines = chunk.split("\n");

            for (const line of lines) {
              if (line.startsWith("data: ")) {
                try {
                  const data = JSON.parse(line.slice(6));
                  if (data.chunk) {
                    accumulatedText += data.chunk;
                    setMessages((prev) =>
                      prev.map((m) =>
                        m.id === assistantMsgId ? { ...m, text: accumulatedText } : m
                      )
                    );
                  } else if (data.text) {
                    accumulatedText = data.text;
                    setMessages((prev) =>
                      prev.map((m) =>
                        m.id === assistantMsgId ? { ...m, text: accumulatedText } : m
                      )
                    );
                  }
                } catch {
                  accumulatedText += line.slice(6);
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
                    text: `*AAGAM Assistant Service notice:* Automated AI reasoning and tool-loop orchestration will be unlocked in Phase 8. (API Response: ${err.message})`,
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
      toast.info("Assistant stream halted.");
    }
  };

  if (!isAssistantOpen) return null;

  return (
    <div className="fixed inset-y-0 right-0 z-50 w-full sm:w-[460px] bg-surface border-l border-border shadow-2xl flex flex-col font-sans animate-in slide-in-from-right duration-200">
      {/* Header */}
      <div className="px-4 py-3 border-b border-border bg-[#161b22] flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="p-1.5 bg-blue-500/10 border border-blue-500/30 rounded text-brand-blue">
            <Sparkles className="w-4 h-4 text-brand-orange" />
          </div>
          <div>
            <h3 className="text-xs font-bold text-text-primary flex items-center gap-1.5">
              <span>AAGAM Meteorological Assistant</span>
              <span className="text-[10px] px-1.5 py-0.2 rounded bg-[#21262d] text-text-muted font-mono">
                Phase 7 UI
              </span>
            </h3>
            <p className="text-[10px] text-text-muted">
              Role Context: <span className="capitalize text-text-secondary">{role}</span> ·
              Grounded in official data
            </p>
          </div>
        </div>

        <button
          onClick={() => setAssistantOpen(false)}
          className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-[#21262d] transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Mode Bar */}
      <div className="px-4 py-2 border-b border-border/60 bg-[#161b22]/50 flex items-center justify-between text-xs flex-wrap gap-2">
        <span className="text-[10px] text-text-muted uppercase tracking-wider font-semibold">
          Response Mode:
        </span>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1 bg-[#21262d] p-0.5 rounded border border-border">
            {(["explain", "raw", "both"] as const).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={`px-2 py-0.5 rounded text-[10px] font-medium capitalize transition-colors ${
                  mode === m
                    ? "bg-brand-blue text-white"
                    : "text-text-muted hover:text-text-secondary"
                }`}
              >
                {m}
              </button>
            ))}
          </div>

          <button
            onClick={() => {
              const id = window.prompt("Enter Stored Assistant Artifact ID (e.g. art-sample-01):");
              if (id?.trim()) setSelectedArtifactId(id.trim());
            }}
            className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium text-text-muted hover:text-text-primary border border-border bg-[#21262d] transition-colors"
            title="Inspect stored assistant data artifact (PRD §8.2 / §12)"
          >
            <FileCode className="w-3 h-3 text-brand-blue" />
            <span>Artifacts</span>
          </button>
        </div>
      </div>

      {/* Messages Feed */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-4 text-xs">
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
                className={`max-w-[85%] rounded-lg p-3 ${
                  isUser
                    ? "bg-brand-blue text-white"
                    : "bg-[#21262d] text-text-secondary border border-border"
                }`}
              >
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

                <div className="mt-1 flex items-center justify-between text-[10px] opacity-70">
                  <span>{m.timestamp}</span>
                  {!isUser && (
                    <div className="flex items-center gap-1 ml-4">
                      <button
                        onClick={() => toast.success("Feedback recorded")}
                        className="hover:text-text-primary"
                        title="Helpful"
                      >
                        <ThumbsUp className="w-3 h-3" />
                      </button>
                      <button
                        onClick={() => toast.info("Feedback recorded")}
                        className="hover:text-text-primary"
                        title="Not helpful"
                      >
                        <ThumbsDown className="w-3 h-3" />
                      </button>
                    </div>
                  )}
                </div>
              </div>

              {isUser && (
                <div className="w-6 h-6 rounded bg-[#21262d] border border-border flex items-center justify-center text-text-muted shrink-0 mt-0.5">
                  <User className="w-3.5 h-3.5" />
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Suggested Starters */}
      {messages.length <= 2 && (
        <div className="px-4 py-2 border-t border-border/40 bg-[#161b22]/30 space-y-1.5">
          <span className="text-[10px] text-text-muted uppercase font-semibold block">
            Suggested Briefings:
          </span>
          <div className="space-y-1">
            {samplePrompts.slice(0, 2).map((p, idx) => (
              <button
                key={idx}
                onClick={() => handleSend(p)}
                className="w-full text-left p-1.5 rounded bg-[#21262d] hover:bg-[#30363d] text-[11px] text-text-secondary transition-colors truncate block border border-border/50"
              >
                {p}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Input Form */}
      <div className="p-3 border-t border-border bg-[#161b22]">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSend(input);
          }}
          className="flex items-center gap-2"
        >
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask AAGAM about weather forecasts or models..."
            disabled={isStreaming}
            className="flex-1 px-3 py-2 bg-[#21262d] border border-border rounded-md text-xs text-text-primary placeholder:text-text-muted focus:ring-2 focus:ring-brand-blue/50 outline-none"
          />

          {isStreaming ? (
            <Button
              type="button"
              variant="destructive"
              size="sm"
              onClick={handleStop}
              className="h-8 px-2.5"
              title="Halt streaming"
            >
              <Square className="w-3.5 h-3.5" />
            </Button>
          ) : (
            <Button
              type="submit"
              variant="primary"
              size="sm"
              disabled={!input.trim()}
              className="h-8 px-3"
            >
              <Send className="w-3.5 h-3.5" />
            </Button>
          )}
        </form>

        <p className="text-[10px] text-text-muted mt-2 text-center">
          Ground truth from IMD 0.25° grid · Decision support only
        </p>
      </div>

      <ArtifactViewerModal
        isOpen={!!selectedArtifactId}
        onClose={() => setSelectedArtifactId(null)}
        artifactId={selectedArtifactId}
      />
    </div>
  );
};
