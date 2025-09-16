'use client';

import { useState, useEffect, forwardRef, useImperativeHandle } from 'react';
import { apiClient } from '@/lib/api';
import { User } from 'lucide-react';

interface AvatarProps {
  user?: {
    id?: number;
    email?: string;
    username?: string;
    first_name?: string;
    last_name?: string;
  };
  size?: 'sm' | 'md' | 'lg' | 'xl';
  className?: string;
  showFallback?: boolean;
}

export interface AvatarRef {
  refresh: () => void;
}

export const Avatar = forwardRef<AvatarRef, AvatarProps>(function Avatar(
  { user, size = 'md', className = '', showFallback = true },
  ref
) {
  const [avatarUrl, setAvatarUrl] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [forceRefresh, setForceRefresh] = useState(0);

  useImperativeHandle(ref, () => ({
    refresh: () => {
      setForceRefresh(prev => prev + 1);
    }
  }));

  // Size mappings
  const sizeClasses = {
    sm: 'w-8 h-8',
    md: 'w-10 h-10',
    lg: 'w-16 h-16',
    xl: 'w-24 h-24'
  };

  // Filter out width and height classes from className to prevent conflicts
  // but allow min-width and min-height classes for responsive sizing
  const filteredClassName = className
    .split(' ')
    .filter(cls => (!cls.match(/^w-\d+$/) && !cls.match(/^h-\d+$/)) || cls.includes('min-w-') || cls.includes('min-h-'))
    .join(' ');

  const iconSizes = {
    sm: 'w-4 h-4',
    md: 'w-5 h-5',
    lg: 'w-8 h-8',
    xl: 'w-12 h-12'
  };

  const textSizes = {
    sm: 'text-xs',
    md: 'text-sm',
    lg: 'text-lg',
    xl: 'text-2xl'
  };

  useEffect(() => {
    if (user?.id) {
      loadAvatar();
    }
  }, [user?.id, user?.avatar_url, forceRefresh]);

  const loadAvatar = async () => {
    if (!user?.id) return;
    
    setLoading(true);
    try {
      const response = await apiClient.get(`/api/auth/avatar/${user.id}`);
      if (response.status === 'success') {
        let avatarUrl = response.avatar_url || '';
        // Add cache busting parameter for uploaded avatars
        if (avatarUrl && avatarUrl.includes('/uploads/')) {
          avatarUrl += `?t=${Date.now()}`;
        }
        setAvatarUrl(avatarUrl);
        setError(false);
      }
    } catch (error) {
      console.error('Failed to load avatar:', error);
      setError(true);
    } finally {
      setLoading(false);
    }
  };

  const generateDefaultAvatar = () => {
    if (!user?.email) return '';

    // Generate initials
    let initials = 'U';
    const name = `${user.first_name || ''} ${user.last_name || ''}`.trim();
    
    if (name) {
      const parts = name.split(' ');
      if (parts.length >= 2) {
        initials = `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
      } else {
        initials = parts[0].substring(0, 2).toUpperCase();
      }
    } else {
      initials = user.email.substring(0, 2).toUpperCase();
    }

    // Generate color based on email
    const colors = ['#A855F7', '#F59E0B', '#3B82F6', '#10B981', '#EF4444', '#8B5CF6', '#EC4899', '#14B8A6'];
    const hash = user.email.split('').reduce((a, b) => a + b.charCodeAt(0), 0);
    const color = colors[hash % colors.length];

    const svgSize = size === 'sm' ? 32 : size === 'md' ? 40 : size === 'lg' ? 64 : 96;
    const fontSize = size === 'sm' ? 12 : size === 'md' ? 16 : size === 'lg' ? 24 : 36;

    return `data:image/svg+xml;base64,${btoa(`
      <svg width="${svgSize}" height="${svgSize}" xmlns="http://www.w3.org/2000/svg">
        <rect width="${svgSize}" height="${svgSize}" fill="${color}" rx="${svgSize / 2}"/>
        <text x="${svgSize / 2}" y="${svgSize / 2}" font-family="Arial, sans-serif" font-size="${fontSize}" 
              fill="white" text-anchor="middle" dominant-baseline="central">
          ${initials}
        </text>
      </svg>
    `)}`;
  };

  const handleImageError = () => {
    setError(true);
  };

  // Show loading state
  if (loading) {
    return (
      <div className={`${sizeClasses[size]} ${filteredClassName} rounded-full bg-gray-200 animate-pulse`} />
    );
  }

  // Show avatar image or fallback
  if (avatarUrl && !error) {
    return (
      <img
        src={avatarUrl}
        alt={`${user?.first_name || user?.username || 'User'} avatar`}
        className={`${sizeClasses[size]} ${filteredClassName} rounded-full object-cover`}
        onError={handleImageError}
      />
    );
  }

  // Show generated default avatar
  if (user?.email) {
    return (
      <img
        src={generateDefaultAvatar()}
        alt={`${user.first_name || user.username || user.email} avatar`}
        className={`${sizeClasses[size]} ${filteredClassName} rounded-full object-cover`}
      />
    );
  }

  // Show fallback icon if no user data
  if (showFallback) {
    return (
      <div className={`${sizeClasses[size]} ${filteredClassName} rounded-full bg-gray-300 flex items-center justify-center`}>
        <User className={`${iconSizes[size]} text-gray-600`} />
      </div>
    );
  }

  return null;
});

export default Avatar;