'use client';

import React, { useState } from 'react';
import { useRouter } from 'next/navigation';
import { 
  Bell, 
  X, 
  Check, 
  Trash2, 
  Filter, 
  DollarSign, 
  TrendingUp, 
  Brain, 
  Trophy, 
  AlertCircle,
  CheckCircle,
  Clock
} from 'lucide-react';
import { useNotifications, Notification } from './NotificationProvider';

const NotificationIcon: React.FC<{ type: Notification['type'] }> = ({ type }) => {
  const iconProps = { className: "w-4 h-4" };
  
  switch (type) {
    case 'bet_won':
      return <CheckCircle {...iconProps} className="w-4 h-4 text-green-600" />;
    case 'bet_lost':
      return <X {...iconProps} className="w-4 h-4 text-red-600" />;
    case 'odds_change':
      return <TrendingUp {...iconProps} className="w-4 h-4 text-blue-600" />;
    case 'prediction':
      return <Brain {...iconProps} className="w-4 h-4 text-purple-600" />;
    case 'achievement':
      return <Trophy {...iconProps} className="w-4 h-4 text-yellow-600" />;
    case 'system':
    default:
      return <AlertCircle {...iconProps} className="w-4 h-4 text-gray-600" />;
  }
};

const NotificationItem: React.FC<{ 
  notification: Notification; 
  onMarkAsRead: (id: string) => void;
  onRemove: (id: string) => void;
}> = ({ notification, onMarkAsRead, onRemove }) => {
  const timeAgo = (date: Date) => {
    const now = new Date();
    const diffInMinutes = Math.floor((now.getTime() - date.getTime()) / (1000 * 60));
    
    if (diffInMinutes < 1) return 'Just now';
    if (diffInMinutes < 60) return `${diffInMinutes}m ago`;
    
    const diffInHours = Math.floor(diffInMinutes / 60);
    if (diffInHours < 24) return `${diffInHours}h ago`;
    
    const diffInDays = Math.floor(diffInHours / 24);
    return `${diffInDays}d ago`;
  };

  return (
    <div 
      className={`
        p-4 border-b border-gray-100 hover:bg-gray-50 transition-colors group
        ${!notification.read ? 'bg-blue-50 border-blue-100' : ''}
      `}
    >
      <div className="flex items-start space-x-3">
        <div className="flex-shrink-0 mt-1">
          <NotificationIcon type={notification.type} />
        </div>
        
        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between">
            <div className="flex-1">
              <p className={`text-sm font-medium ${!notification.read ? 'text-gray-900' : 'text-gray-700'}`}>
                {notification.title}
              </p>
              <p className="text-sm text-gray-600 mt-1">
                {notification.message}
              </p>
              <div className="flex items-center space-x-4 mt-2">
                <div className="flex items-center space-x-1 text-xs text-gray-500">
                  <Clock className="w-3 h-3" />
                  <span>{timeAgo(notification.timestamp)}</span>
                </div>
                {notification.priority === 'high' && (
                  <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-red-100 text-red-800">
                    High Priority
                  </span>
                )}
              </div>
            </div>
            
            <div className="flex items-center space-x-1 opacity-0 group-hover:opacity-100 transition-opacity">
              {!notification.read && (
                <button
                  onClick={() => onMarkAsRead(notification.id)}
                  className="p-1 hover:bg-gray-200 rounded"
                  title="Mark as read"
                >
                  <Check className="w-4 h-4 text-gray-600" />
                </button>
              )}
              <button
                onClick={() => onRemove(notification.id)}
                className="p-1 hover:bg-gray-200 rounded"
                title="Remove notification"
              >
                <Trash2 className="w-4 h-4 text-gray-600" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

interface NotificationPanelProps {
  isOpen: boolean;
  onClose: () => void;
}

export const NotificationPanel: React.FC<NotificationPanelProps> = ({ isOpen, onClose }) => {
  const router = useRouter();
  const { 
    notifications, 
    unreadCount, 
    markAsRead, 
    markAllAsRead, 
    removeNotification, 
    clearAll 
  } = useNotifications();
  
  const [filter, setFilter] = useState<'all' | 'unread' | 'high'>('all');

  const filteredNotifications = notifications.filter(notification => {
    switch (filter) {
      case 'unread':
        return !notification.read;
      case 'high':
        return notification.priority === 'high';
      default:
        return true;
    }
  });

  if (!isOpen) return null;

  return (
    <div className="absolute right-0 mt-2 w-96 bg-white rounded-lg shadow-lg border border-gray-200 z-50">
      {/* Header */}
      <div className="p-4 border-b border-gray-200">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <Bell className="w-5 h-5 text-gray-600" />
            <h3 className="font-semibold text-gray-900">Notifications</h3>
            {unreadCount > 0 && (
              <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-blue-100 text-blue-800">
                {unreadCount} new
              </span>
            )}
          </div>
          <button
            onClick={onClose}
            className="p-1 hover:bg-gray-100 rounded"
          >
            <X className="w-4 h-4 text-gray-600" />
          </button>
        </div>

        {/* Filter and Actions */}
        <div className="flex items-center justify-between mt-3">
          <div className="flex items-center space-x-1">
            <Filter className="w-4 h-4 text-gray-500" />
            <select
              value={filter}
              onChange={(e) => setFilter(e.target.value as 'all' | 'unread' | 'high')}
              className="text-xs border-none bg-transparent text-gray-600 focus:ring-0"
            >
              <option value="all">All ({notifications.length})</option>
              <option value="unread">Unread ({unreadCount})</option>
              <option value="high">High Priority ({notifications.filter(n => n.priority === 'high').length})</option>
            </select>
          </div>

          <div className="flex items-center space-x-2">
            {unreadCount > 0 && (
              <button
                onClick={markAllAsRead}
                className="text-xs text-blue-600 hover:text-blue-700"
              >
                Mark all read
              </button>
            )}
            {notifications.length > 0 && (
              <button
                onClick={clearAll}
                className="text-xs text-red-600 hover:text-red-700"
              >
                Clear all
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Notification List */}
      <div className="max-h-96 overflow-y-auto">
        {filteredNotifications.length === 0 ? (
          <div className="p-8 text-center">
            <Bell className="w-12 h-12 text-gray-300 mx-auto mb-4" />
            <p className="text-gray-500">
              {filter === 'unread' ? 'No unread notifications' : 'No notifications'}
            </p>
          </div>
        ) : (
          <div>
            {filteredNotifications.map((notification) => (
              <NotificationItem
                key={notification.id}
                notification={notification}
                onMarkAsRead={markAsRead}
                onRemove={removeNotification}
              />
            ))}
          </div>
        )}
      </div>

      {/* Footer */}
      {notifications.length > 0 && (
        <div className="p-3 text-center border-t border-gray-200">
          <button 
            onClick={() => {
              router.push('/profile');
              onClose();
            }}
            className="text-sm text-blue-600 hover:text-blue-700"
          >
            View notification settings
          </button>
        </div>
      )}
    </div>
  );
};