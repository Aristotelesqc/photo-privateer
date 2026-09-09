/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        carbon: {
          950: '#0b0d10', // Deepest background
          900: '#12151a', // Primary card/panel surface
          850: '#171b22', // Hover and elevated surface
          800: '#1f242e', // Structural borders
          700: '#2b3240', // Highlight borders
          600: '#3e4758',
          500: '#5a667d',
          400: '#8592a6', // Secondary labels
          300: '#b0bccd', // High readability secondary
          200: '#d5dde8',
          100: '#f0f3f8', // Crisp foreground
        },
        accent: {
          500: '#3b82f6',
          600: '#2563eb',
          700: '#1d4ed8',
        },
      },
      fontFamily: {
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', 'Liberation Mono', 'monospace'],
        sans: ['-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'Helvetica Neue', 'Arial', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
