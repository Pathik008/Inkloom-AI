/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
      },
      colors: {
        gpt: {
          main: '#212121',
          sidebar: '#171717',
          card: '#2F2F2F',
          surface: '#2F2F2F',
          hover: '#424242',
          border: '#424242',
          accent: '#10A37F',
          accentHover: '#0D8F70',
          text: '#ECECEC',
          secondary: '#A1A1AA',
          muted: '#71717A',
        },
      },
    },
  },
  plugins: [],
}
