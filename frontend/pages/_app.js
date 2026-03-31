import { useEffect } from 'react'
import { useRouter } from 'next/router'
import '../styles/globals.css'
import { appWithTranslation } from 'next-i18next'
import nextI18NextConfig from '../next-i18next.config.js'

function App({ Component, pageProps }) {
  const router = useRouter()

  useEffect(() => {
    const gaId = process.env.NEXT_PUBLIC_GA_ID
    if (!gaId) return

    const handleRouteChange = (url) => {
      window.gtag?.('config', gaId, { page_path: url })
    }

    router.events.on('routeChangeComplete', handleRouteChange)
    return () => router.events.off('routeChangeComplete', handleRouteChange)
  }, [router.events])

  return <Component {...pageProps} />
}

export default appWithTranslation(App, nextI18NextConfig)
