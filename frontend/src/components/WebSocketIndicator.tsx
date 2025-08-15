'use client';

import React from 'react';
import { Activity, AlertCircle, Wifi, WifiOff } from 'lucide-react';
import { useNotifications } from './NotificationProvider';

export const WebSocketIndicator: React.FC = () => {
  const { wsStatus } = useNotifications();

  const getIndicatorContent = () => {
    if (wsStatus.connected) {
      return {
        icon: Activity,
        text: 'Live',
        className: 'bg-green-50 text-green-700 border-green-200',
        iconClassName: 'text-green-600 animate-pulse',
        title: `Connected since ${wsStatus.lastConnected?.toLocaleTimeString()}`
      };
    }

    if (wsStatus.reconnecting) {
      return {
        icon: Wifi,
        text: 'Connecting...',
        className: 'bg-yellow-50 text-yellow-700 border-yellow-200',
        iconClassName: 'text-yellow-600 animate-spin',
        title: `Reconnecting (attempt ${wsStatus.reconnectAttempts + 1})`
      };
    }

    return {
      icon: WifiOff,
      text: 'Offline',
      className: 'bg-red-50 text-red-700 border-red-200',
      iconClassName: 'text-red-600',
      title: wsStatus.reconnectAttempts > 0 
        ? `Connection failed after ${wsStatus.reconnectAttempts} attempts`
        : 'Not connected to real-time updates'
    };
  };

  const { icon: Icon, text, className, iconClassName, title } = getIndicatorContent();

  return (
    <div 
      className={`flex items-center space-x-2 px-3 py-1 rounded-full border text-xs font-medium transition-all duration-200 ${className}`}
      title={title}
    >
      <Icon className={`w-3 h-3 ${iconClassName}`} />
      <span>{text}</span>
    </div>
  );
};

export const DetailedWebSocketStatus: React.FC = () => {
  const { wsStatus } = useNotifications();

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4">
      <h3 className="text-sm font-medium text-gray-900 mb-3">Real-time Connection Status</h3>
      
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-sm text-gray-600">Status</span>
          <div className="flex items-center space-x-2">
            {wsStatus.connected ? (
              <>
                <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse"></div>
                <span className="text-sm font-medium text-green-600">Connected</span>
              </>
            ) : wsStatus.reconnecting ? (
              <>
                <div className="w-2 h-2 bg-yellow-500 rounded-full animate-pulse"></div>
                <span className="text-sm font-medium text-yellow-600">Reconnecting</span>
              </>
            ) : (
              <>
                <div className="w-2 h-2 bg-red-500 rounded-full"></div>
                <span className="text-sm font-medium text-red-600">Disconnected</span>
              </>
            )}
          </div>
        </div>

        {wsStatus.lastConnected && (
          <div className="flex items-center justify-between">
            <span className="text-sm text-gray-600">Last Connected</span>
            <span className="text-sm text-gray-900">
              {wsStatus.lastConnected.toLocaleTimeString()}
            </span>
          </div>
        )}

        {wsStatus.reconnectAttempts > 0 && (
          <div className="flex items-center justify-between">
            <span className="text-sm text-gray-600">Reconnect Attempts</span>
            <span className="text-sm text-gray-900">{wsStatus.reconnectAttempts}</span>
          </div>
        )}

        <div className="pt-2 border-t border-gray-200">
          <div className="flex items-start space-x-2">
            {wsStatus.connected ? (
              <AlertCircle className="w-4 h-4 text-green-600 mt-0.5" />
            ) : (
              <AlertCircle className="w-4 h-4 text-gray-400 mt-0.5" />
            )}
            <div>
              <p className="text-xs text-gray-600">
                {wsStatus.connected 
                  ? 'You\'re receiving real-time updates for odds, bet results, and notifications.'
                  : 'Real-time features may be limited. Check your internet connection.'
                }
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};