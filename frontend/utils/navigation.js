import api from '../lib/api';

/**
 * Navigate to a path while preserving the current locale
 * @param {Object} router - Next.js router instance
 * @param {string} path - Path to navigate to
 * @param {Object} options - Additional router options
 */
export const navigateWithLocale = (router, path, options = {}) => {
  router.push(path, path, { locale: router.locale, ...options });
};

/**
 * Logout and redirect to login page with current locale
 * @param {Object} router - Next.js router instance
 */
export const logout = async (router) => {
  try {
    await api.post('/logout', {});
  } catch (e) {
    // Continue with redirect even if logout call fails
  }
  router.push('/login', '/login', { locale: router.locale });
};
