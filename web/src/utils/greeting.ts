/**
 * Utility functions for greeting generation and first name extraction from authoritative profile.
 */

export function extractFirstName(rawName?: string | null): string | null {
  if (!rawName) return null;
  const trimmed = rawName.trim();
  if (!trimmed) return null;

  // Never return an email address or email local-part
  if (trimmed.includes("@")) return null;

  const honorifics = new Set([
    "dr", "dr.", "prof", "prof.", "mr", "mr.", "mrs", "mrs.", "ms", "ms.", "shri", "shri.", "smt", "smt."
  ]);

  const tokens = trimmed.split(/\s+/).filter(Boolean);
  if (tokens.length === 0) return null;

  const firstLower = tokens[0].toLowerCase();
  if (honorifics.has(firstLower)) {
    if (tokens.length === 1) return null;
    const remaining = tokens.slice(1);
    // Find the first token that is not just an initial like "S." or "S"
    const substantiveIdx = remaining.findIndex((t) => !/^[A-Za-z]\.?$/.test(t));
    if (substantiveIdx !== -1) {
      return `${tokens[0]} ${remaining[substantiveIdx]}`;
    }
    return `${tokens[0]} ${remaining[0]}`;
  }

  // Normal first name (e.g. "Subhayu Bit" -> "Subhayu")
  return tokens[0];
}

export function getGreeting(name: string | null): string {
  const hour = new Date().getHours();
  const period =
    hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  if (name) {
    return `${period}, ${name} 👋`;
  }
  return `${period} — here's what's active right now`;
}
