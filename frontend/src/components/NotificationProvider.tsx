'use client';

import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { useAuth } from './Auth';

export interface Notification {
  id: string;
  type: 'bet_won' | 'bet_lost' | 'odds_change' | 'system' | 'prediction' | 'achievement';
  title: string;
  message: string;
  timestamp: Date;
  read: boolean;
  data?: any;
  priority: 'low' | 'medium' | 'high';
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

export const NotificationProvider: React.FC<NotificationProviderProps> = ({ children }) => {
  const { user, isAuthenticated } = useAuth();
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [wsStatus, setWsStatus] = useState<WebSocketStatus>({
    connected: false,
    reconnecting: false,
    reconnectAttempts: 0
  });
  const [ws, setWs] = useState<WebSocket | null>(null);

  // Initialize with some sample notifications
  useEffect(() => {
    if (isAuthenticated) {
      // Don't add sample notifications to avoid showing fake data
      setNotifications([]);
    }
  }, [isAuthenticated]);

  // WebSocket connection management
  const connectWebSocket = useCallback(() => {
    if (!isAuthenticated || !user) return;

    try {
      setWsStatus(prev => ({ ...prev, reconnecting: true }));
      
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${protocol}//localhost:8000/ws/${user.id}`;
      
      const websocket = new WebSocket(wsUrl);
      
      websocket.onopen = () => {
        console.log('WebSocket connected');
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
          
          // Handle different message types
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

        // Attempt to reconnect after a delay (exponential backoff)
        if (isAuthenticated) {
          setTimeout(() => {
            setWsStatus(prev => ({ 
              ...prev, 
              reconnectAttempts: prev.reconnectAttempts + 1 
            }));
            if (wsStatus.reconnectAttempts < 5) {
              connectWebSocket();
            }
          }, Math.min(1000 * Math.pow(2, wsStatus.reconnectAttempts), 30000));
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
  }, [isAuthenticated, user, wsStatus.reconnectAttempts]);

  // Connect WebSocket when authenticated
  useEffect(() => {
    if (isAuthenticated && user && !ws) {
      connectWebSocket();
    }

    // Cleanup on unmount or when user logs out
    return () => {
      if (ws) {
        ws.close();
        setWs(null);
      }
    };
  }, [isAuthenticated, user]);

  // Notification management functions
  const addNotification = useCallback((notification: Omit<Notification, 'id' | 'timestamp' | 'read'>) => {
    const newNotification: Notification = {
      ...notification,
      id: Date.now().toString() + Math.random().toString(36).substr(2, 9),
      timestamp: new Date(),
      read: false
    };

    setNotifications(prev => [newNotification, ...prev].slice(0, 50)); // Keep last 50

    // Show browser notification if permission granted
    if (Notification.permission === 'granted' && notification.priority === 'high') {
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
  }, []);

  const markAllAsRead = useCallback(() => {
    setNotifications(prev => 
      prev.map(notif => ({ ...notif, read: true }))
    );
  }, []);

  const removeNotification = useCallback((id: string) => {
    setNotifications(prev => prev.filter(notif => notif.id !== id));
  }, []);

  const clearAll = useCallback(() => {
    setNotifications([]);
  }, []);

  // Request notification permission on mount
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