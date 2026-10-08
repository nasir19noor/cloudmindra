/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{astro,html,js,jsx,md,mdx,svelte,ts,tsx,vue}'],
  theme: {
    extend: {
      colors: {
        primary: '#0f172a',
        accent: '#3b82f6',
        'accent-dark': '#2563eb',
      },
    },
  },
  plugins: [],
};
