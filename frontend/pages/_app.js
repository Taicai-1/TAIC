import { useEffect } from 'react'
import { useRouter } from 'next/router'
import '../styles/globals.css'
import { appWithTranslation } from 'next-i18next'
import nextI18NextConfig from '../next-i18next.config.js'
import CookieBanner, { loadGA } from '../components/CookieBanner'

function App({ Component, pageProps }) {
  const router = useRouter()

  useEffect(() => {
    const consent = document.cookie.match(/(^| )cookie_consent=([^;]+)/)
    if (consent && consent[2] === 'accepted') {
      loadGA()
    }
  }, [])

  useEffect(() => {
    const gaId = process.env.NEXT_PUBLIC_GA_ID
    if (!gaId) return

    const handleRouteChange = (url) => {
      if (window.__gaLoaded) {
        window.gtag?.('config', gaId, { page_path: url })
      }
    }

    router.events.on('routeChangeComplete', handleRouteChange)
    return () => router.events.off('routeChangeComplete', handleRouteChange)
  }, [router.events])

  return (
    <>
      <Component {...pageProps} />
      <CookieBanner />
    </>
  )
}

export default appWithTranslation(App, nextI18NextConfig)
