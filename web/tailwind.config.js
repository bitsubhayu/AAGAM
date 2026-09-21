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
        sans: ["'IBM Plex Sans'", "sans-serif"],
        mono: ["'IBM Plex Mono'", "monospace"],
      },
      colors: {
        background: "#0d1117",
        surface: "#161b22",
        "surface-raised": "#21262d",
        border: "#30363d",
        "border-subtle": "#21262d",
        text: {
          primary: "#f0f6fc",
          secondary: "#c9d1d9",
          muted: "#8b949e",
        },
        brand: {
          blue: "#388bfd",
          teal: "#2ea043",
          orange: "#d29922",
          red: "#f85149",
        },
        hazard: {
          advisory: "#d29922",
          watch: "#db6d28",
          alert: "#f85149",
          normal: "#2ea043",
        },
        model: {
          gfs: "#58a6ff",
          ifs: "#3fb950",
          icon: "#f0883e",
          aifs: "#a371f7",
          blend: "#388bfd",
          adjusted: "#db6d28",
        }
      }
    },
  },
  plugins: [],
}
