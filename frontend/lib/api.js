import axios from 'axios';

export const getApiUrl = () => '/_api';

const api = axios.create({
  baseURL: getApiUrl(),
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
});

// --- CSRF token management (Response Header pattern) ---
// The backend sends X-CSRF-Token in every response header.
// We store it in memory and send it back on state-changing requests.
let _csrfToken = null;

export function getCsrfToken() {
  return _csrfToken;
}

// Read CSRF token from every response
api.interceptors.response.use(
  (response) => {
    const token = response.headers['x-csrf-token'];
    if (token) _csrfToken = token;
    return response;
  },
  (error) => {
    // Still capture token from error responses
    const token = error.response?.headers?.['x-csrf-token'];
    if (token) _csrfToken = token;

    if (typeof window !== 'undefined') {
      if (error.response?.status === 401 && !window.location.pathname.includes('/login')) {
        window.location.href = '/login';
      }
      if (error.response?.status === 403) {
        const detail = error.response?.data?.detail || '';
        if (detail.includes('2FA') && !window.location.pathname.includes('/setup-2fa')) {
          window.location.href = '/setup-2fa';
        }
      }
    }
    return Promise.reject(error);
  }
);

// Send CSRF token on every request
api.interceptors.request.use((config) => {
  if (_csrfToken) {
    config.headers['X-CSRF-Token'] = _csrfToken;
  }
  return config;
});

export default api;
