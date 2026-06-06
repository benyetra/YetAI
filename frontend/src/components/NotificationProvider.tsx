'use client';

import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import { useAuth } from './Auth';
import { getWsUrl, apiRequest } from '@/lib/api-config';
import { parseApiTimestamp } from '@/lib/formatting';

export interface Notification {
  id: string;
  type: 'bet_won' | 'bet_lost' | 'odds_change' | 'system' | 'prediction' | 'achievement' | 'pipeline';
  title: string;
  message: string;
  timestamp: Date;
  read: boolean;
  data?: any;
  priority: 'low' | 'medium' | 'high';
  // True if this row originated from the admin_notifications table on the
  // backend. Drives REST mark-read instead of client-only state mutation.
  isAdminPipeline?: boolean;
  // Backend numeric id (for admin pipeline notifications). Stored separately
  // so the public `id` stays a string the way the rest of the UI expects.
  backendId?: number;
}

export interface WebSocketStatus {
  connected: boolean;
  reconnecting: boolean;
  lastConnected?: Date;
  reconnectAttempts: number;
}

interface NotificationContextType {
  notifications: Notification[];
  wsStatus: WebSocketStatus;
  unreadCount: number;
  addNotification: (notification: Omit<Notification, 'id' | 'timestamp' | 'read'>) => void;
  markAsRead: (id: string) => void;
  markAllAsRead: () => void;
  removeNotification: (id: string) => void;
  clearAll: () => void;
}

const NotificationContext = createContext<NotificationContextType | undefined>(undefined);

export const useNotifications = () => {
  const context = useContext(NotificationContext);
  if (!context) {
    throw new Error('useNotifications must be used within a NotificationProvider');
  }
  return context;
};

interface NotificationProviderProps {
  children: React.ReactNode;
}

// Backend payload from GET /api/admin/notifications and the
// 'admin_notification' WebSocket message type. Shape mirrors NotificationDTO
// in app/services/admin_notification_service.py.
interface AdminPipelinePayload {
  id: number;
  event_type: 'started' | 'finished' | 'failed';
  task_name: string;
  pipeline_label: string;
  sport?: string | null;
  status?: string | null;
  duration_s?: number | null;
  message: string;
  error_message?: string | null;
  extra?: Record<string, unknown>;
  created_at: string;
  is_read: boolean;
}

function adminPayloadToNotification(p: AdminPipelinePayload): Notification {
  const priority: Notification['priority'] =
    p.event_type === 'failed' ? 'high'
    : p.event_type === 'started' ? 'low'
    : 'medium';
  const title =
    p.event_type === 'started' ? `${p.pipeline_label} started`
    : p.event_type === 'failed' ? `${p.pipeline_label} failed`
    : `${p.pipeline_label} finished`;
  return {
    id: `admin-${p.id}`,
    backendId: p.id,
    isAdminPipeline: true,
    type: 'pipeline',
    title,
    message: p.message,
    timestamp: parseApiTimestamp(p.created_at) ?? new Date(),
    read: p.is_read,
    priority,
    data: p,
  };
}

