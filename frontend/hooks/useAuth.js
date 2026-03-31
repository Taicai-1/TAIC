/**
 * useAuth Hook - Authentication via HttpOnly Cookies
 *
 * Replaces localStorage-based auth with secure HttpOnly cookies.
 * Automatically verifies authentication and redirects if not authenticated.
 * Handles 403 from restricted 2FA tokens by redirecting to /setup-2fa.
 */

import { useEffect, useState } from 'react';
import { useRouter } from 'next/router';
import axios from 'axios';

const getApiUrl = () => {
  if (process.env.NEXT_PUBLIC_API_URL) {
    return process.env.NEXT_PUBLIC_API_URL;
  }
  if (typeof window !== "undefined" && window.location.hostname.includes("run.app")) {
    return window.location.origin.replace("frontend", "backend");
  }
  return "http://localhost:8080";
};

const API_URL = getApiUrl();

export function useAuth(options = {}) {
  const { redirectTo = '/login', required = true } = options;
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [authenticated, setAuthenticated] = useState(false);
  const router = useRouter();

  useEffect(() => {
    const verifyAuth = async () => {
      try {
        const response = await axios.get(`${API_URL}/auth/verify`, {
          withCredentials: true  // CRITICAL: Send HttpOnly cookie
        });

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
          // 403 = restricted token (needs 2FA setup)
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
      await axios.post(`${API_URL}/logout`, {}, {
        withCredentials: true
      });

      setUser(null);
      setAuthenticated(false);
      router.replace('/login');
    } catch (error) {
      // Force redirect even if logout fails
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
