'use client';

import React from 'react';
import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';

export default function TermsAndConditions() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-purple-50 to-white">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
        {/* Back Button */}
        <Link
          href="/signup"
          className="inline-flex items-center text-purple-600 hover:text-purple-700 mb-8"
        >
          <ArrowLeft className="w-4 h-4 mr-2" />
          Back to Sign Up
        </Link>

        {/* Header */}
        <div className="mb-12">
          <div className="flex items-center mb-4">
            <img
              src="/logo.png"
              alt="YetAI Logo"
              className="w-12 h-12 mr-4"
            />
            <h1 className="text-4xl font-bold text-gray-900">Terms and Conditions</h1>
          </div>
          <p className="text-gray-600">Last Updated: January 2025</p>
        </div>

        {/* Content */}
        <div className="bg-white rounded-2xl shadow-lg p-8 space-y-8">
          <section>
            <h2 className="text-2xl font-bold text-gray-900 mb-4">1. Acceptance of Terms</h2>
            <p className="text-gray-700 leading-relaxed">
              By accessing and using YetAI ("the Platform"), you accept and agree to be bound by the terms and provisions of this agreement. If you do not agree to these Terms and Conditions, please do not use the Platform.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-bold text-gray-900 mb-4">2. Eligibility</h2>
            <p className="text-gray-700 leading-relaxed mb-3">
              To use YetAI, you must:
            </p>
            <ul className="list-disc list-inside text-gray-700 space-y-2 ml-4">
              <li>Be at least 21 years of age or the legal gambling age in your jurisdiction, whichever is higher</li>
              <li>Be located in a jurisdiction where sports betting is legal</li>
              <li>Provide accurate and complete registration information</li>
              <li>Maintain the security of your account credentials</li>
            </ul>
          </section>

          <section>
            <h2 className="text-2xl font-bold text-gray-900 mb-4">3. AI-Powered Betting Recommendations</h2>
            <p className="text-gray-700 leading-relaxed mb-3">
              YetAI provides AI-powered betting recommendations and analysis. You acknowledge and agree that:
            </p>
            <ul className="list-disc list-inside text-gray-700 space-y-2 ml-4">
              <li>All recommendations are for informational purposes only and do not guarantee wins</li>
              <li>Past performance does not indicate future results</li>
              <li>You are solely responsible for all betting decisions made using the Platform</li>
              <li>YetAI is not liable for any losses incurred from following recommendations</li>
              <li>Sports betting involves risk, and you should only bet what you can afford to lose</li>
            </ul>
          </section>

          <section>
            <h2 className="text-2xl font-bold text-gray-900 mb-4">4. Account Management</h2>
            <p className="text-gray-700 leading-relaxed mb-3">
              As a YetAI user, you agree to:
            </p>
            <ul className="list-disc list-inside text-gray-700 space-y-2 ml-4">
              <li>Maintain accurate account information</li>
              <li>Keep your password secure and confidential</li>
              <li>Notify us immediately of any unauthorized access</li>
              <li>Not share your account with others</li>
              <li>Not create multiple accounts</li>
            </ul>
          </section>

          <section>
            <h2 className="text-2xl font-bold text-gray-900 mb-4">5. Betting Limits and Responsible Gaming</h2>
            <p className="text-gray-700 leading-relaxed mb-3">
              YetAI promotes responsible gaming. You can:
            </p>
            <ul className="list-disc list-inside text-gray-700 space-y-2 ml-4">
              <li>Set daily, weekly, and monthly betting limits</li>
              <li>Self-exclude from the Platform if needed</li>
              <li>Access resources for problem gambling support</li>
            </ul>
            <p className="text-gray-700 leading-relaxed mt-3">
              If you or someone you know has a gambling problem, call 1-800-GAMBLER for help.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-bold text-gray-900 mb-4">6. Payments and Withdrawals</h2>
            <p className="text-gray-700 leading-relaxed mb-3">
              All financial transactions are subject to:
            </p>
            <ul className="list-disc list-inside text-gray-700 space-y-2 ml-4">
              <li>Identity verification requirements</li>
              <li>Processing times as specified in our payment methods</li>
              <li>Minimum and maximum deposit/withdrawal limits</li>
              <li>Applicable fees and charges</li>
            </ul>
          </section>

          <section>
            <h2 className="text-2xl font-bold text-gray-900 mb-4">7. Bet Settlement</h2>
            <p className="text-gray-700 leading-relaxed">
              All bets are settled based on official results from our data providers. YetAI reserves the right to void bets in cases of obvious errors, technical issues, or fraudulent activity.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-bold text-gray-900 mb-4">8. Intellectual Property</h2>
            <p className="text-gray-700 leading-relaxed">
              All content on YetAI, including but not limited to text, graphics, logos, AI models, and software, is the property of YetAI and is protected by copyright and trademark laws. You may not reproduce, distribute, or create derivative works without our express written permission.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-bold text-gray-900 mb-4">9. Prohibited Activities</h2>
            <p className="text-gray-700 leading-relaxed mb-3">
              You agree not to:
            </p>
            <ul className="list-disc list-inside text-gray-700 space-y-2 ml-4">
              <li>Use the Platform for illegal purposes</li>
              <li>Attempt to manipulate or exploit the Platform</li>
              <li>Use bots, scripts, or automated tools</li>
              <li>Engage in collusion or fraudulent betting</li>
              <li>Harass or abuse other users or staff</li>
              <li>Reverse engineer or attempt to access our AI models</li>
            </ul>
          </section>

          <section>
            <h2 className="text-2xl font-bold text-gray-900 mb-4">10. Account Suspension and Termination</h2>
            <p className="text-gray-700 leading-relaxed">
              YetAI reserves the right to suspend or terminate your account at any time for violation of these Terms, fraudulent activity, or at our sole discretion. Upon termination, any remaining account balance will be returned to you, subject to verification.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-bold text-gray-900 mb-4">11. Limitation of Liability</h2>
            <p className="text-gray-700 leading-relaxed">
              YetAI and its affiliates are not liable for any direct, indirect, incidental, consequential, or punitive damages arising from your use of the Platform. This includes but is not limited to losses from betting, technical issues, data breaches, or service interruptions.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-bold text-gray-900 mb-4">12. Dispute Resolution</h2>
            <p className="text-gray-700 leading-relaxed">
              Any disputes arising from these Terms will be resolved through binding arbitration in accordance with the rules of the American Arbitration Association. You waive your right to participate in class action lawsuits.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-bold text-gray-900 mb-4">13. Changes to Terms</h2>
            <p className="text-gray-700 leading-relaxed">
              YetAI reserves the right to modify these Terms at any time. We will notify users of material changes via email or Platform notification. Continued use of the Platform after changes constitutes acceptance of the new Terms.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-bold text-gray-900 mb-4">14. Governing Law</h2>
            <p className="text-gray-700 leading-relaxed">
              These Terms are governed by the laws of the United States and the state in which YetAI is registered, without regard to conflict of law principles.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-bold text-gray-900 mb-4">15. Contact Information</h2>
            <p className="text-gray-700 leading-relaxed">
              For questions about these Terms and Conditions, please contact us at:
            </p>
            <div className="mt-4 text-gray-700">
              <p>Email: legal@yetai.com</p>
              <p>Support: support@yetai.com</p>
            </div>
          </section>

          <div className="border-t border-gray-200 pt-6 mt-8">
            <p className="text-sm text-gray-600">
              By using YetAI, you acknowledge that you have read, understood, and agree to be bound by these Terms and Conditions.
            </p>
          </div>
        </div>

        {/* Footer Links */}
        <div className="mt-8 text-center">
          <Link
            href="/privacy"
            className="text-purple-600 hover:text-purple-700 mr-6"
          >
            Privacy Policy
          </Link>
          <Link
            href="/signup"
            className="text-purple-600 hover:text-purple-700"
          >
            Back to Sign Up
          </Link>
        </div>
      </div>
    </div>
  );
}
