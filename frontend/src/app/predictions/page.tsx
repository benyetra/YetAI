'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Layout from '@/components/Layout';
import { useAuth } from '@/components/Auth';
import { Brain, TrendingUp, Target, Clock } from 'lucide-react';

export default function PredictionsPage() {
  const { isAuthenticated, loading } = useAuth();
  const router = useRouter();

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

  return (
    <Layout requiresAuth>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-3xl font-bold text-gray-900">AI Predictions</h1>
          <div className="flex items-center space-x-2 text-sm text-gray-500">
            <Clock className="w-4 h-4" />
            <span>Updated 5 minutes ago</span>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
          <div className="bg-white p-6 rounded-lg border border-gray-200">
            <div className="flex items-center justify-between mb-4">
              <Brain className="w-8 h-8 text-blue-600" />
              <span className="text-2xl font-bold text-green-600">87%</span>
            </div>
            <h3 className="font-semibold text-gray-900">Accuracy Rate</h3>
            <p className="text-sm text-gray-600">Last 30 days</p>
          </div>
          
          <div className="bg-white p-6 rounded-lg border border-gray-200">
            <div className="flex items-center justify-between mb-4">
              <TrendingUp className="w-8 h-8 text-green-600" />
              <span className="text-2xl font-bold text-blue-600">156</span>
            </div>
            <h3 className="font-semibold text-gray-900">Predictions Made</h3>
            <p className="text-sm text-gray-600">This week</p>
          </div>

          <div className="bg-white p-6 rounded-lg border border-gray-200">
            <div className="flex items-center justify-between mb-4">
              <Target className="w-8 h-8 text-purple-600" />
              <span className="text-2xl font-bold text-purple-600">23</span>
            </div>
            <h3 className="font-semibold text-gray-900">Hot Picks</h3>
            <p className="text-sm text-gray-600">High confidence</p>
          </div>
        </div>

        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <h2 className="text-xl font-semibold mb-4">Today's Predictions</h2>
          <div className="text-center py-12 text-gray-500">
            <Brain className="w-12 h-12 mx-auto mb-4 text-gray-300" />
            <p>AI predictions coming soon...</p>
            <p className="text-sm">Our AI models are analyzing today's games</p>
          </div>
        </div>
      </div>
    </Layout>
  );
}