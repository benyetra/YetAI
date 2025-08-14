'use client';

import { useState } from 'react';
import { testAPI } from '@/lib/api';

interface TestResult {
  success: boolean;
  data?: unknown;
  error?: string;
}

interface TestResults {
  [key: string]: TestResult;
}

export default function APITest() {
  const [results, setResults] = useState<TestResults>({});
  const [loading, setLoading] = useState(false);

  const runTests = async () => {
    setLoading(true);
    const testResults: TestResults = {};

    try {
      const health = await testAPI.health();
      testResults.health = { success: true, data: health.data };
    } catch {
      testResults.health = { success: false, error: 'Failed to connect' };
    }

    try {
      const odds = await testAPI.odds();
      testResults.odds = { success: true, data: odds.data };
    } catch {
      testResults.odds = { success: false, error: 'Failed to get odds' };
    }

    try {
      const fantasy = await testAPI.fantasy();
      testResults.fantasy = { success: true, data: fantasy.data };
    } catch {
      testResults.fantasy = { success: false, error: 'Failed to get fantasy data' };
    }

    setResults(testResults);
    setLoading(false);
  };

  return (
    <div className="p-6 max-w-2xl mx-auto">
      <h2 className="text-2xl font-bold mb-4">API Connection Test</h2>
      
      <button
        onClick={runTests}
        disabled={loading}
        className="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600 disabled:opacity-50"
      >
        {loading ? 'Testing...' : 'Test API Connection'}
      </button>

      {Object.keys(results).length > 0 && (
        <div className="mt-6 space-y-4">
          {Object.entries(results).map(([key, result]) => (
            <div key={key} className="border p-4 rounded">
              <h3 className="font-semibold">{key} endpoint:</h3>
              <div className={`mt-2 ${result.success ? 'text-green-600' : 'text-red-600'}`}>
                {result.success ? '✅ Success' : '❌ Failed'}
              </div>
              <pre className="mt-2 text-sm bg-gray-100 p-2 rounded overflow-auto">
                {JSON.stringify(result.data || result.error, null, 2)}
              </pre>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}