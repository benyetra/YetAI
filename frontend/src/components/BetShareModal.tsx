'use client';

import { useState, useEffect } from 'react';
import { 
  Share2, 
  Copy, 
  Twitter, 
  Facebook, 
  MessageCircle,
  Instagram,
  X,
  Check,
  ExternalLink,
  TrendingUp,
  Target,
  Calendar,
  Loader2
} from 'lucide-react';
import { apiClient } from '@/lib/api';
import { useAuth } from './Auth';
import { formatLocalDate } from '@/lib/formatting';

interface BetShareModalProps {
  bet: any;
  isOpen: boolean;
  onClose: () => void;
}

export default function BetShareModal({ bet, isOpen, onClose }: BetShareModalProps) {
  const { token } = useAuth();
  const [copied, setCopied] = useState(false);
  const [shareUrl, setShareUrl] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (isOpen && bet?.id && token) {
      generateShareUrl();
    }
  }, [isOpen, bet?.id, token]);

  if (!isOpen) return null;

  // Generate share URL using backend API
  const generateShareUrl = async () => {
    if (!token || !bet?.id) return;
    
    setLoading(true);
    try {
      const response = await apiClient.post('/api/bets/share', {
        bet_id: bet.id
      }, token);
      
      if (response.status === 'success' && response.share?.share_url) {
        // Backend returns full URL, use it directly
        setShareUrl(response.share.share_url);
      }
    } catch (error) {
      console.error('Failed to generate share URL:', error);
      // Fallback to simple URL
      const baseUrl = window.location.origin;
      setShareUrl(`${baseUrl}/share/bet/${bet.id}`);
    } finally {
      setLoading(false);
    }
  };

  // Format bet for sharing
  const formatBetForSharing = () => {
    // Handle parlay bets with legs
    if (bet.bet_type === 'parlay' && bet.legs && bet.legs.length > 0) {
      const legDescriptions = bet.legs.map((leg: any, index: number) => {
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
      
      return `${bet.legs.length}-Leg Parlay:\n${legDescriptions}`;
    }
    
    // Handle regular bets
    if (bet.home_team && bet.away_team) {
      const gameInfo = `${bet.away_team} @ ${bet.home_team}`;
      if (bet.bet_type === 'moneyline') {
        const team = bet.selection === 'home' ? bet.home_team : bet.away_team;
        return `${team} to Win (${gameInfo})`;
      } else if (bet.bet_type === 'spread') {
        // Use full selection if it contains spread info, otherwise fallback
        if (bet.selection && (bet.selection.includes('+') || bet.selection.includes('-'))) {
          return `${bet.selection} (${gameInfo})`;
        }
        const team = bet.selection === 'home' ? bet.home_team : bet.away_team;
        return `${team} Spread (${gameInfo})`;
      } else if (bet.bet_type === 'total') {
        return `${bet.selection.toUpperCase()} (${gameInfo})`;
      }
    }
    
    // Fallback for other bet types
    if (bet.bet_type === 'parlay') {
      return `${bet.selection || 'Multi-leg Parlay'}`;
    }
    
    return `${bet.bet_type.toUpperCase()} - ${bet.selection.toUpperCase()}`;
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

  const shareText = `${getStatusEmoji(bet.status)} Just ${bet.status === 'pending' ? 'placed' : bet.status} a bet on ${formatBetForSharing()}!\n\n💰 Bet: $${bet.amount.toFixed(2)}\n📊 Odds: ${formatOdds(bet.odds)}\n🎯 Potential Win: $${bet.potential_win.toFixed(2)}\n\n#SportsBetting #YetAI`;

  const copyToClipboard = () => {
    if (!shareUrl) return;
    navigator.clipboard.writeText(`${shareText}\n\n${shareUrl}`);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const shareOnTwitter = () => {
    if (!shareUrl) return;
    const twitterUrl = `https://twitter.com/intent/tweet?text=${encodeURIComponent(shareText)}&url=${encodeURIComponent(shareUrl)}`;
    window.open(twitterUrl, '_blank');
  };

  const shareOnFacebook = () => {
    if (!shareUrl) return;
    const facebookUrl = `https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(shareUrl)}&quote=${encodeURIComponent(shareText)}`;
    window.open(facebookUrl, '_blank');
  };

  const shareOnWhatsApp = () => {
    if (!shareUrl) return;
    const whatsappUrl = `https://wa.me/?text=${encodeURIComponent(`${shareText}\n\n${shareUrl}`)}`;
    window.open(whatsappUrl, '_blank');
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg max-w-md w-full max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="sticky top-0 bg-white border-b border-gray-200 p-6 flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <Share2 className="w-5 h-5 text-blue-600" />
            <h2 className="text-xl font-bold text-gray-900">Share Your Bet</h2>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 transition-colors"
          >
            <X className="w-6 h-6" />
          </button>
        </div>

        {/* Bet Preview Card */}
        <div className="p-6">
          <div className="bg-gradient-to-r from-blue-50 to-purple-50 rounded-lg p-4 mb-6 border border-blue-200">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center space-x-2">
                <span className="text-2xl">{getStatusEmoji(bet.status)}</span>
                <span className={`px-2 py-1 rounded-full text-xs font-medium ${
                  bet.status === 'won' ? 'bg-green-100 text-green-800' :
                  bet.status === 'lost' ? 'bg-red-100 text-red-800' :
                  bet.status === 'pending' ? 'bg-yellow-100 text-yellow-800' :
                  bet.status === 'live' ? 'bg-green-100 text-green-800' :
                  'bg-gray-100 text-gray-800'
                }`}>
                  {bet.status.charAt(0).toUpperCase() + bet.status.slice(1)}
                </span>
              </div>
              <div className="text-sm text-gray-500 flex items-center">
                <Calendar className="w-4 h-4 mr-1" />
                {formatLocalDate(bet.placed_at)}
              </div>
            </div>
            
            <h3 className="text-lg font-semibold text-gray-900 mb-2">
              {bet.bet_type === 'parlay' && bet.legs ? 
                `${bet.legs.length}-Leg Parlay` : 
                formatBetForSharing()
              }
            </h3>
            
            {bet.bet_type === 'parlay' && bet.legs && bet.legs.length > 0 && (
              <div className="mb-3">
                <div className="text-xs text-gray-500 mb-2">Legs:</div>
                <div className="space-y-1">
                  {bet.legs.map((leg: any, index: number) => (
                    <div key={index} className="text-sm bg-white bg-opacity-50 rounded px-2 py-1 text-gray-900">
                      <span className="font-medium">{index + 1}.</span> {leg.selection} ({leg.bet_type}) 
                      <span className="ml-2 text-blue-600">
                        {leg.odds > 0 ? `+${Math.round(leg.odds)}` : Math.round(leg.odds)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            
            {bet.sport && (
              <div className="text-sm text-blue-600 mb-3 font-medium">
                {bet.sport}
              </div>
            )}
            
            <div className="grid grid-cols-3 gap-3 text-center">
              <div className="bg-white bg-opacity-70 rounded-lg p-2">
                <div className="text-xs text-gray-600 mb-1">Bet Amount</div>
                <div className="font-semibold text-gray-900">${bet.amount.toFixed(2)}</div>
              </div>
              <div className="bg-white bg-opacity-70 rounded-lg p-2">
                <div className="text-xs text-gray-600 mb-1">Odds</div>
                <div className="font-semibold text-gray-900">{formatOdds(bet.odds)}</div>
              </div>
              <div className="bg-white bg-opacity-70 rounded-lg p-2">
                <div className="text-xs text-gray-600 mb-1">
                  {bet.status === 'won' ? 'Won' : bet.status === 'lost' ? 'Lost' : 'Potential Win'}
                </div>
                <div className={`font-semibold ${
                  bet.status === 'won' ? 'text-green-600' :
                  bet.status === 'lost' ? 'text-red-600' :
                  'text-blue-600'
                }`}>
                  ${bet.status === 'won' && bet.result_amount ? 
                    bet.result_amount.toFixed(2) : 
                    bet.potential_win.toFixed(2)
                  }
                </div>
              </div>
            </div>
          </div>

          {/* Share Options */}
          <div className="space-y-4">
            {loading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="w-6 h-6 animate-spin text-blue-600" />
                <span className="ml-2 text-sm text-gray-600">Generating share link...</span>
              </div>
            ) : (
              <>
                <div>
                  <h3 className="text-sm font-medium text-gray-700 mb-3">Share to Social Media</h3>
                  <div className="grid grid-cols-3 gap-3">
                    <button
                      onClick={shareOnTwitter}
                      disabled={!shareUrl}
                      className="flex flex-col items-center p-3 border border-gray-300 rounded-lg hover:bg-blue-50 hover:border-blue-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      <Twitter className="w-6 h-6 text-blue-500 mb-1" />
                      <span className="text-xs font-medium text-gray-700">Twitter</span>
                    </button>
                
                    <button
                      onClick={shareOnFacebook}
                      disabled={!shareUrl}
                      className="flex flex-col items-center p-3 border border-gray-300 rounded-lg hover:bg-blue-50 hover:border-blue-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      <Facebook className="w-6 h-6 text-blue-600 mb-1" />
                      <span className="text-xs font-medium text-gray-700">Facebook</span>
                    </button>
                    
                    <button
                      onClick={shareOnWhatsApp}
                      disabled={!shareUrl}
                      className="flex flex-col items-center p-3 border border-gray-300 rounded-lg hover:bg-green-50 hover:border-green-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      <MessageCircle className="w-6 h-6 text-green-600 mb-1" />
                      <span className="text-xs font-medium text-gray-700">WhatsApp</span>
                    </button>
                  </div>
                </div>

                {/* Copy Link */}
                <div>
                  <h3 className="text-sm font-medium text-gray-700 mb-3">Copy & Share</h3>
                  <button
                    onClick={copyToClipboard}
                    disabled={!shareUrl}
                    className="w-full flex items-center justify-center space-x-2 p-3 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {copied ? (
                      <>
                        <Check className="w-5 h-5 text-green-600" />
                        <span className="font-medium text-green-600">Copied to Clipboard!</span>
                      </>
                    ) : (
                      <>
                        <Copy className="w-5 h-5 text-gray-600" />
                        <span className="font-medium text-gray-700">Copy Bet Details & Link</span>
                      </>
                    )}
                  </button>
                </div>

                {/* Preview Text */}
                <div>
                  <h3 className="text-sm font-medium text-gray-700 mb-2">Share Preview</h3>
                  <div className="bg-gray-50 rounded-lg p-3 text-sm text-gray-600 font-mono whitespace-pre-wrap">
                    {shareText}
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}