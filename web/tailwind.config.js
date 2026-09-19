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
        brand: {
          blue: "#388bfd",
          teal: "#2ea043",
          orange: "#d29922",
          red: "#f85149",
        }
      }
    },
  },
  plugins: [],
}
