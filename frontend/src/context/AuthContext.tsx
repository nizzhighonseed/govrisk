import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react';
import { getMe, logoutLocal } from '../services/api';

interface User {
  id: string;
  userId?: string;
  fullName: string;
  email: string;
  role: string;
  department?: string;
  designation?: string;
  isActive: boolean;
  isApproved: boolean;
  mustChangePassword?: boolean;
  createdAt: string;
  updatedAt: string;
  lastLogin?: string;
}

interface AuthContextType {
  user: User | null;
  isAuthenticated: boolean;
  loading: boolean;
  setUser: (user: User | null) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  isAuthenticated: false,
  loading: true,
  setUser: () => {},
  logout: () => {},
});

export function useAuth() {
  return useContext(AuthContext);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem('govrisk_access_token');
    if (!token) {
      setLoading(false);
      return;
    }
    getMe()
      .then((u) => setUser(u))
      .catch(() => {
        logoutLocal();
        setUser(null);
      })
      .finally(() => setLoading(false));
  }, []);

  const handleLogout = useCallback(() => {
    logoutLocal();
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user,
        loading,
        setUser,
        logout: handleLogout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}
