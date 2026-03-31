const path = require('path')

module.exports = {
  i18n: {
    locales: ['fr', 'en'],
    defaultLocale: 'fr',
    localeDetection: true,
  },
  localePath: typeof window === 'undefined'
    ? path.join(process.cwd(), 'public/locales')
    : '/locales',
  reloadOnPrerender: process.env.NODE_ENV === 'development',
  fallbackLng: { default: ['fr'] },
  ns: ['common', 'auth', 'agents', 'chat', 'teams', 'profile', 'dashboard', 'errors', 'organization', 'sources'],
  defaultNS: 'common',
  react: { useSuspense: false },
}
