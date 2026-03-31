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
export const logout = (router) => {
  localStorage.removeItem('token');
  router.push('/login', '/login', { locale: router.locale });
};
