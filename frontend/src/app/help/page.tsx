'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Layout from '@/components/Layout';
import { useAuth } from '@/components/Auth';
import { HelpCircle, Search, Book, MessageSquare, Mail, ChevronDown, ChevronRight } from 'lucide-react';

export default function HelpPage() {
  const { isAuthenticated, loading, user } = useAuth();
  const router = useRouter();
  const [searchQuery, setSearchQuery] = useState('');
  const [expandedFaq, setExpandedFaq] = useState<number | null>(null);

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

  const faqs = [
    {
      question: "How do I place my first bet?",
      answer: "To place your first bet, navigate to the 'Odds' or 'Bet' page, select a game, choose your bet type, enter your stake amount, and confirm your bet. Make sure you have funds in your account balance."
    },
    {
      question: "How accurate are the AI predictions?",
      answer: "Our AI predictions have shown an average accuracy rate of 68-75% across different sports. However, remember that sports betting always involves risk, and past performance doesn't guarantee future results."
    },
    {
      question: "How do I withdraw my winnings?",
      answer: "Go to your account settings, select 'Payment Methods', choose your preferred withdrawal method, and follow the instructions. Withdrawals typically take 1-3 business days to process."
    },
    {
      question: "What sports are available for betting?",
      answer: "We currently support NFL, NBA, MLB, and NHL. We're continuously working to add more sports and leagues based on user demand."
    },
    {
      question: "How do parlays work?",
      answer: "A parlay combines multiple bets into one. All selections must win for the parlay to pay out, but the potential payout is much higher than individual bets."
    },
    {
      question: "Is my personal information secure?",
      answer: "Yes, we use bank-level encryption and security measures to protect your personal and financial information. We never share your data with third parties without your consent."
    }
  ];

  const toggleFaq = (index: number) => {
    setExpandedFaq(expandedFaq === index ? null : index);
  };

  const openSupportEmail = () => {
    if (!user) return;
    
    const subject = encodeURIComponent('YetAI Support Request');
    const body = encodeURIComponent(`Hello YetAI Support Team,

I need assistance with the following:

[Please describe your issue here]

Account Information:
- Username: ${user.username || 'N/A'}
- Name: ${user.first_name && user.last_name ? `${user.first_name} ${user.last_name}` : 'N/A'}
- Email: ${user.email || 'N/A'}
- Account Type: ${user.subscription_tier || 'free'}

Thank you for your assistance.

Best regards,
${user.first_name || user.username || 'User'}`);
    
    const mailtoUrl = `mailto:yetai.help@gmail.com?subject=${subject}&body=${body}`;
    window.open(mailtoUrl, '_blank');
  };

  const openFeedbackEmail = () => {
    if (!user) return;
    
    const subject = encodeURIComponent('YetAI Feedback Submission');
    const body = encodeURIComponent(`Hello YetAI Team,

Thank you for providing this platform! I would like to share my feedback:

FEEDBACK TYPE (Please delete options that don't apply, keep one):
- Feature Request
- Bug Report  
- General Feedback
- User Experience Improvement
- Other: [Please specify]

FEEDBACK DETAILS:
[Please share your thoughts, suggestions, or observations here]


RATING (Optional - Please delete ratings that don't apply):
Overall Experience: [Excellent | Good | Fair | Poor]
Ease of Use: [Excellent | Good | Fair | Poor]
AI Predictions: [Excellent | Good | Fair | Poor]

ADDITIONAL COMMENTS:
[Any other thoughts or suggestions]

Account Information:
- Username: ${user.username || 'N/A'}
- Email: ${user.email || 'N/A'}
- Account Type: ${user.subscription_tier || 'free'}

Thank you for your time!

Best regards,
${user.first_name || user.username || 'User'}`);
    
    const mailtoUrl = `mailto:yetai.help@gmail.com?subject=${subject}&body=${body}`;
    window.open(mailtoUrl, '_blank');
  };

  return (
    <Layout requiresAuth>
      <div className="space-y-6">
        <div className="text-center">
          <h1 className="text-3xl font-bold text-gray-900 mb-4">Help Center</h1>
          <p className="text-gray-600 mb-8">Find answers to common questions or get in touch with our support team</p>
          
          <div className="max-w-md mx-auto relative">
            <Search className="absolute left-3 top-3 w-5 h-5 text-gray-400" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search for help..."
              className="w-full pl-10 pr-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
          <div className="bg-white p-6 rounded-lg border border-gray-200 text-center">
            <Book className="w-12 h-12 text-blue-600 mx-auto mb-4" />
            <h3 className="font-semibold text-lg mb-2">Getting Started</h3>
            <p className="text-gray-600 text-sm mb-4">Learn the basics of using YetAI platform</p>
            <button className="text-blue-600 hover:text-blue-700 font-medium">
              View Guide
            </button>
          </div>
          
          <div className="bg-white p-6 rounded-lg border border-gray-200 text-center">
            <MessageSquare className="w-12 h-12 text-green-600 mx-auto mb-4" />
            <h3 className="font-semibold text-lg mb-2">Live Chat</h3>
            <p className="text-gray-600 text-sm mb-4">Chat with our support team in real-time</p>
            <button className="text-green-600 hover:text-green-700 font-medium">
              Start Chat
            </button>
          </div>

          <div className="bg-white p-6 rounded-lg border border-gray-200 text-center">
            <Mail className="w-12 h-12 text-purple-600 mx-auto mb-4" />
            <h3 className="font-semibold text-lg mb-2">Email Support</h3>
            <p className="text-gray-600 text-sm mb-4">Send us a detailed message about your issue</p>
            <button 
              onClick={openSupportEmail}
              className="text-purple-600 hover:text-purple-700 font-medium"
            >
              Send Email
            </button>
          </div>
        </div>

        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <h2 className="text-2xl font-semibold mb-6 flex items-center">
            <HelpCircle className="w-6 h-6 mr-3" />
            Frequently Asked Questions
          </h2>
          
          <div className="space-y-4">
            {faqs.map((faq, index) => (
              <div key={index} className="border border-gray-200 rounded-lg">
                <button
                  onClick={() => toggleFaq(index)}
                  className="w-full px-6 py-4 text-left flex items-center justify-between hover:bg-gray-50 transition-colors"
                >
                  <span className="font-medium">{faq.question}</span>
                  {expandedFaq === index ? (
                    <ChevronDown className="w-5 h-5 text-gray-500" />
                  ) : (
                    <ChevronRight className="w-5 h-5 text-gray-500" />
                  )}
                </button>
                
                {expandedFaq === index && (
                  <div className="px-6 pb-4 text-gray-600">
                    {faq.answer}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        <div className="bg-blue-50 border border-blue-200 rounded-lg p-6">
          <h3 className="font-semibold text-lg mb-2">Still need help?</h3>
          <p className="text-gray-600 mb-4">
            Can't find what you're looking for? Our support team is here to help you 24/7.
          </p>
          <div className="flex space-x-4">
            <button 
              onClick={openSupportEmail}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
            >
              Contact Support
            </button>
            <button 
              onClick={openFeedbackEmail}
              className="px-4 py-2 border border-blue-600 text-blue-600 rounded-lg hover:bg-blue-50 transition-colors"
            >
              Submit Feedback
            </button>
          </div>
        </div>
      </div>
    </Layout>
  );
}