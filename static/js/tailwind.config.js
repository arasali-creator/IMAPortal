// tailwind.config.js

module.exports = {
  // Support dark mode classes
  darkMode: "class",
  // Your project's files to scan for Tailwind classes
  content: ["./your_project/**/*.{html,py,js}"],
  theme: {
    extend: {
      // Colors that match with UNFOLD["COLORS"] settings
      colors: {
        base: {
          50: "rgb(var(--color-base-50) / <alpha-value>)",
          100: "rgb(var(--color-base-100) / <alpha-value>)",
          200: "rgb(var(--color-base-200) / <alpha-value>)",
          300: "rgb(var(--color-base-300) / <alpha-value>)",
          400: "rgb(var(--color-base-400) / <alpha-value>)",
          500: "rgb(var(--color-base-500) / <alpha-value>)",
          600: "rgb(var(--color-base-600) / <alpha-value>)",
          700: "rgb(var(--color-base-700) / <alpha-value>)",
          800: "rgb(var(--color-base-800) / <alpha-value>)",
          900: "rgb(var(--color-base-900) / <alpha-value>)",
          950: "rgb(var(--color-base-950) / <alpha-value>)",
        },
        primary: {
          50: "rgb(var(--color-primary-50) / <alpha-value>)",
          100: "rgb(var(--color-primary-100) / <alpha-value>)",
          200: "rgb(var(--color-primary-200) / <alpha-value>)",
          300: "rgb(var(--color-primary-300) / <alpha-value>)",
          400: "rgb(var(--color-primary-400) / <alpha-value>)",
          500: "rgb(var(--color-primary-500) / <alpha-value>)",
          600: "rgb(var(--color-primary-600) / <alpha-value>)",
          700: "rgb(var(--color-primary-700) / <alpha-value>)",
          800: "rgb(var(--color-primary-800) / <alpha-value>)",
          900: "rgb(var(--color-primary-900) / <alpha-value>)",
          950: "rgb(var(--color-primary-950) / <alpha-value>)",
        },
        font: {
          "subtle-light": "rgb(var(--color-font-subtle-light) / <alpha-value>)",
          "subtle-dark": "rgb(var(--color-font-subtle-dark) / <alpha-value>)",
          "default-light": "rgb(var(--color-font-default-light) / <alpha-value>)",
          "default-dark": "rgb(var(--color-font-default-dark) / <alpha-value>)",
          "important-light": "rgb(var(--color-font-important-light) / <alpha-value>)",
          "important-dark": "rgb(var(--color-font-important-dark) / <alpha-value>)",
        }
      }
    }
  }
};