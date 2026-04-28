import { useState, useEffect } from 'react'
import { useTranslation } from 'next-i18next'
import { Shield } from 'lucide-react'

function getCookie(name) {
  const match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'))
  return match ? match[2] : null
}

function setCookie(name, value, days) {
  const expires = new Date(Date.now() + days * 864e5).toUTCString()
  document.cookie = `${name}=${value};expires=${expires};path=/;SameSite=Lax`
}

export function loadGA() {
  const gaId = process.env.NEXT_PUBLIC_GA_ID
  if (!gaId || window.__gaLoaded) return

  const script = document.createElement('script')
  script.src = `https://www.googletagmanager.com/gtag/js?id=${gaId}`
  script.async = true
  document.head.appendChild(script)

  window.dataLayer = window.dataLayer || []
  window.gtag = function () { window.dataLayer.push(arguments) }
  window.gtag('js', new Date())
  window.gtag('config', gaId, { page_path: window.location.pathname })
  window.__gaLoaded = true
}

export default function CookieBanner() {
  const { t } = useTranslation('common')
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    const consent = getCookie('cookie_consent')
    if (!consent) {
      setVisible(true)
    }
  }, [])

  const handleAccept = () => {
    setCookie('cookie_consent', 'accepted', 365)
    setVisible(false)
    loadGA()
  }

  const handleRefuse = () => {
    setCookie('cookie_consent', 'refused', 365)
    setVisible(false)
  }

  if (!visible) return null

  return (
    <div className="fixed bottom-0 inset-x-0 z-[9999] p-4 animate-fade-in">
      <div className="max-w-3xl mx-auto bg-white rounded-2xl shadow-elevated border border-gray-200 p-5 flex flex-col sm:flex-row items-center gap-4">
        <Shield className="w-6 h-6 text-blue-600 flex-shrink-0 hidden sm:block" />
        <p className="text-sm text-gray-700 flex-1 text-center sm:text-left">
          {t('cookies.message')}
        </p>
        <div className="flex gap-3 flex-shrink-0">
          <button
            onClick={handleRefuse}
            className="px-5 py-2.5 text-sm font-semibold text-gray-700 bg-white border border-gray-300 rounded-button hover:bg-gray-50 hover:border-gray-400 transition-all duration-200"
          >
            {t('cookies.refuse')}
          </button>
          <button
            onClick={handleAccept}
            className="px-5 py-2.5 text-sm font-semibold text-white bg-blue-600 rounded-button hover:bg-blue-700 shadow-subtle hover:shadow-card transition-all duration-200"
          >
            {t('cookies.accept')}
          </button>
        </div>
      </div>
    </div>
  )
}
