/** @type {import('next').NextConfig} */

// Build connect-src from NEXT_PUBLIC_API_URL instead of wildcard *.run.app
const apiUrl = process.env.NEXT_PUBLIC_API_URL || '';
const connectSrcExtra = apiUrl ? apiUrl.replace(/\/+$/, '') : '';

const nextConfig = {
  reactStrictMode: true,
  swcMinify: true,
  compress: true,

  // Optimize large icon libraries
  experimental: {
    optimizePackageImports: ['lucide-react'],
  },

  // Configuration i18n
  i18n: {
    locales: ['fr', 'en'],
    defaultLocale: 'fr',
  },

  // Security headers for all frontend pages
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          {
            key: 'X-Frame-Options',
            value: 'DENY',
          },
          {
            key: 'X-Content-Type-Options',
            value: 'nosniff',
          },
          {
            key: 'X-XSS-Protection',
            value: '1; mode=block',
          },
          {
            key: 'Referrer-Policy',
            value: 'strict-origin-when-cross-origin',
          },
          {
            key: 'Permissions-Policy',
            value: 'geolocation=(), camera=()',
          },
          {
            key: 'Strict-Transport-Security',
            value: 'max-age=31536000; includeSubDomains',
          },
          {
            key: 'Content-Security-Policy',
            // Next.js requires 'unsafe-inline' for styles (injected inline styles)
            // and 'unsafe-inline' for scripts (__NEXT_DATA__ hydration)
            // unsafe-eval is NOT needed and is excluded
            value: [
              "default-src 'self'",
              "script-src 'self' 'unsafe-inline' https://www.googletagmanager.com https://www.google-analytics.com https://accounts.google.com https://apis.google.com",
              "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
              "font-src 'self' https://fonts.gstatic.com",
              "img-src 'self' data: https: https://www.google-analytics.com https://www.googletagmanager.com",
              `connect-src 'self'${connectSrcExtra ? ' ' + connectSrcExtra : ''} https://api.openai.com https://www.google-analytics.com https://analytics.google.com https://www.googletagmanager.com https://accounts.google.com`,
              "frame-src 'self' https://accounts.google.com",
              "frame-ancestors 'none'",
            ].join('; '),
          },
        ],
      },
    ];
  },
}

module.exports = nextConfig
