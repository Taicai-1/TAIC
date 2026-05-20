import axios from 'axios';

export const getApiUrl = () => {
  if (process.env.NEXT_PUBLIC_API_URL) {
    return process.env.NEXT_PUBLIC_API_URL;
  }
  if (typeof window !== 'undefined' && window.location.hostname.includes('run.app')) {
    return window.location.origin.replace('frontend', 'backend');
  }
  return 'http://localhost:8080';
};

const api = axios.create({
  baseURL: getApiUrl(),
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Security: CSRF Double Submit Cookie — read csrf_token cookie and send as header
api.interceptors.request.use((config) => {
  if (typeof document !== 'undefined') {
    const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/);
    if (match) {
      config.headers['X-CSRF-Token'] = decodeURIComponent(match[1]);
    }
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
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

export default api;
