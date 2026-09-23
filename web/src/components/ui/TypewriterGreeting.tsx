import React, { useState, useEffect, useRef } from "react";

interface TypewriterGreetingProps {
  className?: string;
}

function getGreeting(name: string | null): string {
  const hour = new Date().getHours();
  const period =
    hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  if (name) {
    return `${period}, ${name} 👋`;
  }
  return `${period} — here's what's active right now`;
}

function getUserName(): string | null {
  try {
    const email = localStorage.getItem("aagam_user_email");
    if (!email) return null;
    return email.split("@")[0];
  } catch {
    return null;
  }
}

const isReducedMotion = (): boolean =>
  typeof window !== "undefined"
    ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
    : false;

export const TypewriterGreeting: React.FC<TypewriterGreetingProps> = ({
  className = "",
}) => {
  const name = getUserName();
  const fullText = getGreeting(name);

  // Track display text — once per mount (never re-triggers on re-renders)
  const [displayText, setDisplayText] = useState(() =>
    isReducedMotion() ? fullText : ""
  );
  const [showCursor, setShowCursor] = useState(() => !isReducedMotion());
  const [done, setDone] = useState(() => isReducedMotion());
  const hasStarted = useRef(false);

  useEffect(() => {
    if (isReducedMotion() || hasStarted.current) return;
    hasStarted.current = true;

    let i = 0;
    // Small initial delay so the page renders before typing starts
    const delay = setTimeout(() => {
      const interval = setInterval(() => {
        i++;
        setDisplayText(fullText.slice(0, i));
        if (i >= fullText.length) {
          clearInterval(interval);
          setDone(true);
          // Keep blinking cursor for a moment, then hide it
          setTimeout(() => setShowCursor(false), 2000);
        }
      }, 45);
      return () => clearInterval(interval);
    }, 300);

    return () => clearTimeout(delay);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className={`${className}`} aria-label={fullText} aria-live="polite">
      <span className="text-2xl md:text-3xl font-bold text-text-primary tracking-tight leading-tight">
        {displayText}
      </span>
      {showCursor && (
        <span
          className={`inline-block w-0.5 h-7 bg-accent align-middle ml-0.5 relative top-[-1px] ${
            done ? "animate-cursor-blink" : ""
          }`}
          aria-hidden="true"
        />
      )}
    </div>
  );
};
