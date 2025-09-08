"use client";

import React, { useState, useEffect } from 'react';
import { TrendingUp, Target, Award, BarChart3, Clock, CheckCircle } from 'lucide-react';

// API client
const api = {
  baseURL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000',
  
  async get(endpoint) {
    try {
      const response = await fetch(`${this.baseURL}${endpoint}`);
      return await response.json();
    } catch (error) {
      console.error(`API Error: ${endpoint}`, error);
      return null;
    }
  },
  
  async post(endpoint, data = {}) {
    try {
      const response = await fetch(`${this.baseURL}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      });
      return await response.json();
    } catch (error) {
      console.error(`API Error: ${endpoint}`, error);
      return null;
    }
  }
};

export default function PerformanceDashboard() {
  const [metrics, setMetrics] = useState(null);
  const [bestPredictions, setBestPredictions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState(null);

  useEffect(() => {
    const fetchPerformanceData = async () => {
      setLoading(true);
      
      // Generate sample data if needed
      await api.post('/api/performance/simulate-data');
      
      // Fetch performance metrics
      const metricsData = await api.get('/api/performance/metrics');
      if (metricsData?.metrics) {
        setMetrics(metricsData.metrics);
      }
      
      // Fetch best predictions
      const bestPredsData = await api.get('/api/performance/best-predictions');
      if (bestPredsData?.best_predictions) {
        setBestPredictions(bestPredsData.best_predictions);
      }
      
      setLastUpdated(new Date().toLocaleTimeString());
      setLoading(false);
    };

    fetchPerformanceData();
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
          <p className="mt-4 text-gray-600">Loading performance data...</p>
        </div>
      </div>
    );
  }

  if (!metrics) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <BarChart3 className="w-16 h-16 text-gray-400 mx-auto mb-4" />
          <h2 className="text-xl font-semibold text-gray-900 mb-2">No Performance Data</h2>
          <p className="text-gray-600">Start making predictions to see performance metrics.</p>
        </div>
      </div>
    );
  }

  // Calculate average confidence from confidence breakdown
  const avgConfidence = (() => {
    const { high_confidence, medium_confidence, low_confidence } = metrics.by_confidence;
    const totalCount = high_confidence.count + medium_confidence.count + low_confidence.count;
    if (totalCount === 0) return 75; // Default fallback
    
    const weightedSum = (high_confidence.count * high_confidence.avg_accuracy) + 
                       (medium_confidence.count * medium_confidence.avg_accuracy) + 
                       (low_confidence.count * low_confidence.avg_accuracy);
    return weightedSum / totalCount;
  })();

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white shadow-sm border-b">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center py-4">
            <div>
              <h1 className="text-2xl font-bold text-gray-900">Prediction Performance</h1>
              <p className="text-sm text-gray-500">
                Track accuracy and improve over time • Updated {lastUpdated}
              </p>
            </div>
            <div className="flex items-center space-x-4">
              <div className="text-right">
                <p className="text-sm text-gray-600">Overall Accuracy</p>
                <p className={`text-2xl font-bold ${
                  metrics.overall_accuracy >= 70 ? 'text-green-600' :
                  metrics.overall_accuracy >= 60 ? 'text-yellow-600' : 'text-red-600'
                }`}>
                  {metrics.overall_accuracy.toFixed(1)}%
                </p>
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        
        {/* Key Metrics Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
          
          {/* Total Predictions */}
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
            <div className="flex items-center">
              <div className="flex-shrink-0">
                <Target className="w-8 h-8 text-blue-600" />
              </div>
              <div className="ml-4">
                <p className="text-sm font-medium text-gray-600">Total Predictions</p>
                <p className="text-2xl font-bold text-gray-900">{metrics.total_predictions}</p>
                <p className="text-sm text-gray-500">{metrics.pending_predictions} pending</p>
              </div>
            </div>
          </div>

          {/* Accuracy Rate */}
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
            <div className="flex items-center">
              <div className="flex-shrink-0">
                <CheckCircle className={`w-8 h-8 ${
                  metrics.overall_accuracy >= 70 ? 'text-green-600' :
                  metrics.overall_accuracy >= 60 ? 'text-yellow-600' : 'text-red-600'
                }`} />
              </div>
              <div className="ml-4">
                <p className="text-sm font-medium text-gray-600">Accuracy Rate</p>
                <p className="text-2xl font-bold text-gray-900">{metrics.overall_accuracy.toFixed(1)}%</p>
                <p className="text-sm text-gray-500">
                  {metrics.resolved_predictions} completed
                </p>
              </div>
            </div>
          </div>

          {/* Success Rate */}
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
            <div className="flex items-center">
              <div className="flex-shrink-0">
                <TrendingUp className="w-8 h-8 text-purple-600" />
              </div>
              <div className="ml-4">
                <p className="text-sm font-medium text-gray-600">Success Rate</p>
                <p className="text-2xl font-bold text-gray-900">{(metrics.success_rate * 100).toFixed(1)}%</p>
                <p className="text-sm text-gray-500">above 70% accuracy</p>
              </div>
            </div>
          </div>

          {/* Recent Performance */}
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
            <div className="flex items-center">
              <div className="flex-shrink-0">
                <Clock className="w-8 h-8 text-orange-600" />
              </div>
              <div className="ml-4">
                <p className="text-sm font-medium text-gray-600">Last 7 Days</p>
                <p className="text-2xl font-bold text-gray-900">
                  {metrics.trends.last_7_days_accuracy.toFixed(1)}%
                </p>
                <p className={`text-sm font-medium ${
                  metrics.trends.improvement_trend === 'improving' ? 'text-green-600' : 
                  metrics.trends.improvement_trend === 'stable' ? 'text-blue-600' : 'text-red-600'
                }`}>
                  {metrics.trends.improvement_trend}
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Performance Breakdown */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 mb-8">
          
          {/* By Category */}
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">Performance by Category</h3>
            <div className="space-y-4">
              
              {/* Fantasy Performance */}
              {metrics.by_type.fantasy && (
                <div className="border border-gray-200 rounded-lg p-4">
                  <div className="flex justify-between items-center mb-2">
                    <h4 className="font-medium text-gray-900">Fantasy Projections</h4>
                    <span className="text-sm text-gray-500">{metrics.by_type.fantasy.count} predictions</span>
                  </div>
                  <div className="w-full bg-gray-200 rounded-full h-2 mb-2">
                    <div 
                      className="bg-blue-600 h-2 rounded-full" 
                      style={{ width: `${Math.min(100, metrics.by_type.fantasy.avg_accuracy)}%` }}
                    ></div>
                  </div>
                  <div className="flex justify-between text-sm">
                    <span className="text-gray-600">
                      {metrics.by_type.fantasy.avg_accuracy.toFixed(1)}% accuracy
                    </span>
                    <span className="text-gray-600">
                      {(metrics.by_type.fantasy.success_rate * 100).toFixed(1)}% success rate
                    </span>
                  </div>
                </div>
              )}

              {/* Betting Performance */}
              {metrics.by_type.betting && (
                <div className="border border-gray-200 rounded-lg p-4">
                  <div className="flex justify-between items-center mb-2">
                    <h4 className="font-medium text-gray-900">Betting Predictions</h4>
                    <span className="text-sm text-gray-500">{metrics.by_type.betting.count} predictions</span>
                  </div>
                  <div className="w-full bg-gray-200 rounded-full h-2 mb-2">
                    <div 
                      className="bg-green-600 h-2 rounded-full" 
                      style={{ width: `${Math.min(100, metrics.by_type.betting.avg_accuracy)}%` }}
                    ></div>
                  </div>
                  <div className="flex justify-between text-sm">
                    <span className="text-gray-600">
                      {metrics.by_type.betting.avg_accuracy.toFixed(1)}% accuracy
                    </span>
                    <span className="text-gray-600">
                      {(metrics.by_type.betting.success_rate * 100).toFixed(1)}% success rate
                    </span>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Confidence Analysis */}
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">Confidence Analysis</h3>
            <div className="space-y-4">
              
              {/* High Confidence */}
              <div className="border border-gray-200 rounded-lg p-4">
                <div className="flex justify-between items-center mb-2">
                  <h4 className="font-medium text-gray-900">High Confidence (80%+)</h4>
                  <span className="text-sm text-gray-500">{metrics.by_confidence.high_confidence.count} predictions</span>
                </div>
                <div className="w-full bg-gray-200 rounded-full h-2 mb-2">
                  <div 
                    className="bg-green-600 h-2 rounded-full" 
                    style={{ width: `${Math.min(100, metrics.by_confidence.high_confidence.avg_accuracy)}%` }}
                  ></div>
                </div>
                <p className="text-sm text-gray-600">
                  {metrics.by_confidence.high_confidence.avg_accuracy.toFixed(1)}% accuracy
                </p>
              </div>

              {/* Medium Confidence */}
              <div className="border border-gray-200 rounded-lg p-4">
                <div className="flex justify-between items-center mb-2">
                  <h4 className="font-medium text-gray-900">Medium Confidence (60-80%)</h4>
                  <span className="text-sm text-gray-500">{metrics.by_confidence.medium_confidence.count} predictions</span>
                </div>
                <div className="w-full bg-gray-200 rounded-full h-2 mb-2">
                  <div 
                    className="bg-yellow-600 h-2 rounded-full" 
                    style={{ width: `${Math.min(100, metrics.by_confidence.medium_confidence.avg_accuracy)}%` }}
                  ></div>
                </div>
                <p className="text-sm text-gray-600">
                  {metrics.by_confidence.medium_confidence.avg_accuracy.toFixed(1)}% accuracy
                </p>
              </div>

              {/* Low Confidence */}
              {metrics.by_confidence.low_confidence.count > 0 && (
                <div className="border border-gray-200 rounded-lg p-4">
                  <div className="flex justify-between items-center mb-2">
                    <h4 className="font-medium text-gray-900">Low Confidence (&lt;60%)</h4>
                    <span className="text-sm text-gray-500">{metrics.by_confidence.low_confidence.count} predictions</span>
                  </div>
                  <div className="w-full bg-gray-200 rounded-full h-2 mb-2">
                    <div 
                      className="bg-red-600 h-2 rounded-full" 
                      style={{ width: `${Math.min(100, metrics.by_confidence.low_confidence.avg_accuracy)}%` }}
                    ></div>
                  </div>
                  <p className="text-sm text-gray-600">
                    {metrics.by_confidence.low_confidence.avg_accuracy.toFixed(1)}% accuracy
                  </p>
                </div>
              )}

              {/* Key Insights */}
              <div className="border-l-4 border-blue-500 pl-4 mt-4">
                <h4 className="font-medium text-gray-900">Calibration Insight</h4>
                <p className="text-sm text-gray-600 mt-1">
                  {metrics.by_confidence.high_confidence.avg_accuracy > metrics.by_confidence.medium_confidence.avg_accuracy 
                    ? 'Your confidence levels are well-calibrated with higher confidence predictions performing better.' 
                    : 'Consider reviewing confidence scoring as higher confidence predictions aren\'t significantly more accurate.'}
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Best Predictions */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200">
          <div className="px-6 py-4 border-b border-gray-200">
            <div className="flex items-center">
              <Award className="w-5 h-5 text-yellow-600 mr-2" />
              <h3 className="text-lg font-semibold text-gray-900">Most Accurate Predictions</h3>
            </div>
          </div>
          
          <div className="p-6">
            {bestPredictions.length === 0 ? (
              <p className="text-gray-500 text-center py-8">
                No completed predictions yet. Check back after games are finished!
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full">
                  <thead>
                    <tr className="border-b border-gray-200">
                      <th className="text-left py-3 px-4 font-medium text-gray-600">Player</th>
                      <th className="text-left py-3 px-4 font-medium text-gray-600">Position</th>
                      <th className="text-left py-3 px-4 font-medium text-gray-600">Predicted</th>
                      <th className="text-left py-3 px-4 font-medium text-gray-600">Actual</th>
                      <th className="text-left py-3 px-4 font-medium text-gray-600">Accuracy</th>
                      <th className="text-left py-3 px-4 font-medium text-gray-600">Date</th>
                    </tr>
                  </thead>
                  <tbody>
                    {bestPredictions.map((pred, idx) => (
                      <tr key={idx} className="border-b border-gray-100">
                        <td className="py-3 px-4">
                          <div>
                            <p className="font-medium text-gray-900">{pred.name}</p>
                            <p className="text-sm text-gray-500">{pred.team} vs {pred.opponent}</p>
                          </div>
                        </td>
                        <td className="py-3 px-4">
                          <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                            pred.position === 'QB' ? 'bg-red-100 text-red-800' :
                            pred.position === 'RB' ? 'bg-green-100 text-green-800' :
                            pred.position === 'WR' ? 'bg-blue-100 text-blue-800' :
                            pred.position === 'TE' ? 'bg-yellow-100 text-yellow-800' :
                            'bg-gray-100 text-gray-800'
                          }`}>
                            {pred.position}
                          </span>
                        </td>
                        <td className="py-3 px-4 font-medium text-gray-900">
                          {pred.predicted_points.toFixed(1)} pts
                        </td>
                        <td className="py-3 px-4 font-medium text-gray-900">
                          {pred.actual_points.toFixed(1)} pts
                        </td>
                        <td className="py-3 px-4">
                          <span className="text-green-600 font-medium">
                            {pred.accuracy_score.toFixed(1)}%
                          </span>
                          <p className="text-xs text-gray-500">
                            {pred.confidence}% confidence
                          </p>
                        </td>
                        <td className="py-3 px-4 text-sm text-gray-500">
                          {new Date(pred.game_date).toLocaleDateString()}
                          <p className="text-xs text-gray-400">{pred.days_ago} days ago</p>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="bg-white border-t border-gray-200 mt-12">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <p className="text-sm text-gray-500 text-center">
            Performance tracking helps improve prediction accuracy over time. 
            Historical data shows model effectiveness and areas for improvement.
          </p>
        </div>
      </footer>
    </div>
  );
}