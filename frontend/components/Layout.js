import { useRouter } from 'next/router';
import { useTranslation } from 'next-i18next';
import { ArrowLeft, Users, UserCircle, MessageSquarePlus, LogOut } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';

export default function Layout({ children, showBack, backHref, title, actions, onFeedback, onLogout }) {
  const router = useRouter();
  const { t } = useTranslation(['common', 'agents']);
  const { logout: authLogout } = useAuth({ required: false });

  const handleLogout = onLogout || (() => {
    authLogout();
  });

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Subtle background gradient */}
      <div className="fixed inset-0 pointer-events-none">
        <div className="absolute inset-0 bg-gradient-to-br from-blue-50/50 via-transparent to-purple-50/30" />
      </div>

      {/* Top Navigation Bar */}
      <div className="sticky top-0 z-50 bg-white/80 backdrop-blur-xl border-b border-gray-200 shadow-subtle">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            {/* Left: Back + Title */}
            <div className="flex items-center space-x-3">
              {showBack && (
                <button
                  onClick={() => router.push(backHref || '/agents')}
                  className="flex items-center space-x-1.5 text-gray-500 hover:text-gray-900 transition-colors"
                >
                  <ArrowLeft className="w-5 h-5" />
                </button>
              )}
              {title && (
                <h1 className="text-lg font-heading font-bold text-gray-900">{title}</h1>
              )}
            </div>

            {/* Right: Nav icons + custom actions */}
            <div className="flex items-center space-x-1">
              {actions}
              <button
                onClick={() => router.push('/organization')}
                className="p-2.5 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded-button transition-colors"
                title={t('common:navigation.organization')}
              >
                <Users className="w-5 h-5" />
              </button>
              <button
                onClick={() => router.push('/profile')}
                className="p-2.5 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded-button transition-colors"
                title={t('common:navigation.profile')}
              >
                <UserCircle className="w-5 h-5" />
              </button>
              {onFeedback && (
                <button
                  onClick={onFeedback}
                  className="p-2.5 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded-button transition-colors"
                  title={t('agents:feedback.button')}
                >
                  <MessageSquarePlus className="w-5 h-5" />
                </button>
              )}
              <button
                onClick={handleLogout}
                className="p-2.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-button transition-colors"
                title={t('agents:logout')}
              >
                <LogOut className="w-5 h-5" />
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="relative">
        {children}
      </div>
    </div>
  );
}
