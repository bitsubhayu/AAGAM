/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      fontFamily: {
        sans: ["'Instrument Sans'", "system-ui", "sans-serif"],
        mono: ["'IBM Plex Mono'", "monospace"],
      },
      colors: {
        // ── Surfaces ──────────────────────────────────────────────────────
        canvas:      "#EDEAE4",   // warm cream page background (from reference image)
        background:  "#EDEAE4",   // alias for legacy bg-background references
        surface:     "#FFFFFF",   // card fill — pure white
        "surface-2": "#F0EDE7",   // inset / secondary tonal card
        "surface-raised": "#F0EDE7", // alias for legacy surface-raised references
        border:      "rgba(26,23,18,0.09)", // warm subtle line
        "border-subtle": "rgba(26,23,18,0.05)",
        pill:        "#1C1915",   // near-black warm pill (from reference logo badge)

        // ── Ink / Text ────────────────────────────────────────────────────
        text: {
          primary:   "#1A1712",   // warm near-black
          secondary: "#6B6560",   // label / caption
          muted:     "#A09890",   // placeholder / tertiary
        },

        // ── Brand accent (single coral-orange from reference) ─────────────
        accent:      "#E86440",   // coral — exact reference image match
        "accent-soft": "#F9D8CE", // light coral tint for badges / chips

        // ── Hazard / Severity ─────────────────────────────────────────────
        hazard: {
          advisory:  "#D9A441",   // warm amber
          watch:     "#E07B2E",   // deeper orange
          alert:     "#E86440",   // = --accent coral
          normal:    "#3D9970",   // warm teal-green
        },

        // ── Brand shortcuts (backward compat) ─────────────────────────────
        brand: {
          blue:   "#4C7BD9",
          teal:   "#3D9970",
          orange: "#D9A441",
          red:    "#E86440",
        },

        // ── Model colors ──────────────────────────────────────────────────
        model: {
          gfs:      "#4C7BD9",
          ifs:      "#8B6FD9",
          icon:     "#4FA37A",
          aifs:     "#C98A1E",
          blend:    "#4C7BD9",
          adjusted: "#E07B2E",
        },
      },
      borderRadius: {
        card: "20px",
        pill: "9999px",
      },
      boxShadow: {
        card: "0 1px 2px rgba(26,23,18,0.04), 0 12px 24px -8px rgba(26,23,18,0.10)",
        "card-hover": "0 2px 4px rgba(26,23,18,0.06), 0 16px 32px -8px rgba(26,23,18,0.16)",
        pill: "0 2px 8px rgba(26,23,18,0.18)",
      },
      transitionTimingFunction: {
        "out-smooth": "cubic-bezier(0.22, 0.61, 0.36, 1)",
      },
      animation: {
        breathing: "breathing 2.5s ease-in-out infinite",
        "cursor-blink": "cursor-blink 1s step-end infinite",
        "fade-in": "fadeIn 200ms ease-out",
        "slide-in-right": "slideInRight 220ms cubic-bezier(0.22,0.61,0.36,1)",
      },
      keyframes: {
        breathing: {
          "0%, 100%": { transform: "scale(1)", opacity: "1" },
          "50%": { transform: "scale(1.1)", opacity: "0.8" },
        },
        "cursor-blink": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0" },
        },
        fadeIn: {
          from: { opacity: "0", transform: "translateY(4px)" },
          to:   { opacity: "1", transform: "translateY(0)" },
        },
        slideInRight: {
          from: { transform: "translateX(100%)" },
          to:   { transform: "translateX(0)" },
        },
      },
    },
  },
  plugins: [],
}