export const NotificationProvider: React.FC<NotificationProviderProps> = ({ children }) => {
  const { user, isAuthenticated } = useAuth();
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [wsStatus, setWsStatus] = useState<WebSocketStatus>({
    connected: false,
    reconnecting: false,
    reconnectAttempts: 0
  });
  const [ws, setWs] = useState<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const isAdmin = !!user?.is_admin;
  const userId = user?.id ?? user?.user_id;

  // Reset on auth change
  useEffect(() => {
    if (!isAuthenticated) {
      setNotifications([]);
    }
  }, [isAuthenticated]);

  // On mount as admin, hydrate from REST so notifications that fired while
  // the user was offline still show up.
  useEffect(() => {
    if (!isAuthenticated || !isAdmin) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await apiRequest('/api/admin/notifications?limit=50');
        if (!res.ok) return;
        const body = await res.json();
        const items: AdminPipelinePayload[] = body?.notifications ?? [];
        if (cancelled) return;
        setNotifications(prev => {
          const existingBackendIds = new Set(
            prev.filter(n => n.isAdminPipeline).map(n => n.backendId)
          );
          const incoming = items
            .filter(p => !existingBackendIds.has(p.id))
            .map(adminPayloadToNotification);
          // Newest first; keep last 50 total to match prior behavior.
          return [...incoming, ...prev]
            .sort((a, b) => b.timestamp.getTime() - a.timestamp.getTime())
            .slice(0, 50);
        });
      } catch (err) {
        console.error('Failed to fetch admin notifications:', err);
      }
    })();
    return () => { cancelled = true; };
  }, [isAuthenticated, isAdmin]);

  // WebSocket connection management
  const connectWebSocket = useCallback(() => {
    if (!isAuthenticated || !userId) return;

    try {
      setWsStatus(prev => ({ ...prev, reconnecting: true }));

      const wsUrl = getWsUrl(`/ws/${userId}`);
      const websocket = new WebSocket(wsUrl);

      websocket.onopen = () => {
        console.log('WebSocket connected');
        reconnectAttemptsRef.current = 0;
        setWsStatus({
          connected: true,
          reconnecting: false,
          lastConnected: new Date(),
          reconnectAttempts: 0
        });
        setWs(websocket);
      };

      websocket.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          console.log('WebSocket message received:', data);

          switch (data.type) {
            case 'bet_update':
              addNotification({
                type: data.won ? 'bet_won' : 'bet_lost',
                title: data.won ? 'Bet Won!' : 'Bet Lost',
                message: data.won
                  ? `Your bet won! +$${data.amount}`
                  : `Your bet didn't win this time. -$${data.amount}`,
                priority: 'high',
                data: data
              });
              break;

            case 'odds_change':
              addNotification({
                type: 'odds_change',
                title: 'Odds Update',
                message: `Odds changed for ${data.game_name}`,
                priority: 'medium',
                data: data
              });
              break;

            case 'prediction_ready':
              addNotification({
                type: 'prediction',
                title: 'New AI Prediction',
                message: `New prediction available for ${data.game_name}`,
                priority: 'medium',
                data: data
              });
              break;

            case 'system_message':
              addNotification({
                type: 'system',
                title: 'System Notification',
                message: data.message,
                priority: data.priority || 'low',
                data: data
              });
              break;

            case 'admin_notification': {
              // Live push from the Celery pipeline signal handler.
              // Backend strips no fields; data has the same shape as REST.
              const payload = data as AdminPipelinePayload & { type: string };
              const notif = adminPayloadToNotification({ ...payload, is_read: false });
              setNotifications(prev => {
                if (prev.some(n => n.backendId === payload.id)) return prev;
                return [notif, ...prev].slice(0, 50);
              });
              if (typeof window !== 'undefined' && 'Notification' in window
                  && Notification.permission === 'granted' && notif.priority === 'high') {
                new Notification(notif.title, {
                  body: notif.message,
                  icon: '/favicon.ico',
                  tag: notif.id
                });
              }
              break;
            }
          }
        } catch (error) {
          console.error('Error parsing WebSocket message:', error);
        }
      };

      websocket.onclose = (event) => {
        console.log('WebSocket disconnected:', event.code, event.reason);
        setWsStatus(prev => ({
          ...prev,
          connected: false,
          reconnecting: false
        }));
        setWs(null);

        if (isAuthenticated) {
          const attempt = reconnectAttemptsRef.current;
          if (attempt < 5) {
            setTimeout(() => {
              reconnectAttemptsRef.current = attempt + 1;
              setWsStatus(prev => ({ ...prev, reconnectAttempts: attempt + 1 }));
              connectWebSocket();
            }, Math.min(1000 * Math.pow(2, attempt), 30000));
          }
        }
      };

      websocket.onerror = (error) => {
        console.error('WebSocket error:', error);
        setWsStatus(prev => ({ ...prev, reconnecting: false }));
      };

    } catch (error) {
      console.error('Failed to connect WebSocket:', error);
      setWsStatus(prev => ({ ...prev, reconnecting: false }));
    }
  }, [isAuthenticated, userId]);

  // Connect WebSocket when authenticated (key off user id, not whole user object)
  useEffect(() => {
    if (!isAuthenticated || !userId) return;
    connectWebSocket();

    return () => {
      setWs((prev) => {
        prev?.close();
        return null;
      });
    };
  }, [isAuthenticated, userId, connectWebSocket]);

  // Notification management functions
  const addNotification = useCallback((notification: Omit<Notification, 'id' | 'timestamp' | 'read'>) => {
    const newNotification: Notification = {
      ...notification,
      id: Date.now().toString() + Math.random().toString(36).substr(2, 9),
      timestamp: new Date(),
      read: false
    };

    setNotifications(prev => [newNotification, ...prev].slice(0, 50));

    if (typeof window !== 'undefined' && 'Notification' in window
        && Notification.permission === 'granted' && notification.priority === 'high') {
      new Notification(notification.title, {
        body: notification.message,
        icon: '/favicon.ico',
        tag: newNotification.id
      });
    }
  }, []);

  const markAsRead = useCallback((id: string) => {
    setNotifications(prev =>
      prev.map(notif =>
        notif.id === id ? { ...notif, read: true } : notif
      )
    );
    // Persist to backend if this is an admin pipeline notification.
    const target = notifications.find(n => n.id === id);
    if (target?.isAdminPipeline && target.backendId !== undefined) {
      apiRequest(`/api/admin/notifications/${target.backendId}/read`, { method: 'POST' })
        .catch(err => console.error('Failed to mark admin notification read:', err));
    }
  }, [notifications]);

  const markAllAsRead = useCallback(() => {
    const hadAdminUnread = notifications.some(n => n.isAdminPipeline && !n.read);
    setNotifications(prev =>
      prev.map(notif => ({ ...notif, read: true }))
    );
    if (isAdmin && hadAdminUnread) {
      apiRequest('/api/admin/notifications/mark-all-read', { method: 'POST' })
        .catch(err => console.error('Failed to mark all admin notifications read:', err));
    }
  }, [notifications, isAdmin]);

  const removeNotification = useCallback((id: string) => {
    setNotifications(prev => prev.filter(notif => notif.id !== id));
  }, []);

  const clearAll = useCallback(() => {
    setNotifications([]);
  }, []);

  // Request browser notification permission on mount
  useEffect(() => {
    if (typeof window !== 'undefined' && 'Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission();
    }
  }, []);

  const unreadCount = notifications.filter(n => !n.read).length;

  const value: NotificationContextType = {
    notifications,
    wsStatus,
    unreadCount,
    addNotification,
    markAsRead,
    markAllAsRead,
    removeNotification,
    clearAll
  };

  return (
    <NotificationContext.Provider value={value}>
      {children}
    </NotificationContext.Provider>
  );
};
