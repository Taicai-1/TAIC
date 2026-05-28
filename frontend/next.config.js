/** @type {import('next').NextConfig} */

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

  // Proxy API requests through the frontend domain for first-party cookies
  async rewrites() {
    const backendUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';
    return [
      {
        source: '/_api/:path*',
        destination: `${backendUrl}/:path*`,
      },
    ];
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
              "script-src 'self' 'unsafe-inline' https://accounts.google.com https://apis.google.com",
              "style-src 'self' 'unsafe-inline'",
              "font-src 'self'",
              "img-src 'self' blob: data: https:",
              `connect-src 'self' https://accounts.google.com`,
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
