import React, { useState, useEffect } from "react";
import { useAuthStore } from "@/auth/authStore";
import { extractFirstName, getGreeting } from "@/utils/greeting";

interface TypewriterGreetingProps {
  className?: string;
}

const isReducedMotion = (): boolean =>
  typeof window !== "undefined"
    ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
    : false;

export const TypewriterGreeting: React.FC<TypewriterGreetingProps> = ({
  className = "",
}) => {
  const { profile, user } = useAuthStore();

  const rawName =
    profile?.display_name ||
    user?.user_metadata?.display_name ||
    user?.user_metadata?.full_name ||
    null;

  const firstName = extractFirstName(rawName);
  const fullText = getGreeting(firstName);

  const [displayText, setDisplayText] = useState(() =>
    isReducedMotion() ? fullText : ""
  );
  const [showCursor, setShowCursor] = useState(() => !isReducedMotion());
  const [done, setDone] = useState(() => isReducedMotion());

  useEffect(() => {
    if (isReducedMotion()) {
      setDisplayText(fullText);
      setShowCursor(false);
      setDone(true);
      return;
    }

    setDisplayText("");
    setShowCursor(true);
    setDone(false);

    let i = 0;
    const delay = setTimeout(() => {
      const interval = setInterval(() => {
        i++;
        setDisplayText(fullText.slice(0, i));
        if (i >= fullText.length) {
          clearInterval(interval);
          setDone(true);
          setTimeout(() => setShowCursor(false), 2000);
        }
      }, 35);
      return () => clearInterval(interval);
    }, 150);

    return () => clearTimeout(delay);
  }, [fullText]);

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
