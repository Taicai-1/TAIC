import { useRouter } from 'next/router';
import { useTranslation } from 'next-i18next';
import { AlertTriangle } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import Sidebar from './Sidebar';

export default function Layout({ children, title, actions, className = '' }) {
  const router = useRouter();
  const { t } = useTranslation('common');
  const { user } = useAuth({ required: false });
  const hasNoOrg = user && !user.company_id;

  return (
    <div className="flex min-h-screen bg-slate-50">
      <Sidebar />

      {/* Main area */}
      <div className={`flex-1 flex flex-col min-w-0 ${className}`}>

        {/* No-org warning */}
        {hasNoOrg && (
          <div className="bg-amber-50 border-b-2 border-amber-300">
            <div className="max-w-5xl mx-auto px-6 py-3 flex items-center gap-4">
              <AlertTriangle className="w-6 h-6 text-amber-600 shrink-0" />
              <div className="flex-1">
                <p className="text-sm font-bold text-amber-900">{t('noOrg.title')}</p>
                <p className="text-xs text-amber-700">{t('noOrg.description')}</p>
              </div>
              <button
                onClick={() => router.push('/organization')}
                className="shrink-0 px-4 py-2 bg-amber-600 text-white text-sm font-semibold rounded-button hover:bg-amber-700 transition-colors"
              >
                {t('noOrg.action')}
              </button>
            </div>
          </div>
        )}

        {/* Optional inline page header (title + actions) */}
        {(title || actions) && (
          <div className="px-8 pt-7 pb-0 flex items-center justify-between">
            {title && (
              <h1 className="font-heading font-extrabold text-[22px] text-slate-900 tracking-tight">
                {title}
              </h1>
            )}
            {actions && <div className="flex items-center gap-3">{actions}</div>}
          </div>
        )}

        {children}
      </div>
    </div>
  );
}
