import { useEffect, useState } from 'react';
import { useRouter } from 'next/router';
import api from '../lib/api';

export function useAuth(options = {}) {
  const { redirectTo = '/login', required = true } = options;
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [authenticated, setAuthenticated] = useState(false);
  const router = useRouter();

  useEffect(() => {
    const verifyAuth = async () => {
      try {
        const response = await api.get('/auth/verify');

        if (response.data.authenticated) {
          setUser(response.data.user);
          setAuthenticated(true);
        } else if (required) {
          router.replace(redirectTo);
        }
      } catch (error) {
        setAuthenticated(false);
        setUser(null);

        if (required) {
          if (error.response?.status === 403) {
            router.replace('/setup-2fa');
          } else {
            router.replace(redirectTo);
          }
        }
      } finally {
        setLoading(false);
      }
    };

    verifyAuth();
  }, [router, redirectTo, required]);

  const logout = async () => {
    try {
      await api.post('/logout', {});
      setUser(null);
      setAuthenticated(false);
      router.replace('/login');
    } catch (error) {
      router.replace('/login');
    }
  };

  return {
    user,
    loading,
    authenticated,
    logout
  };
}
