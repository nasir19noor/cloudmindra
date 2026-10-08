/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{astro,html,js,jsx,md,mdx,svelte,ts,tsx,vue}'],
  theme: {
    extend: {
      colors: {
        ink: '#0d0d0d',
        surface: '#121212',
        'surface-2': '#141414',
        brand: {
          DEFAULT: '#ff6b35',
          100: '#ffb388',
          300: '#ff8a4d',
          500: '#ff4b01',
        },
      },
      fontFamily: {
        sans: ['Manrope', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        display: ['"IBM Plex Serif"', 'Georgia', 'serif'],
      },
      fontSize: {
        caption: ['13px', { lineHeight: '1.5' }],
        body: ['15px', { lineHeight: '1.6' }],
        title: ['20px', { lineHeight: '1.35' }],
        'display-sm': ['32px', { lineHeight: '1.25' }],
        display: ['42px', { lineHeight: '1.25' }],
        'display-xl': ['58px', { lineHeight: '1.1' }],
      },
    },
  },
  plugins: [],
};
