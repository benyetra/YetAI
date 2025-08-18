'use client';

import { useState, useEffect } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { apiClient } from '@/lib/api';
import { 
  Share2, 
  Calendar,
  Trophy,
  TrendingUp,
  Target,
  Clock,
  CheckCircle,
  XCircle,
  DollarSign,
  ExternalLink,
  Twitter,
  Facebook,
  MessageCircle,
  Copy,
  Check,
  AlertCircle,
  ArrowLeft
} from 'lucide-react';

interface SharedBet {
  id: string;
  bet_type: string;
  selection: string;
  odds: number;
  amount: number;
  potential_win: number;
  status: string;
  placed_at: string;
  result_amount?: number;
  home_team?: string;
  away_team?: string;
  sport?: string;
  commence_time?: string;
  shared_at: string;
  views: number;
  legs?: Array<{
    id: string;
    game_id: string;
    bet_type: string;
    selection: string;
    odds: number;
    status: string;
  }>;
  leg_count?: number;
}

export default function SharedBetPage() {
  const params = useParams();
  const router = useRouter();
  const shareId = params.shareId as string;
  
  const [sharedBet, setSharedBet] = useState<SharedBet | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (shareId) {
      fetchSharedBet();
    }
  }, [shareId]);

  const fetchSharedBet = async () => {
    try {
      setLoading(true);
      const response = await apiClient.get(`/api/share/bet/${shareId}`);
      
      if (response.status === 'success') {
        setSharedBet(response.shared_bet);
      } else {
        setError('Bet not found or link has expired');
      }
    } catch (error: any) {
      setError('Failed to load shared bet');
      console.error('Error fetching shared bet:', error);
    } finally {
      setLoading(false);
    }
  };

  const formatOdds = (odds: number) => {
    const roundedOdds = Math.round(odds);
    return roundedOdds > 0 ? `+${roundedOdds}` : `${roundedOdds}`;
  };

  const getStatusEmoji = (status: string) => {
    switch (status) {
      case 'won': return '🏆';
      case 'lost': return '😤';
      case 'pending': return '⏰';
      case 'live': return '🔴';
      default: return '🎲';
    }
  };

  const formatBetTitle = (bet: SharedBet) => {
    // Handle parlay bets with legs
    if (bet.bet_type === 'parlay' && bet.legs && bet.legs.length > 0) {
      return `${bet.legs.length}-Leg Parlay`;
    }
    
    if (bet.home_team && bet.away_team) {
      const gameInfo = `${bet.away_team} @ ${bet.home_team}`;
      if (bet.bet_type === 'moneyline') {
        const team = bet.selection === 'home' ? bet.home_team : bet.away_team;
        return `${team} to Win (${gameInfo})`;
      } else if (bet.bet_type === 'spread') {
        const team = bet.selection === 'home' ? bet.home_team : bet.away_team;
        return `${team} Spread (${gameInfo})`;
      } else if (bet.bet_type === 'total') {
        return `${bet.selection.toUpperCase()} (${gameInfo})`;
      }
    }
    
    // Fallback for parlay without legs
    if (bet.bet_type === 'parlay') {
      return `${bet.leg_count || 'Multi'}-Leg Parlay`;
    }
    
    return `${bet.bet_type.toUpperCase()} - ${bet.selection.toUpperCase()}`;
  };

  const shareText = sharedBet ? (() => {
    let betDescription = formatBetTitle(sharedBet);
    
    // Add parlay legs details if available
    if (sharedBet.bet_type === 'parlay' && sharedBet.legs && sharedBet.legs.length > 0) {
      const legDescriptions = sharedBet.legs.map((leg, index) => {
        let legText = `${index + 1}. ${leg.selection.toUpperCase()}`;
        if (leg.bet_type) {
          legText += ` (${leg.bet_type})`;
        }
        if (leg.odds) {
          const formattedOdds = leg.odds > 0 ? `+${Math.round(leg.odds)}` : `${Math.round(leg.odds)}`;
          legText += ` ${formattedOdds}`;
        }
        return legText;
      }).join('\n');
      
      betDescription = `${sharedBet.legs.length}-Leg Parlay:\n${legDescriptions}`;
    }
    
    return `${getStatusEmoji(sharedBet.status)} Check out this sports bet on ${betDescription}!\n\n💰 Bet: $${sharedBet.amount.toFixed(2)}\n📊 Odds: ${formatOdds(sharedBet.odds)}\n🎯 Potential Win: $${sharedBet.potential_win.toFixed(2)}\n\n#SportsBetting #YetAI`;
  })() : '';

  const copyToClipboard = () => {
    const url = window.location.href;
    navigator.clipboard.writeText(`${shareText}\n\n${url}`);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const shareOnTwitter = () => {
    const url = window.location.href;
    const twitterUrl = `https://twitter.com/intent/tweet?text=${encodeURIComponent(shareText)}&url=${encodeURIComponent(url)}`;
    window.open(twitterUrl, '_blank');
  };

  const shareOnFacebook = () => {
    const url = window.location.href;
    const facebookUrl = `https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(url)}&quote=${encodeURIComponent(shareText)}`;
    window.open(facebookUrl, '_blank');
  };

  const shareOnWhatsApp = () => {
    const url = window.location.href;
    const whatsappUrl = `https://wa.me/?text=${encodeURIComponent(`${shareText}\n\n${url}`)}`;
    window.open(whatsappUrl, '_blank');
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
          <p className="text-gray-600">Loading shared bet...</p>
        </div>
      </div>
    );
  }

  if (error || !sharedBet) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center max-w-md mx-auto p-6">
          <AlertCircle className="w-16 h-16 text-red-500 mx-auto mb-4" />
          <h1 className="text-2xl font-bold text-gray-900 mb-2">Bet Not Found</h1>
          <p className="text-gray-600 mb-6">
            {error || 'This shared bet link may have expired or been removed.'}
          </p>
          <button
            onClick={() => router.push('/')}
            className="inline-flex items-center px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
          >
            <ArrowLeft className="w-4 h-4 mr-2" />
            Go to YetAI
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 py-8 px-4">
      <div className="max-w-2xl mx-auto">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="flex items-center justify-center mb-4">
            <div className="bg-blue-600 text-white p-3 rounded-full">
              <Share2 className="w-8 h-8" />
            </div>
          </div>
          <h1 className="text-3xl font-bold text-gray-900 mb-2">Shared Sports Bet</h1>
          <p className="text-gray-600">Someone shared their betting pick with you</p>
        </div>

        {/* Bet Card */}
        <div className="bg-white rounded-lg shadow-lg border border-gray-200 overflow-hidden mb-6">
          {/* Bet Header */}
          <div className="bg-gradient-to-r from-blue-50 to-purple-50 border-b border-blue-200 p-6">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center space-x-2">
                <span className="text-3xl">{getStatusEmoji(sharedBet.status)}</span>
                <span className={`px-3 py-1 rounded-full text-sm font-medium ${
                  sharedBet.status === 'won' ? 'bg-green-100 text-green-800' :
                  sharedBet.status === 'lost' ? 'bg-red-100 text-red-800' :
                  sharedBet.status === 'pending' ? 'bg-yellow-100 text-yellow-800' :
                  sharedBet.status === 'live' ? 'bg-green-100 text-green-800' :
                  'bg-gray-100 text-gray-800'
                }`}>
                  {sharedBet.status.charAt(0).toUpperCase() + sharedBet.status.slice(1)}
                </span>
              </div>
              <div className="text-sm text-gray-500 flex items-center">
                <Calendar className="w-4 h-4 mr-1" />
                {new Date(sharedBet.placed_at).toLocaleDateString()}
              </div>
            </div>
            
            <h2 className="text-xl font-bold text-gray-900 mb-2">
              {formatBetTitle(sharedBet)}
            </h2>
            
            {sharedBet.bet_type === 'parlay' && sharedBet.legs && sharedBet.legs.length > 0 && (
              <div className="mb-4">
                <div className="text-xs text-gray-500 mb-2">Legs:</div>
                <div className="space-y-1">
                  {sharedBet.legs.map((leg, index) => (
                    <div key={leg.id || index} className="text-sm bg-white bg-opacity-50 rounded px-2 py-1">
                      <span className="font-medium">{index + 1}.</span> {leg.selection} ({leg.bet_type}) 
                      <span className="ml-2 text-blue-600">
                        {leg.odds > 0 ? `+${Math.round(leg.odds)}` : Math.round(leg.odds)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            
            {sharedBet.sport && (
              <div className="text-sm font-medium text-blue-600 mb-4">
                {sharedBet.sport}
              </div>
            )}
            
            {/* Bet Stats */}
            <div className="grid grid-cols-3 gap-4">
              <div className="bg-white bg-opacity-70 rounded-lg p-3 text-center">
                <div className="text-xs text-gray-600 mb-1">Bet Amount</div>
                <div className="font-bold text-gray-900">${sharedBet.amount.toFixed(2)}</div>
              </div>
              <div className="bg-white bg-opacity-70 rounded-lg p-3 text-center">
                <div className="text-xs text-gray-600 mb-1">Odds</div>
                <div className="font-bold text-gray-900">{formatOdds(sharedBet.odds)}</div>
              </div>
              <div className="bg-white bg-opacity-70 rounded-lg p-3 text-center">
                <div className="text-xs text-gray-600 mb-1">
                  {sharedBet.status === 'won' ? 'Won' : sharedBet.status === 'lost' ? 'Lost' : 'Potential Win'}
                </div>
                <div className={`font-bold ${
                  sharedBet.status === 'won' ? 'text-green-600' :
                  sharedBet.status === 'lost' ? 'text-red-600' :
                  'text-blue-600'
                }`}>
                  ${sharedBet.status === 'won' && sharedBet.result_amount ? 
                    sharedBet.result_amount.toFixed(2) : 
                    sharedBet.potential_win.toFixed(2)
                  }
                </div>
              </div>
            </div>
          </div>

          {/* Additional Info */}
          <div className="p-6">
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <span className="text-gray-500">Shared:</span>
                <span className="ml-2 text-gray-900">{new Date(sharedBet.shared_at).toLocaleDateString()}</span>
              </div>
              <div>
                <span className="text-gray-500">Views:</span>
                <span className="ml-2 text-gray-900">{sharedBet.views}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Share Options */}
        <div className="bg-white rounded-lg shadow border border-gray-200 p-6 mb-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">Share this bet</h3>
          
          <div className="grid grid-cols-3 gap-3 mb-4">
            <button
              onClick={shareOnTwitter}
              className="flex flex-col items-center p-3 border border-gray-300 rounded-lg hover:bg-blue-50 hover:border-blue-500 transition-colors"
            >
              <Twitter className="w-6 h-6 text-blue-500 mb-1" />
              <span className="text-xs font-medium text-gray-700">Twitter</span>
            </button>
            
            <button
              onClick={shareOnFacebook}
              className="flex flex-col items-center p-3 border border-gray-300 rounded-lg hover:bg-blue-50 hover:border-blue-500 transition-colors"
            >
              <Facebook className="w-6 h-6 text-blue-600 mb-1" />
              <span className="text-xs font-medium text-gray-700">Facebook</span>
            </button>
            
            <button
              onClick={shareOnWhatsApp}
              className="flex flex-col items-center p-3 border border-gray-300 rounded-lg hover:bg-green-50 hover:border-green-500 transition-colors"
            >
              <MessageCircle className="w-6 h-6 text-green-600 mb-1" />
              <span className="text-xs font-medium text-gray-700">WhatsApp</span>
            </button>
          </div>

          <button
            onClick={copyToClipboard}
            className="w-full flex items-center justify-center space-x-2 p-3 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors"
          >
            {copied ? (
              <>
                <Check className="w-5 h-5 text-green-600" />
                <span className="font-medium text-green-600">Copied to Clipboard!</span>
              </>
            ) : (
              <>
                <Copy className="w-5 h-5 text-gray-600" />
                <span className="font-medium text-gray-700">Copy Link</span>
              </>
            )}
          </button>
        </div>

        {/* YetAI Branding */}
        <div className="bg-white rounded-lg shadow border border-gray-200 p-6 text-center">
          <h3 className="text-lg font-semibold text-gray-900 mb-2">Like this bet?</h3>
          <p className="text-gray-600 mb-4">
            Join YetAI for AI-powered sports betting insights and track your own bets!
          </p>
          <div className="flex space-x-3 justify-center">
            <button
              onClick={() => router.push('/')}
              className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors flex items-center"
            >
              <ExternalLink className="w-4 h-4 mr-2" />
              Visit YetAI
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}