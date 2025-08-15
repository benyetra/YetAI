'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Layout from '@/components/Layout';
import { useAuth } from '@/components/Auth';
import { MessageCircle, Send, Bot, User, Users } from 'lucide-react';

export default function ChatPage() {
  const { isAuthenticated, loading } = useAuth();
  const router = useRouter();
  const [message, setMessage] = useState('');

  useEffect(() => {
    if (!loading && !isAuthenticated) {
      router.push('/?login=true');
    }
  }, [isAuthenticated, loading, router]);

  if (loading) {
    return (
      <Layout>
        <div className="min-h-screen flex items-center justify-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
        </div>
      </Layout>
    );
  }

  if (!isAuthenticated) {
    return null;
  }

  const handleSendMessage = () => {
    if (message.trim()) {
      setMessage('');
    }
  };

  return (
    <Layout requiresAuth>
      <div className="h-[calc(100vh-8rem)] flex flex-col">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-3xl font-bold text-gray-900">Chat & Community</h1>
          <div className="flex items-center space-x-2 text-sm text-gray-500">
            <Users className="w-4 h-4" />
            <span>1,247 online</span>
          </div>
        </div>

        <div className="flex-1 grid grid-cols-1 lg:grid-cols-4 gap-6">
          <div className="lg:col-span-1 bg-white rounded-lg border border-gray-200 p-4">
            <h3 className="font-semibold mb-4">Channels</h3>
            <div className="space-y-2">
              <div className="p-2 bg-blue-50 border border-blue-200 rounded cursor-pointer">
                <div className="flex items-center">
                  <MessageCircle className="w-4 h-4 text-blue-600 mr-2" />
                  <span className="text-sm font-medium">General</span>
                </div>
              </div>
              <div className="p-2 hover:bg-gray-50 rounded cursor-pointer">
                <div className="flex items-center">
                  <MessageCircle className="w-4 h-4 text-gray-500 mr-2" />
                  <span className="text-sm">NFL Discussion</span>
                </div>
              </div>
              <div className="p-2 hover:bg-gray-50 rounded cursor-pointer">
                <div className="flex items-center">
                  <MessageCircle className="w-4 h-4 text-gray-500 mr-2" />
                  <span className="text-sm">NBA Talk</span>
                </div>
              </div>
              <div className="p-2 hover:bg-gray-50 rounded cursor-pointer">
                <div className="flex items-center">
                  <Bot className="w-4 h-4 text-purple-600 mr-2" />
                  <span className="text-sm">AI Assistant</span>
                </div>
              </div>
            </div>
          </div>

          <div className="lg:col-span-3 bg-white rounded-lg border border-gray-200 flex flex-col">
            <div className="p-4 border-b border-gray-200">
              <div className="flex items-center">
                <MessageCircle className="w-5 h-5 text-blue-600 mr-2" />
                <h3 className="font-semibold">General Chat</h3>
              </div>
            </div>

            <div className="flex-1 p-4 overflow-y-auto">
              <div className="space-y-4">
                <div className="flex items-start space-x-3">
                  <div className="w-8 h-8 bg-blue-100 rounded-full flex items-center justify-center">
                    <Bot className="w-5 h-5 text-blue-600" />
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center space-x-2 mb-1">
                      <span className="font-medium text-sm">AI Assistant</span>
                      <span className="text-xs text-gray-500">just now</span>
                    </div>
                    <p className="text-sm text-gray-700">
                      Welcome to the YetAI community! I'm here to help with betting insights and answer questions.
                    </p>
                  </div>
                </div>

                <div className="text-center py-8 text-gray-500">
                  <MessageCircle className="w-12 h-12 mx-auto mb-4 text-gray-300" />
                  <p>Chat feature coming soon</p>
                  <p className="text-sm">Connect with other bettors and get AI assistance</p>
                </div>
              </div>
            </div>

            <div className="p-4 border-t border-gray-200">
              <div className="flex space-x-2">
                <input
                  type="text"
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  placeholder="Type your message..."
                  className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  onKeyPress={(e) => e.key === 'Enter' && handleSendMessage()}
                />
                <button
                  onClick={handleSendMessage}
                  className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
                >
                  <Send className="w-4 h-4" />
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Layout>
  );
}