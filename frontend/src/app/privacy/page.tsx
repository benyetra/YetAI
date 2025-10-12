'use client';

import React from 'react';
import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';

export default function PrivacyPolicy() {
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
            <h1 className="text-4xl font-bold text-gray-900">Privacy Policy</h1>
          </div>
          <p className="text-gray-600">Last Updated: January 2025</p>
        </div>

        {/* Content */}
        <div className="bg-white rounded-2xl shadow-lg p-8 space-y-8">
          <section>
            <h2 className="text-2xl font-bold text-gray-900 mb-4">1. Introduction</h2>
            <p className="text-gray-700 leading-relaxed">
              YetAI ("we," "our," or "us") is committed to protecting your privacy. This Privacy Policy explains how we collect, use, disclose, and safeguard your information when you use our Platform. Please read this policy carefully to understand our practices regarding your personal data.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-bold text-gray-900 mb-4">2. Information We Collect</h2>

            <h3 className="text-xl font-semibold text-gray-900 mb-3 mt-4">2.1 Personal Information</h3>
            <p className="text-gray-700 leading-relaxed mb-3">
              We collect personal information that you provide directly to us, including:
            </p>
            <ul className="list-disc list-inside text-gray-700 space-y-2 ml-4">
              <li>Name, email address, and username</li>
              <li>Date of birth and location (for age and jurisdiction verification)</li>
              <li>Payment information (processed through secure third-party providers)</li>
              <li>Government-issued ID for identity verification</li>
              <li>Contact information and support communications</li>
            </ul>

            <h3 className="text-xl font-semibold text-gray-900 mb-3 mt-6">2.2 Betting and Platform Activity</h3>
            <p className="text-gray-700 leading-relaxed mb-3">
              We automatically collect information about your use of the Platform:
            </p>
            <ul className="list-disc list-inside text-gray-700 space-y-2 ml-4">
              <li>Betting history, preferences, and patterns</li>
              <li>Account balance and transaction history</li>
              <li>AI recommendation views and interactions</li>
              <li>Platform usage data and feature interactions</li>
            </ul>

            <h3 className="text-xl font-semibold text-gray-900 mb-3 mt-6">2.3 Technical Information</h3>
            <p className="text-gray-700 leading-relaxed mb-3">
              We collect technical data about your device and connection:
            </p>
            <ul className="list-disc list-inside text-gray-700 space-y-2 ml-4">
              <li>IP address and geolocation data</li>
              <li>Device type, operating system, and browser information</li>
              <li>Cookies and similar tracking technologies</li>
              <li>Log files and usage statistics</li>
            </ul>
          </section>

          <section>
            <h2 className="text-2xl font-bold text-gray-900 mb-4">3. How We Use Your Information</h2>
            <p className="text-gray-700 leading-relaxed mb-3">
              We use your information for the following purposes:
            </p>
            <ul className="list-disc list-inside text-gray-700 space-y-2 ml-4">
              <li><strong>Account Management:</strong> Create and manage your account, verify your identity and age</li>
              <li><strong>Platform Services:</strong> Process bets, calculate winnings, provide AI recommendations</li>
              <li><strong>Payments:</strong> Process deposits, withdrawals, and financial transactions</li>
              <li><strong>Personalization:</strong> Customize your experience and provide relevant recommendations</li>
              <li><strong>AI Training:</strong> Improve our AI models using anonymized betting data and patterns</li>
              <li><strong>Communications:</strong> Send account updates, promotional offers, and customer support messages</li>
              <li><strong>Compliance:</strong> Comply with legal obligations, prevent fraud, and ensure responsible gaming</li>
              <li><strong>Analytics:</strong> Analyze Platform performance and user behavior to improve our services</li>
            </ul>
          </section>

          <section>
            <h2 className="text-2xl font-bold text-gray-900 mb-4">4. AI and Data Processing</h2>
            <p className="text-gray-700 leading-relaxed mb-3">
              YetAI uses artificial intelligence to provide betting recommendations. Our AI systems:
            </p>
            <ul className="list-disc list-inside text-gray-700 space-y-2 ml-4">
              <li>Analyze historical sports data, statistics, and betting patterns</li>
              <li>Use anonymized user betting data to improve prediction accuracy</li>
              <li>Do not share individual user betting decisions with third parties</li>
              <li>Are continuously trained to enhance recommendation quality</li>
            </ul>
            <p className="text-gray-700 leading-relaxed mt-3">
              Your individual betting decisions are kept private and are only used in aggregate, anonymized form for AI training purposes.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-bold text-gray-900 mb-4">5. Information Sharing and Disclosure</h2>
            <p className="text-gray-700 leading-relaxed mb-3">
              We may share your information with:
            </p>
            <ul className="list-disc list-inside text-gray-700 space-y-2 ml-4">
              <li><strong>Service Providers:</strong> Payment processors, identity verification services, cloud hosting providers</li>
              <li><strong>Legal Authorities:</strong> When required by law, court order, or regulatory request</li>
              <li><strong>Business Transfers:</strong> In connection with mergers, acquisitions, or asset sales</li>
              <li><strong>Fraud Prevention:</strong> With fraud detection services to protect against illegal activity</li>
            </ul>
            <p className="text-gray-700 leading-relaxed mt-3">
              We do not sell your personal information to third parties for marketing purposes.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-bold text-gray-900 mb-4">6. Data Security</h2>
            <p className="text-gray-700 leading-relaxed mb-3">
              We implement industry-standard security measures to protect your information:
            </p>
            <ul className="list-disc list-inside text-gray-700 space-y-2 ml-4">
              <li>Encryption of data in transit and at rest (SSL/TLS, AES-256)</li>
              <li>Secure authentication and password hashing</li>
              <li>Regular security audits and penetration testing</li>
              <li>Access controls and employee training</li>
              <li>Automated monitoring for suspicious activity</li>
            </ul>
            <p className="text-gray-700 leading-relaxed mt-3">
              However, no method of transmission over the internet is 100% secure. We cannot guarantee absolute security but continuously work to protect your data.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-bold text-gray-900 mb-4">7. Your Privacy Rights</h2>
            <p className="text-gray-700 leading-relaxed mb-3">
              Depending on your location, you may have the following rights:
            </p>
            <ul className="list-disc list-inside text-gray-700 space-y-2 ml-4">
              <li><strong>Access:</strong> Request a copy of your personal data</li>
              <li><strong>Correction:</strong> Update inaccurate or incomplete information</li>
              <li><strong>Deletion:</strong> Request deletion of your personal data (subject to legal retention requirements)</li>
              <li><strong>Portability:</strong> Receive your data in a structured, machine-readable format</li>
              <li><strong>Opt-Out:</strong> Unsubscribe from marketing communications</li>
              <li><strong>Restriction:</strong> Limit how we use your data</li>
            </ul>
            <p className="text-gray-700 leading-relaxed mt-3">
              To exercise these rights, contact us at privacy@yetai.com. We will respond within 30 days.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-bold text-gray-900 mb-4">8. Cookies and Tracking Technologies</h2>
            <p className="text-gray-700 leading-relaxed mb-3">
              We use cookies and similar technologies to:
            </p>
            <ul className="list-disc list-inside text-gray-700 space-y-2 ml-4">
              <li>Maintain your session and keep you logged in</li>
              <li>Remember your preferences and settings</li>
              <li>Analyze Platform performance and user behavior</li>
              <li>Provide personalized content and recommendations</li>
            </ul>
            <p className="text-gray-700 leading-relaxed mt-3">
              You can control cookies through your browser settings, but disabling cookies may affect Platform functionality.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-bold text-gray-900 mb-4">9. Data Retention</h2>
            <p className="text-gray-700 leading-relaxed">
              We retain your personal information for as long as necessary to provide services and comply with legal obligations. Betting records are retained for at least 7 years for regulatory compliance. After account closure, we may retain certain information for fraud prevention and legal purposes.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-bold text-gray-900 mb-4">10. Children's Privacy</h2>
            <p className="text-gray-700 leading-relaxed">
              YetAI is not intended for individuals under 21 years of age (or the legal gambling age in your jurisdiction). We do not knowingly collect information from minors. If we discover that we have collected information from a minor, we will delete it immediately.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-bold text-gray-900 mb-4">11. International Data Transfers</h2>
            <p className="text-gray-700 leading-relaxed">
              Your information may be transferred to and processed in countries other than your own. We ensure that appropriate safeguards are in place to protect your data in accordance with this Privacy Policy and applicable laws.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-bold text-gray-900 mb-4">12. Third-Party Links</h2>
            <p className="text-gray-700 leading-relaxed">
              The Platform may contain links to third-party websites or services. We are not responsible for the privacy practices of these third parties. We encourage you to review their privacy policies before providing any information.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-bold text-gray-900 mb-4">13. Changes to This Privacy Policy</h2>
            <p className="text-gray-700 leading-relaxed">
              We may update this Privacy Policy from time to time. We will notify you of material changes via email or Platform notification. The "Last Updated" date at the top indicates when the policy was last revised. Continued use of the Platform after changes constitutes acceptance of the updated policy.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-bold text-gray-900 mb-4">14. California Privacy Rights (CCPA)</h2>
            <p className="text-gray-700 leading-relaxed mb-3">
              If you are a California resident, you have additional rights under the California Consumer Privacy Act:
            </p>
            <ul className="list-disc list-inside text-gray-700 space-y-2 ml-4">
              <li>Right to know what personal information we collect and how it's used</li>
              <li>Right to delete your personal information</li>
              <li>Right to opt-out of the sale of personal information (we do not sell your data)</li>
              <li>Right to non-discrimination for exercising your privacy rights</li>
            </ul>
          </section>

          <section>
            <h2 className="text-2xl font-bold text-gray-900 mb-4">15. European Privacy Rights (GDPR)</h2>
            <p className="text-gray-700 leading-relaxed">
              If you are in the European Economic Area (EEA), you have rights under the General Data Protection Regulation (GDPR), including the right to access, correct, delete, and restrict processing of your personal data. You also have the right to lodge a complaint with your local data protection authority.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-bold text-gray-900 mb-4">16. Contact Us</h2>
            <p className="text-gray-700 leading-relaxed">
              If you have questions or concerns about this Privacy Policy or our data practices, please contact us:
            </p>
            <div className="mt-4 text-gray-700">
              <p><strong>Privacy Inquiries:</strong> privacy@yetai.com</p>
              <p><strong>General Support:</strong> support@yetai.com</p>
              <p><strong>Data Protection Officer:</strong> dpo@yetai.com</p>
            </div>
          </section>

          <div className="border-t border-gray-200 pt-6 mt-8">
            <p className="text-sm text-gray-600">
              By using YetAI, you acknowledge that you have read, understood, and agree to the collection and use of your information as described in this Privacy Policy.
            </p>
          </div>
        </div>

        {/* Footer Links */}
        <div className="mt-8 text-center">
          <Link
            href="/terms"
            className="text-purple-600 hover:text-purple-700 mr-6"
          >
            Terms and Conditions
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
