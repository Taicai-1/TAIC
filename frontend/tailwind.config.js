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
      typography: (theme) => ({
        DEFAULT: {
          css: {
            maxWidth: 'none',
            color: theme('colors.gray.700'),
            fontSize: '0.9rem',
            lineHeight: '1.75',
            a: {
              color: theme('colors.primary.600'),
              textDecoration: 'underline',
              textUnderlineOffset: '2px',
              '&:hover': { color: theme('colors.primary.700') },
            },
            strong: { color: theme('colors.gray.900'), fontWeight: '600' },
            h2: {
              fontSize: '1.25rem',
              fontWeight: '700',
              color: theme('colors.gray.900'),
              marginTop: '1.25rem',
              marginBottom: '0.5rem',
              paddingBottom: '0.35rem',
              borderBottom: `1px solid ${theme('colors.gray.200')}`,
            },
            h3: {
              fontSize: '1.1rem',
              fontWeight: '600',
              color: theme('colors.gray.800'),
              marginTop: '1rem',
              marginBottom: '0.4rem',
            },
            h4: {
              fontSize: '0.95rem',
              fontWeight: '600',
              color: theme('colors.gray.700'),
            },
            blockquote: {
              borderLeftColor: theme('colors.primary.500'),
              backgroundColor: '#f5f3ff',
              padding: '0.75rem 1rem',
              borderRadius: '0 8px 8px 0',
              fontStyle: 'italic',
              color: theme('colors.gray.600'),
            },
            code: {
              backgroundColor: theme('colors.gray.100'),
              color: '#dc2626',
              padding: '2px 6px',
              borderRadius: '4px',
              fontWeight: '500',
              fontSize: '0.85em',
              fontFamily: "'Fira Code', 'Courier New', monospace",
            },
            'code::before': { content: 'none' },
            'code::after': { content: 'none' },
            hr: { borderColor: theme('colors.gray.200') },
            thead: { borderBottomColor: theme('colors.gray.200') },
            'thead th': {
              fontWeight: '600',
              color: theme('colors.gray.700'),
              paddingLeft: '0.75rem',
              paddingRight: '0.75rem',
            },
            'tbody td': {
              paddingLeft: '0.75rem',
              paddingRight: '0.75rem',
            },
          },
        },
      }),
    },
  },
  plugins: [
    require('@tailwindcss/typography'),
  ],
}
