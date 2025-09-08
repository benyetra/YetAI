import { useEffect, useRef, useState, useCallback } from 'react';
import { useAuth } from '@/components/Auth';
import { getWsUrl } from '@/lib/api-config';

interface WebSocketMessage {
  type: string;
  data?: any;
  game_id?: string;
  timestamp?: string;
}

interface GameUpdate {
  home_odds?: number;
  away_odds?: number;
  spread?: number;
  total?: number;
  movement?: 'up' | 'down' | 'stable';
  home_score?: number;
  away_score?: number;
  quarter?: number;
  time_remaining?: string;
  game_status?: string;
  last_updated?: string;
}

export function useWebSocket() {
  const { user } = useAuth();
  const ws = useRef<WebSocket | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<WebSocketMessage | null>(null);
  const [gameUpdates, setGameUpdates] = useState<Record<string, GameUpdate>>({});
  const reconnectTimeout = useRef<NodeJS.Timeout>();
  const pingInterval = useRef<NodeJS.Timeout>();
  const reconnectAttempts = useRef(0);
  const maxReconnectAttempts = 5;

  const connect = useCallback(() => {
    if (!user?.id) {
      console.log('WebSocket: No user ID available, skipping connection');
      return;
    }

    // Temporarily disable WebSocket connections to resolve admin page loading issues
    console.log('WebSocket: Connection temporarily disabled');
    return;

    try {
      // WebSocket URL using centralized configuration
      const wsUrl = getWsUrl(`/ws/${user.id}`);
      console.log('WebSocket: Attempting to connect to', wsUrl);
      ws.current = new WebSocket(wsUrl);

      ws.current.onopen = () => {
        console.log('WebSocket connected');
        setIsConnected(true);
        reconnectAttempts.current = 0;
        
        // Start ping interval to keep connection alive
        pingInterval.current = setInterval(() => {
          sendMessage({ type: 'ping' });
        }, 30000);
      };

      ws.current.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          setLastMessage(message);
          
          // Handle different message types
          switch (message.type) {
            case 'game_update':
              handleGameUpdate(message);
              break;
            case 'bet_notification':
              handleBetNotification(message);
              break;
            case 'connection':
              console.log('WebSocket connection confirmed:', message.status);
              break;
            case 'subscription':
              console.log(`Game subscription ${message.status}:`, message.game_id);
              break;
            case 'pong':
              // Ping response received - connection is alive
              break;
            default:
              console.log('Unknown message type:', message.type);
          }
        } catch (error) {
          console.error('Error parsing WebSocket message:', error);
        }
      };

      ws.current.onclose = (event) => {
        console.log('WebSocket disconnected:', event.code, event.reason);
        setIsConnected(false);
        
        // Clear ping interval
        if (pingInterval.current) {
          clearInterval(pingInterval.current);
        }
        
        // Attempt to reconnect if not manually closed
        if (event.code !== 1000 && reconnectAttempts.current < maxReconnectAttempts) {
          const delay = Math.min(1000 * Math.pow(2, reconnectAttempts.current), 30000);
          console.log(`Attempting to reconnect in ${delay}ms...`);
          
          reconnectTimeout.current = setTimeout(() => {
            reconnectAttempts.current++;
            connect();
          }, delay);
        } else if (reconnectAttempts.current >= maxReconnectAttempts) {
          console.error('Max reconnection attempts reached');
        }
      };

      ws.current.onerror = (error) => {
        console.error('WebSocket error:', error);
        console.error('WebSocket readyState:', ws.current?.readyState);
        console.error('User ID:', user?.id);
      };
    } catch (error) {
      console.error('Failed to connect WebSocket:', error);
    }
  }, [user?.id]);

  const disconnect = useCallback(() => {
    if (ws.current) {
      ws.current.close(1000, 'User disconnect');
      ws.current = null;
    }
    
    if (reconnectTimeout.current) {
      clearTimeout(reconnectTimeout.current);
    }
    
    if (pingInterval.current) {
      clearInterval(pingInterval.current);
    }
    
    setIsConnected(false);
  }, []);

  const sendMessage = useCallback((message: WebSocketMessage) => {
    if (ws.current && ws.current.readyState === WebSocket.OPEN) {
      try {
        ws.current.send(JSON.stringify(message));
      } catch (error) {
        console.error('Error sending WebSocket message:', error);
      }
    } else {
      console.warn('WebSocket not connected, unable to send message:', message);
    }
  }, []);

  const subscribeToGame = useCallback((gameId: string) => {
    console.log('Subscribing to game:', gameId);
    sendMessage({ type: 'subscribe', game_id: gameId });
  }, [sendMessage]);

  const unsubscribeFromGame = useCallback((gameId: string) => {
    console.log('Unsubscribing from game:', gameId);
    sendMessage({ type: 'unsubscribe', game_id: gameId });
  }, [sendMessage]);

  const handleGameUpdate = useCallback((message: WebSocketMessage) => {
    if (message.game_id && message.data) {
      console.log('Game update received:', message.game_id, message.data);
      
      setGameUpdates(prev => ({
        ...prev,
        [message.game_id!]: {
          ...prev[message.game_id!],
          ...message.data,
          last_updated: message.timestamp
        }
      }));

      // Trigger custom event for other components to listen to
      window.dispatchEvent(new CustomEvent('gameUpdate', {
        detail: {
          gameId: message.game_id,
          data: message.data,
          timestamp: message.timestamp
        }
      }));
    }
  }, []);

  const handleBetNotification = useCallback((message: WebSocketMessage) => {
    console.log('Bet notification received:', message.data);
    
    // Trigger custom event for bet notifications
    window.dispatchEvent(new CustomEvent('betNotification', {
      detail: message.data
    }));

    // You could also show a toast notification here
    if (message.data?.type === 'bet_settled') {
      const { bet_id, status, amount } = message.data;
      console.log(`Bet ${bet_id} settled: ${status} for $${amount}`);
    }
  }, []);

  // Get latest update for a specific game
  const getGameUpdate = useCallback((gameId: string): GameUpdate | undefined => {
    return gameUpdates[gameId];
  }, [gameUpdates]);

  // Get all game updates
  const getAllGameUpdates = useCallback(() => {
    return gameUpdates;
  }, [gameUpdates]);

  // Clear game updates
  const clearGameUpdates = useCallback(() => {
    setGameUpdates({});
  }, []);

  useEffect(() => {
    if (user?.id) {
      connect();
    }
    
    return () => {
      disconnect();
    };
  }, [user?.id, connect, disconnect]);

  return {
    isConnected,
    lastMessage,
    gameUpdates,
    sendMessage,
    subscribeToGame,
    unsubscribeFromGame,
    getGameUpdate,
    getAllGameUpdates,
    clearGameUpdates,
    reconnect: connect,
    disconnect
  };
}