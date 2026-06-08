import { apiRequest } from '@/lib/api-config';

export interface ProposeTradeAssets {
  players: string[];
  picks: number[];
  faab: number;
}

export interface RecommendationTradeAssetsInput {
  players: Array<{ id?: string | number; player_id?: string | number; name?: string }>;
  picks?: number[];
  faab?: number;
}

export interface BuilderTradeAssets {
  players: number[];
  picks: number[];
  faab: number;
}

export function resolveSleeperPlayerId(player: {
  id?: string | number;
  player_id?: string | number;
}): string | null {
  const raw = player.id ?? player.player_id;
  if (raw == null || raw === '') {
    return null;
  }
  const id = String(raw);
  if (id === '0' || id === 'NaN') {
    return null;
  }
  return id;
}

export function buildTradeAssetsFromRecommendation(
  assets: RecommendationTradeAssetsInput
): ProposeTradeAssets {
  const players = (assets.players ?? [])
    .map(resolveSleeperPlayerId)
    .filter((id): id is string => id != null);

  return {
    players,
    picks: assets.picks ?? [],
    faab: assets.faab ?? 0,
  };
}

export function buildTradeAssetsFromBuilder(assets: BuilderTradeAssets): ProposeTradeAssets {
  return {
    players: assets.players.map((id) => String(id)),
    picks: assets.picks,
    faab: assets.faab,
  };
}

export interface ProposeTradeRequest {
  league_id: string;
  team1_id: number;
  team2_id: number;
  team1_gives: ProposeTradeAssets;
  team2_gives: ProposeTradeAssets;
  trade_reason?: string;
  persist?: boolean;
}

export interface ProposeTradeResponse {
  success: boolean;
  validated?: boolean;
  evaluation?: Record<string, unknown>;
  persisted?: boolean;
  error?: string;
}

export async function proposeTrade(
  request: ProposeTradeRequest
): Promise<
  { ok: true; data: ProposeTradeResponse } | { ok: false; status: number; message: string }
> {
  const token = typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null;

  const response = await apiRequest('/api/v1/fantasy/trade-analyzer/propose', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      ...request,
      persist: request.persist ?? false,
    }),
  });

  if (!response.ok) {
    let message = 'Failed to propose trade';
    try {
      const errBody = await response.json();
      if (typeof errBody.detail === 'string') {
        message = errBody.detail;
      } else if (typeof errBody.error === 'string') {
        message = errBody.error;
      } else if (errBody.detail && typeof errBody.detail === 'object') {
        message = JSON.stringify(errBody.detail);
      }
    } catch {
      try {
        const text = await response.text();
        if (text) {
          message = text;
        }
      } catch {
        // keep default message
      }
    }
    return { ok: false, status: response.status, message };
  }

  const data = (await response.json()) as ProposeTradeResponse;
  return { ok: true, data };
}
