/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './pages/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      fontFamily: {
        heading: ['Plus Jakarta Sans', 'system-ui', 'sans-serif'],
        body: ['Inter', 'system-ui', 'sans-serif'],
      },
      colors: {
        primary: {
          50:  '#eef2ff',
          100: '#e0e7ff',
          500: '#6366f1',
          600: '#4f46e5',
          700: '#4338ca',
          900: '#312e81',
        },
        navy: {
          DEFAULT: '#0f1c3f',
          dark:    '#080e20',
        },
      },
      boxShadow: {
        subtle:   '0 1px 2px 0 rgb(0 0 0 / 0.04)',
        card:     '0 1px 3px 0 rgb(0 0 0 / 0.04), 0 4px 12px 0 rgb(0 0 0 / 0.06)',
        elevated: '0 4px 20px 0 rgb(0 0 0 / 0.10)',
        floating: '0 8px 40px 0 rgb(0 0 0 / 0.18)',
      },
      borderRadius: {
        card:   '16px',
        button: '12px',
        input:  '10px',
        sm:     '8px',
      },
      animation: {
        'fade-up':  'fadeUp 0.35s ease-out',
        'fade-in':  'fadeIn 0.25s ease-out',
        'slide-in': 'slideIn 0.3s ease-out',
      },
      keyframes: {
        fadeUp:  { '0%': { opacity:'0', transform:'translateY(8px)' }, '100%': { opacity:'1', transform:'none' } },
        fadeIn:  { '0%': { opacity:'0' },                              '100%': { opacity:'1' } },
        slideIn: { '0%': { opacity:'0', transform:'translateX(-8px)' },'100%': { opacity:'1', transform:'none' } },
      },
    },
  },
  plugins: [],
}
