import { useState, useEffect } from 'react';
import { useRouter } from 'next/router';
import { useTranslation } from 'next-i18next';
import { Bot, Users, Building2, Settings, LogOut, User, ChevronsLeft, ChevronsRight } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import Image from 'next/image';

const NAV_ITEMS = [
  { href: '/agents',       labelKey: 'navigation.agents',       Icon: Bot },
  { href: '/teams',        labelKey: 'navigation.teams',        Icon: Users },
  { href: '/organization', labelKey: 'navigation.organization', Icon: Building2 },
  { href: '/profile',      labelKey: 'navigation.profile',      Icon: Settings },
];

const STORAGE_KEY = 'taic_sidebar_collapsed';

export default function Sidebar({ collapsed: controlledCollapsed, onToggle }) {
  const router = useRouter();
  const { t } = useTranslation('common');
  const { user, logout } = useAuth({ required: false });

  const [internalCollapsed, setInternalCollapsed] = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === '1') setInternalCollapsed(true);
  }, []);

  const isControlled = controlledCollapsed !== undefined;
  const collapsed = isControlled ? controlledCollapsed : internalCollapsed;

  const toggle = () => {
    if (isControlled) {
      onToggle?.(!collapsed);
    } else {
      const next = !internalCollapsed;
      setInternalCollapsed(next);
      localStorage.setItem(STORAGE_KEY, next ? '1' : '0');
    }
  };

  const isActive = (href) =>
    href === '/agents'
      ? router.pathname === '/agents' || router.pathname === '/'
      : router.pathname.startsWith(href);

  return (
    <aside className={`${collapsed ? 'w-[68px]' : 'w-[220px]'} shrink-0 flex flex-col bg-white border-r border-gray-200 min-h-screen sticky top-0 transition-[width] duration-200 ease-out`}>
      {/* Brand */}
      <div className={`flex items-center ${collapsed ? 'justify-center' : 'gap-2.5'} px-4 py-5 mb-4 relative`}>
        <Image src="/logo-and.png" alt="TAIC" width={28} height={28} className="object-contain shrink-0" />
        {!collapsed && (
          <span className="font-heading font-extrabold text-[16px] text-slate-900 tracking-tight">
            TAIC
          </span>
        )}
        {collapsed ? (
          <button
            onClick={toggle}
            title={t('navigation.expand', { defaultValue: 'Expand' })}
            className="absolute top-14 left-1/2 -translate-x-1/2 p-1 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-sm transition-colors"
          >
            <ChevronsRight className="w-4 h-4" />
          </button>
        ) : (
          <button
            onClick={toggle}
            title={t('navigation.collapse', { defaultValue: 'Collapse' })}
            className="ml-auto p-1 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-sm transition-colors"
          >
            <ChevronsLeft className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Nav */}
      <nav className={`flex-1 flex flex-col gap-0.5 px-2 ${collapsed ? 'mt-4' : ''}`}>
        {NAV_ITEMS.map(({ href, labelKey, Icon }) => {
          const active = isActive(href);
          return (
            <button
              key={href}
              onClick={() => router.push(href)}
              title={collapsed ? t(labelKey) : undefined}
              className={[
                'flex items-center w-full rounded-button text-sm font-medium transition-colors',
                collapsed ? 'justify-center px-2 py-2.5' : 'gap-2.5 px-3 py-2.5 text-left',
                active
                  ? 'bg-primary-50 text-primary-600 font-semibold'
                  : 'text-gray-500 hover:bg-gray-50 hover:text-gray-800',
              ].join(' ')}
            >
              <Icon
                className={['w-4 h-4 shrink-0', active ? 'text-primary-600' : 'text-gray-400'].join(' ')}
              />
              {!collapsed && t(labelKey)}
            </button>
          );
        })}
      </nav>

      {/* User footer */}
      <div className="border-t border-gray-200 p-3 mt-2">
        {collapsed ? (
          <div className="flex flex-col items-center gap-2">
            <div className="w-8 h-8 rounded-sm bg-primary-50 flex items-center justify-center shrink-0">
              <User className="w-4 h-4 text-primary-600" />
            </div>
            <button
              onClick={() => logout()}
              title={t('navigation.logout')}
              className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-sm transition-colors"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-2.5 px-2 py-2 rounded-button">
            <div className="w-8 h-8 rounded-sm bg-primary-50 flex items-center justify-center shrink-0">
              <User className="w-4 h-4 text-primary-600" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-gray-800 truncate">
                {user?.username || user?.email || '—'}
              </p>
              <p className="text-xs text-gray-400">
                {user?.role === 'admin' ? 'Administrateur' : 'Membre'}
              </p>
            </div>
            <button
              onClick={() => logout()}
              title={t('navigation.logout')}
              className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-sm transition-colors"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        )}
      </div>
    </aside>
  );
}
