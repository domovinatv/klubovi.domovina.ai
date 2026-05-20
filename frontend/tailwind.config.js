/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        navy: {
          DEFAULT: "#002F6C",
          50: "#F0F4FA",
          100: "#D5E0EF",
          200: "#A6BDDB",
          300: "#7099C6",
          400: "#3D6FA8",
          500: "#1A4D89",
          600: "#002F6C",
          700: "#00255A",
          800: "#001A40",
          900: "#000F26",
        },
        flag: {
          red: "#FF0000",
          white: "#FFFFFF",
          navy: "#002F6C",
        },
        muted: "#5A6570",
        surface: "#F5F7F9",
        border: "#E1E5EA",
        // Tier palette — premium, brand-aligned (navy → red ramp via amber)
        tier: {
          1: "#FF0000", // HNL — flag red
          2: "#F97316", // 1. NL
          3: "#FBBF24", // 2. NL / 3. HNL
          4: "#FDE047", // 3. NL
          5: "#86EFAC", // 1. ŽNL
          6: "#5EEAD4", // 2. ŽNL
          7: "#7DD3FC", // 3. ŽNL
          8: "#94A3B8", // amateur unmapped
        },
      },
      fontFamily: {
        sans: [
          "Inter",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Helvetica",
          "Arial",
          "sans-serif",
        ],
      },
      borderRadius: {
        DEFAULT: "12px",
        sm: "8px",
        lg: "16px",
      },
      boxShadow: {
        card: "0 1px 3px rgba(0,47,108,0.08), 0 4px 12px rgba(0,47,108,0.05)",
        elevated:
          "0 4px 6px rgba(0,47,108,0.07), 0 12px 32px rgba(0,47,108,0.10)",
      },
      letterSpacing: {
        brand: "0.15em",
      },
    },
  },
  plugins: [],
};
