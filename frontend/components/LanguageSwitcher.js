import { useRouter } from 'next/router'
import { useState, useRef, useEffect } from 'react'
import { Globe } from 'lucide-react'

const languages = {
  fr: { name: 'Français', flag: '🇫🇷' },
  en: { name: 'English', flag: '🇬🇧' }
}

export default function LanguageSwitcher() {
  const router = useRouter()
  const [isOpen, setIsOpen] = useState(false)
  const dropdownRef = useRef(null)

  const currentLang = languages[router.locale] || languages.fr

  const changeLanguage = (locale) => {
    console.log('Changing language to:', locale)
    document.cookie = `NEXT_LOCALE=${locale};max-age=31536000;path=/`
    setIsOpen(false)

    // Use Next.js locale routing API for proper locale switching
    // This works for both dynamic and static routes
    router.push(
      { pathname: router.pathname, query: router.query },
      router.asPath,
      { locale: locale }
    )
  }

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center space-x-2 px-4 py-2.5 rounded-button bg-white hover:bg-white border border-gray-200 hover:border-blue-300 shadow-subtle hover:shadow-card transition-all duration-300 group"
        aria-label="Change language"
      >
        <Globe className="w-5 h-5 text-blue-600 group-hover:text-blue-700 transition-colors" />
        <span className="text-2xl group-hover:scale-110 transition-transform">{currentLang.flag}</span>
        <span className="text-sm font-semibold text-gray-700 group-hover:text-blue-700 transition-colors">{currentLang.name}</span>
      </button>

      {isOpen && (
        <div className="absolute right-0 mt-2 w-52 bg-white rounded-button shadow-elevated border border-gray-200 py-2 z-[9999] animate-fade-in">
          {Object.entries(languages).map(([locale, lang]) => (
            <button
              key={locale}
              onClick={(e) => {
                e.preventDefault()
                e.stopPropagation()
                changeLanguage(locale)
              }}
              className={`w-full flex items-center space-x-3 px-4 py-3 hover:bg-blue-50 transition-all duration-200 ${
                router.locale === locale ? 'bg-blue-50 border-l-4 border-blue-600' : ''
              }`}
            >
              <span className="text-2xl">{lang.flag}</span>
              <span className={`text-sm font-medium ${router.locale === locale ? 'text-blue-700 font-semibold' : 'text-gray-700'}`}>{lang.name}</span>
              {router.locale === locale && (
                <span className="ml-auto text-blue-600 text-lg font-bold">✓</span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
