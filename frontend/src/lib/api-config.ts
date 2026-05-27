/**
 * Centralized API configuration for environment-aware URL handling
 * This ensures consistent API URL usage across the entire frontend application
 * Updated: 2025-10-08 - Vercel env vars configured for api.yetai.app
 */

import { endSession, getStoredAuthToken } from './auth-session';

const AUTH_ENDPOINTS_WITHOUT_SESSION = [
  '/api/auth/login',
  '/api/auth/register',
  '/api/auth/google',
  '/api/auth/forgot-password',
  '/api/auth/reset-password',
  '/api/auth/verify-email',
];

function shouldEndSessionOn401(endpoint: string, hadAuthToken: boolean, status: number): boolean {
  if (status !== 401 || !hadAuthToken) return false;
  const normalized = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
  return !AUTH_ENDPOINTS_WITHOUT_SESSION.some((path) => normalized.startsWith(path));
}

interface ApiConfig {
  baseURL: string;
  wsURL: string;
  environment: 'development' | 'staging' | 'production';
}

/**
 * Determine the current environment based on various indicators
 */
function getCurrentEnvironment(): 'development' | 'staging' | 'production' {
  // Check if we're in browser environment
  if (typeof window === 'undefined') {
    return 'development'; // Default for SSR
  }

  const hostname = window.location.hostname;
  
  // Production environment
  if (hostname === 'yetai.app' || hostname === 'www.yetai.app') {
    return 'production';
  }
  
  // Staging environment
  if (hostname === 'staging.yetai.app' || hostname.includes('staging')) {
    return 'staging';
  }
  
  // Development environment (localhost, 127.0.0.1, etc.)
  return 'development';
}

/**
 * Get API configuration based on environment
 */
function getApiConfig(): ApiConfig {
  const environment = getCurrentEnvironment();
  
  // Always check environment variable first
  const envApiUrl = process.env.NEXT_PUBLIC_API_URL;
  
  if (envApiUrl) {
    // If environment variable is set, use it
    const wsUrl = envApiUrl.replace(/^https?:\/\//, '').replace(/^http:\/\//, 'ws://').replace(/^https:\/\//, 'wss://');
    return {
      baseURL: envApiUrl,
      wsURL: envApiUrl.startsWith('https') ? `wss://${wsUrl}` : `ws://${wsUrl}`,
      environment
    };
  }
  
  // Fallback to environment-based defaults
  switch (environment) {
    case 'production':
      return {
        baseURL: 'https://api.yetai.app',
        wsURL: 'wss://api.yetai.app',
        environment
      };
      
    case 'staging':
      return {
        baseURL: 'https://staging-backend.up.railway.app',
        wsURL: 'wss://staging-backend.up.railway.app',
        environment
      };
      
    case 'development':
    default:
      return {
        baseURL: 'http://localhost:8000',
        wsURL: 'ws://localhost:8000',
        environment
      };
  }
}

// Export singleton instance
export const apiConfig = getApiConfig();

/**
 * Get full API URL for a given endpoint
 */
export function getApiUrl(endpoint: string): string {
  // Ensure endpoint starts with /
  const normalizedEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
  // Remove trailing slash from baseURL to prevent double slashes
  const baseURL = apiConfig.baseURL.replace(/\/$/, '');
  return `${baseURL}${normalizedEndpoint}`;
}

/**
 * Get WebSocket URL for a given endpoint
 */
export function getWsUrl(endpoint: string): string {
  // Ensure endpoint starts with /
  const normalizedEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
  // Remove trailing slash from wsURL to prevent double slashes
  const wsURL = apiConfig.wsURL.replace(/\/$/, '');
  return `${wsURL}${normalizedEndpoint}`;
}

/**
 * Utility function for making API requests with consistent configuration
 */
export async function apiRequest(
  endpoint: string, 
  options: RequestInit = {}
): Promise<Response> {
  const url = getApiUrl(endpoint);

  const method = (options.method ?? 'GET').toString().toUpperCase();
  const defaultHeaders: HeadersInit = {};
  // GET/HEAD with Content-Type: application/json is a non-simple CORS request in
  // browsers and can break cross-origin calls if the API preflight is strict.
  if (method !== 'GET' && method !== 'HEAD') {
    defaultHeaders['Content-Type'] = 'application/json';
  }

  // Add auth token if available
  const token = getStoredAuthToken();
  if (token) {
    (defaultHeaders as Record<string, string>).Authorization = `Bearer ${token}`;
  }

  const config: RequestInit = {
    ...options,
    headers: {
      ...defaultHeaders,
      ...options.headers,
    },
  };
  
  const response = await fetch(url, config);
  if (shouldEndSessionOn401(endpoint, Boolean(token), response.status)) {
    endSession('unauthorized');
  }
  return response;
}

/**
 * Extract a human-readable error message from a failed API response.
 */
export async function parseApiErrorResponse(response: Response): Promise<string> {
  try {
    const data = await response.json();
    const detail = data?.detail;
    if (typeof detail === 'string') {
      return detail;
    }
    if (Array.isArray(detail)) {
      return detail
        .map((item: { msg?: string }) => item?.msg || String(item))
        .join(', ');
    }
    if (data?.message) {
      return data.message;
    }
  } catch {
    // Response body was not JSON
  }
  return `HTTP ${response.status}: ${response.statusText}`;
}

/**
 * Debug information (useful for development)
 */
export function getApiDebugInfo(): {
  config: ApiConfig;
  envVar: string | undefined;
  hostname: string | undefined;
} {
  return {
    config: apiConfig,
    envVar: process.env.NEXT_PUBLIC_API_URL,
    hostname: typeof window !== 'undefined' ? window.location.hostname : undefined,
  };
}