import React, { useState } from "react";
import { Sparkles } from "lucide-react";

interface AnimatedAssistantButtonProps {
  isOpen: boolean;
  onClick: () => void;
  className?: string;
}

const isReducedMotion = (): boolean =>
  typeof window !== "undefined"
    ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
    : false;

export const AnimatedAssistantButton: React.FC<AnimatedAssistantButtonProps> = ({
  isOpen,
  onClick,
  className = "",
}) => {
  const [reducedMotion] = useState(isReducedMotion);
  const shouldAnimate = !isOpen && !reducedMotion;

  return (
    <button
      onClick={onClick}
      aria-label={isOpen ? "Close AI Assistant" : "Open AI Assistant"}
      aria-expanded={isOpen}
      title="AAGAM AI Assistant"
      className={`relative flex items-center gap-2 px-3.5 py-1.5 rounded-full transition-all duration-150 focus:outline-none focus:ring-2 focus:ring-accent/40 select-none ${
        isOpen
          ? "bg-accent text-white shadow-pill"
          : "bg-[#F0EDE7] hover:bg-white text-text-primary border border-[rgba(26,23,18,0.10)]"
      } ${className}`}
    >
      {/* Subtle glow ring when idle-open — not when drawer is open */}
      {!isOpen && (
        <span
          className="absolute inset-0 rounded-full"
          style={{
            background:
              "radial-gradient(circle, rgba(232,100,64,0.08) 0%, transparent 70%)",
            animation: shouldAnimate ? "breathing 2.5s ease-in-out infinite" : "none",
          }}
          aria-hidden="true"
        />
      )}

      <span
        style={{
          display: "inline-flex",
          animation: shouldAnimate ? "breathing 2.5s ease-in-out infinite" : "none",
          transformOrigin: "center",
        }}
        aria-hidden="true"
      >
        <Sparkles
          className={`w-3.5 h-3.5 transition-colors ${
            isOpen ? "text-white" : "text-accent"
          }`}
        />
      </span>
      <span className="hidden sm:inline text-xs font-medium">Assistant</span>
    </button>
  );
};
