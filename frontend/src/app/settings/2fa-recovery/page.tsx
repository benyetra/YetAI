'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Layout from '@/components/Layout';
import { useAuth } from '@/components/Auth';
import { apiClient } from '@/lib/api';
import { 
  Shield, 
  Key, 
  Download,
  RefreshCw,
  Copy,
  Check,
  AlertCircle,
  Mail,
  ArrowLeft
} from 'lucide-react';

export default function TwoFactorRecoveryPage() {
  const { isAuthenticated, loading, user, token } = useAuth();
  const router = useRouter();
  
  const [backupCodes, setBackupCodes] = useState<string[]>([]);
  const [usedCodes, setUsedCodes] = useState<string[]>([]);
  const [isGenerating, setIsGenerating] = useState(false);
  const [showCodes, setShowCodes] = useState(false);
  const [copiedCode, setCopiedCode] = useState<string | null>(null);
  const [emailSent, setEmailSent] = useState(false);
  const [message, setMessage] = useState<{type: 'success' | 'error', text: string} | null>(null);

  useEffect(() => {
    if (!loading && !isAuthenticated) {
      router.push('/login');
    } else if (user && !user.totp_enabled) {
      router.push('/settings');
    } else if (user) {
      loadBackupCodesStatus();
    }
  }, [isAuthenticated, loading, user, router]);

  const loadBackupCodesStatus = async () => {
    try {
      const response = await apiClient.get('/api/auth/2fa/backup-codes/status', token);
      if (response.status === 'success') {
        setBackupCodes(response.remaining_codes || []);
        setUsedCodes(response.used_codes || []);
      }
    } catch (error) {
      console.error('Failed to load backup codes status:', error);
    }
  };

  const generateNewCodes = async () => {
    if (!confirm('This will invalidate all existing backup codes. Are you sure?')) {
      return;
    }

    setIsGenerating(true);
    setMessage(null);

    try {
      const response = await apiClient.post('/api/auth/2fa/backup-codes/regenerate', {}, token);
      if (response.status === 'success') {
        setBackupCodes(response.backup_codes);
        setUsedCodes([]);
        setShowCodes(true);
        setMessage({ type: 'success', text: 'New backup codes generated successfully' });
      }
    } catch (error: any) {
      setMessage({ type: 'error', text: error.detail || 'Failed to generate new codes' });
    } finally {
      setIsGenerating(false);
    }
  };

  const copyCode = (code: string) => {
    navigator.clipboard.writeText(code);
    setCopiedCode(code);
    setTimeout(() => setCopiedCode(null), 2000);
  };

  const downloadCodes = () => {
    const content = `YetAI 2FA Backup Codes
Generated: ${new Date().toLocaleString()}

IMPORTANT: Store these codes in a safe place!
Each code can only be used once.

Codes:
${backupCodes.map((code, i) => `${i + 1}. ${code}`).join('\n')}

Keep these codes secure and do not share them with anyone.
`;

    const blob = new Blob([content], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'yetai-2fa-backup-codes.txt';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const emailCodes = async () => {
    setMessage(null);
    
    try {
      const response = await apiClient.post('/api/auth/2fa/backup-codes/email', {}, token);
      if (response.status === 'success') {
        setEmailSent(true);
        setMessage({ type: 'success', text: 'Backup codes sent to your email' });
      }
    } catch (error: any) {
      setMessage({ type: 'error', text: error.detail || 'Failed to email backup codes' });
    }
  };

  if (loading) {
    return (
      <Layout>
        <div className="min-h-screen flex items-center justify-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
        </div>
      </Layout>
    );
  }

  if (!isAuthenticated || !user?.totp_enabled) {
    return null;
  }

  return (
    <Layout>
      <div className="max-w-4xl mx-auto space-y-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <Shield className="w-8 h-8 text-blue-600" />
            <h1 className="text-2xl font-bold text-gray-900">2FA Recovery Codes</h1>
          </div>
          <button
            onClick={() => router.push('/settings')}
            className="flex items-center text-gray-600 hover:text-gray-900"
          >
            <ArrowLeft className="w-4 h-4 mr-2" />
            Back to Settings
          </button>
        </div>

        {message && (
          <div className={`rounded-lg p-4 ${
            message.type === 'success' ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800'
          }`}>
            <div className="flex items-center">
              {message.type === 'success' ? (
                <Check className="w-5 h-5 mr-2" />
              ) : (
                <AlertCircle className="w-5 h-5 mr-2" />
              )}
              {message.text}
            </div>
          </div>
        )}

        {/* Status Card */}
        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">Recovery Code Status</h2>
          
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
            <div className="bg-gray-50 rounded-lg p-4">
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-600">Remaining Codes</span>
                <span className="text-2xl font-bold text-gray-900">{backupCodes.length}</span>
              </div>
            </div>
            
            <div className="bg-gray-50 rounded-lg p-4">
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-600">Used Codes</span>
                <span className="text-2xl font-bold text-gray-500">{usedCodes.length}</span>
              </div>
            </div>
            
            <div className="bg-gray-50 rounded-lg p-4">
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-600">Total Generated</span>
                <span className="text-2xl font-bold text-gray-900">
                  {backupCodes.length + usedCodes.length}
                </span>
              </div>
            </div>
          </div>

          {backupCodes.length < 3 && (
            <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 mb-6">
              <div className="flex items-start">
                <AlertCircle className="w-5 h-5 text-yellow-600 mr-2 flex-shrink-0 mt-0.5" />
                <div>
                  <p className="text-yellow-800 font-medium">Low on backup codes</p>
                  <p className="text-yellow-700 text-sm mt-1">
                    You have only {backupCodes.length} backup {backupCodes.length === 1 ? 'code' : 'codes'} remaining. 
                    Consider generating new codes to ensure account recovery access.
                  </p>
                </div>
              </div>
            </div>
          )}

          <div className="flex flex-wrap gap-3">
            <button
              onClick={generateNewCodes}
              disabled={isGenerating}
              className="flex items-center px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              {isGenerating ? (
                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>
              ) : (
                <RefreshCw className="w-4 h-4 mr-2" />
              )}
              Generate New Codes
            </button>

            {backupCodes.length > 0 && (
              <>
                <button
                  onClick={() => setShowCodes(!showCodes)}
                  className="flex items-center px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50"
                >
                  <Key className="w-4 h-4 mr-2" />
                  {showCodes ? 'Hide' : 'Show'} Current Codes
                </button>

                <button
                  onClick={downloadCodes}
                  className="flex items-center px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50"
                >
                  <Download className="w-4 h-4 mr-2" />
                  Download Codes
                </button>

                <button
                  onClick={emailCodes}
                  disabled={emailSent}
                  className="flex items-center px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50"
                >
                  <Mail className="w-4 h-4 mr-2" />
                  {emailSent ? 'Sent to Email' : 'Email Codes'}
                </button>
              </>
            )}
          </div>
        </div>

        {/* Current Codes Display */}
        {showCodes && backupCodes.length > 0 && (
          <div className="bg-white rounded-lg border border-gray-200 p-6">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">Your Backup Codes</h2>
            
            <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 mb-6">
              <div className="flex items-start">
                <AlertCircle className="w-5 h-5 text-yellow-600 mr-2 flex-shrink-0 mt-0.5" />
                <div className="text-sm text-yellow-800">
                  <p className="font-medium mb-1">Important Security Information:</p>
                  <ul className="list-disc list-inside space-y-1">
                    <li>Each code can only be used once</li>
                    <li>Store these codes in a secure location</li>
                    <li>Do not share these codes with anyone</li>
                    <li>Use these codes if you lose access to your authenticator app</li>
                  </ul>
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {backupCodes.map((code, index) => (
                <div
                  key={index}
                  className="flex items-center justify-between bg-gray-50 rounded-lg p-3 font-mono"
                >
                  <span className="text-sm">{code}</span>
                  <button
                    onClick={() => copyCode(code)}
                    className="ml-2 p-1 hover:bg-gray-200 rounded"
                    title="Copy code"
                  >
                    {copiedCode === code ? (
                      <Check className="w-4 h-4 text-green-600" />
                    ) : (
                      <Copy className="w-4 h-4 text-gray-600" />
                    )}
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Used Codes Display */}
        {usedCodes.length > 0 && (
          <div className="bg-white rounded-lg border border-gray-200 p-6">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">Used Codes</h2>
            <p className="text-sm text-gray-600 mb-4">
              These codes have already been used and cannot be used again.
            </p>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {usedCodes.map((code, index) => (
                <div
                  key={index}
                  className="flex items-center bg-gray-100 rounded-lg p-3 font-mono opacity-50"
                >
                  <span className="text-sm line-through">{code}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </Layout>
  );
}