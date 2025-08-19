'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/components/Auth';
import { Eye, EyeOff, Mail, Lock, User, TrendingUp, DollarSign, Activity, Users } from 'lucide-react';
import Link from 'next/link';

export default function SignUpPage() {
  const router = useRouter();
  const { signup, isAuthenticated, loading } = useAuth();
  const [formData, setFormData] = useState({
    firstName: '',
    lastName: '',
    email: '',
    username: '',
    password: '',
    confirmPassword: '',
    agreeToTerms: false
  });
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (isAuthenticated) {
      router.push('/dashboard');
    }
  }, [isAuthenticated, router]);

  const handleInputChange = (field: string, value: string | boolean) => {
    setFormData(prev => ({ ...prev, [field]: value }));
    setError(''); // Clear error when user types
  };

  const validateForm = () => {
    if (!formData.firstName.trim()) {
      setError('First name is required');
      return false;
    }
    if (!formData.email.trim()) {
      setError('Email is required');
      return false;
    }
    if (!formData.username.trim()) {
      setError('Username is required');
      return false;
    }
    if (formData.username.length < 3) {
      setError('Username must be at least 3 characters long');
      return false;
    }
    if (!/^[a-zA-Z0-9_-]+$/.test(formData.username)) {
      setError('Username can only contain letters, numbers, underscores, and hyphens');
      return false;
    }
    if (formData.password.length < 6) {
      setError('Password must be at least 6 characters long');
      return false;
    }
    if (formData.password !== formData.confirmPassword) {
      setError('Passwords do not match');
      return false;
    }
    if (!formData.agreeToTerms) {
      setError('You must agree to the terms and conditions');
      return false;
    }
    return true;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (!validateForm()) {
      return;
    }

    setIsLoading(true);

    try {
      const result = await signup(
        formData.email,
        formData.username,
        formData.password,
        formData.firstName,
        formData.lastName
      );
      
      if (result.success) {
        router.push('/dashboard');
      } else {
        setError(result.message || 'Signup failed. Please try again.');
      }
    } catch (error) {
      setError('An unexpected error occurred. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleGoogleSignUp = async () => {
    // For now, show a notification that this feature is coming soon
    setError('Google Sign-up is coming soon! Please use email and password for now.');
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-lg">Loading...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex bg-gray-100">
      {/* Left Panel - Signup Form */}
      <div className="flex-1 flex items-center justify-center px-4 sm:px-6 lg:px-8 bg-white">
        <div className="max-w-md w-full space-y-8">

          {/* Logo */}
          <div className="flex items-center space-x-3">
            <div className="w-8 h-8 bg-gradient-to-r from-purple-600 to-blue-600 rounded-lg flex items-center justify-center">
              <span className="text-white font-bold text-lg">Y</span>
            </div>
            <span className="text-2xl font-bold text-gray-900">YetAI</span>
          </div>

          {/* Welcome Message */}
          <div>
            <h2 className="text-3xl font-bold text-gray-900">Create Account</h2>
            <p className="mt-2 text-gray-600">Join YetAI and start your betting journey</p>
          </div>

          {/* Google Sign Up */}
          <button
            type="button"
            onClick={handleGoogleSignUp}
            className="w-full flex items-center justify-center px-4 py-3 border border-gray-300 rounded-xl shadow-sm bg-white text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors"
          >
            <svg className="w-5 h-5 mr-3" viewBox="0 0 24 24">
              <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
              <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
              <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
              <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
            </svg>
            Sign up with Google
          </button>

          <div className="relative">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-gray-300" />
            </div>
            <div className="relative flex justify-center text-sm">
              <span className="px-2 bg-white text-gray-500">or Sign up with Email</span>
            </div>
          </div>

          {/* Signup Form */}
          <form className="space-y-6" onSubmit={handleSubmit}>
            {error && (
              <div className="p-3 rounded-lg bg-red-50 border border-red-200">
                <p className="text-sm text-red-600">{error}</p>
              </div>
            )}

            {/* Name Fields */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label htmlFor="firstName" className="block text-sm font-medium text-gray-700 mb-2">
                  First Name
                </label>
                <div className="relative">
                  <User className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
                  <input
                    id="firstName"
                    name="firstName"
                    type="text"
                    required
                    value={formData.firstName}
                    onChange={(e) => handleInputChange('firstName', e.target.value)}
                    className="pl-10 pr-4 py-3 w-full border border-gray-300 rounded-xl focus:ring-2 focus:ring-purple-500 focus:border-transparent transition-colors"
                    placeholder="John"
                  />
                </div>
              </div>

              <div>
                <label htmlFor="lastName" className="block text-sm font-medium text-gray-700 mb-2">
                  Last Name
                </label>
                <input
                  id="lastName"
                  name="lastName"
                  type="text"
                  value={formData.lastName}
                  onChange={(e) => handleInputChange('lastName', e.target.value)}
                  className="px-4 py-3 w-full border border-gray-300 rounded-xl focus:ring-2 focus:ring-purple-500 focus:border-transparent transition-colors"
                  placeholder="Doe"
                />
              </div>
            </div>

            {/* Email Field */}
            <div>
              <label htmlFor="email" className="block text-sm font-medium text-gray-700 mb-2">
                Email address
              </label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
                <input
                  id="email"
                  name="email"
                  type="email"
                  autoComplete="email"
                  required
                  value={formData.email}
                  onChange={(e) => handleInputChange('email', e.target.value)}
                  className="pl-10 pr-4 py-3 w-full border border-gray-300 rounded-xl focus:ring-2 focus:ring-purple-500 focus:border-transparent transition-colors"
                  placeholder="john@example.com"
                />
              </div>
            </div>

            {/* Username Field */}
            <div>
              <label htmlFor="username" className="block text-sm font-medium text-gray-700 mb-2">
                Username
              </label>
              <div className="relative">
                <User className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
                <input
                  id="username"
                  name="username"
                  type="text"
                  autoComplete="username"
                  required
                  value={formData.username}
                  onChange={(e) => handleInputChange('username', e.target.value)}
                  className="pl-10 pr-4 py-3 w-full border border-gray-300 rounded-xl focus:ring-2 focus:ring-purple-500 focus:border-transparent transition-colors"
                  placeholder="john_doe"
                />
              </div>
              <p className="mt-1 text-xs text-gray-500">3+ characters, letters, numbers, underscore and hyphen only</p>
            </div>

            {/* Password Fields */}
            <div className="grid grid-cols-1 gap-4">
              <div>
                <label htmlFor="password" className="block text-sm font-medium text-gray-700 mb-2">
                  Password
                </label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
                  <input
                    id="password"
                    name="password"
                    type={showPassword ? 'text' : 'password'}
                    autoComplete="new-password"
                    required
                    value={formData.password}
                    onChange={(e) => handleInputChange('password', e.target.value)}
                    className="pl-10 pr-12 py-3 w-full border border-gray-300 rounded-xl focus:ring-2 focus:ring-purple-500 focus:border-transparent transition-colors"
                    placeholder="••••••••"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-3 top-1/2 transform -translate-y-1/2 text-gray-400 hover:text-gray-600"
                  >
                    {showPassword ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
                  </button>
                </div>
              </div>

              <div>
                <label htmlFor="confirmPassword" className="block text-sm font-medium text-gray-700 mb-2">
                  Confirm Password
                </label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
                  <input
                    id="confirmPassword"
                    name="confirmPassword"
                    type={showConfirmPassword ? 'text' : 'password'}
                    autoComplete="new-password"
                    required
                    value={formData.confirmPassword}
                    onChange={(e) => handleInputChange('confirmPassword', e.target.value)}
                    className="pl-10 pr-12 py-3 w-full border border-gray-300 rounded-xl focus:ring-2 focus:ring-purple-500 focus:border-transparent transition-colors"
                    placeholder="••••••••"
                  />
                  <button
                    type="button"
                    onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                    className="absolute right-3 top-1/2 transform -translate-y-1/2 text-gray-400 hover:text-gray-600"
                  >
                    {showConfirmPassword ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
                  </button>
                </div>
              </div>
            </div>

            {/* Terms Agreement */}
            <div className="flex items-center">
              <input
                id="agree-terms"
                name="agree-terms"
                type="checkbox"
                checked={formData.agreeToTerms}
                onChange={(e) => handleInputChange('agreeToTerms', e.target.checked)}
                className="h-4 w-4 text-purple-600 focus:ring-purple-500 border-gray-300 rounded"
              />
              <label htmlFor="agree-terms" className="ml-2 block text-sm text-gray-700">
                I agree to the{' '}
                <a href="#" className="text-purple-600 hover:text-purple-500">Terms and Conditions</a>
                {' '}and{' '}
                <a href="#" className="text-purple-600 hover:text-purple-500">Privacy Policy</a>
              </label>
            </div>

            {/* Submit Button */}
            <button
              type="submit"
              disabled={isLoading}
              className="w-full flex justify-center py-3 px-4 border border-transparent rounded-xl shadow-sm text-sm font-medium text-white bg-gradient-to-r from-purple-600 to-blue-600 hover:from-purple-700 hover:to-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-purple-500 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
            >
              {isLoading ? 'Creating Account...' : 'Create Account'}
            </button>

            {/* Login Link */}
            <div className="text-center">
              <span className="text-sm text-gray-600">
                Already have an account?{' '}
                <Link href="/login" className="font-medium text-purple-600 hover:text-purple-500">
                  Sign In
                </Link>
              </span>
            </div>
          </form>
        </div>
      </div>

      {/* Right Panel - Hero/Preview Section */}
      <div className="hidden lg:flex lg:flex-1 relative">
        <div className="w-full bg-gradient-to-br from-purple-600 via-purple-700 to-indigo-800 flex items-center justify-center p-12">
          <div className="max-w-lg w-full space-y-8">
            {/* User Avatar */}
            <div className="flex justify-end">
              <div className="w-16 h-16 rounded-full bg-white/20 backdrop-blur-sm border border-white/30 flex items-center justify-center">
                <img 
                  src="https://images.unsplash.com/photo-1472099645785-5658abf4ff4e?w=64&h=64&fit=crop&crop=face" 
                  alt="User" 
                  className="w-12 h-12 rounded-full object-cover"
                />
              </div>
            </div>

            {/* Main Dashboard Card */}
            <div className="bg-white/10 backdrop-blur-lg rounded-2xl p-6 border border-white/20">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-white font-semibold">Earnings</h3>
                <div className="w-2 h-2 bg-green-400 rounded-full"></div>
              </div>
              
              <div className="space-y-4">
                <div>
                  <div className="text-3xl font-bold text-white">+112.10%</div>
                  <div className="text-white/70 text-sm">Business Growth</div>
                </div>
                
                <div className="flex items-center space-x-2">
                  <TrendingUp className="w-4 h-4 text-green-400" />
                  <span className="text-white/80 text-sm">68.5% Growth</span>
                </div>
              </div>
            </div>

            {/* Secondary Card */}
            <div className="bg-white/10 backdrop-blur-lg rounded-2xl p-6 border border-white/20">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center space-x-2">
                  <Activity className="w-5 h-5 text-blue-400" />
                  <span className="text-white font-medium">Performance</span>
                </div>
                <span className="text-2xl font-bold text-white">+80.9%</span>
              </div>
              
              <div className="text-white/70 text-sm mb-4">Last 30 days business growth</div>
              
              {/* Progress Bar */}
              <div className="bg-white/20 rounded-full h-2">
                <div className="bg-gradient-to-r from-blue-400 to-purple-400 h-2 rounded-full w-4/5"></div>
              </div>
              
              <div className="flex justify-between mt-2 text-xs text-white/60">
                <span>68.5% Increase</span>
                <span>Last Week</span>
              </div>
            </div>

            {/* Stats Cards Row */}
            <div className="grid grid-cols-2 gap-4">
              <div className="bg-white/10 backdrop-blur-lg rounded-xl p-4 border border-white/20">
                <DollarSign className="w-6 h-6 text-green-400 mb-2" />
                <div className="text-white font-semibold">$24.5K</div>
                <div className="text-white/60 text-xs">Revenue</div>
              </div>
              
              <div className="bg-white/10 backdrop-blur-lg rounded-xl p-4 border border-white/20">
                <Users className="w-6 h-6 text-blue-400 mb-2" />
                <div className="text-white font-semibold">1,847</div>
                <div className="text-white/60 text-xs">Active Users</div>
              </div>
            </div>

            {/* Bottom User Avatars */}
            <div className="flex justify-center">
              <div className="flex -space-x-3">
                <img 
                  src="https://images.unsplash.com/photo-1494790108755-2616b612b786?w=40&h=40&fit=crop&crop=face" 
                  alt="User 1" 
                  className="w-10 h-10 rounded-full border-2 border-white object-cover"
                />
                <img 
                  src="https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=40&h=40&fit=crop&crop=face" 
                  alt="User 2" 
                  className="w-10 h-10 rounded-full border-2 border-white object-cover"
                />
                <div className="w-10 h-10 rounded-full border-2 border-white bg-white/20 backdrop-blur-sm flex items-center justify-center">
                  <span className="text-white text-xs font-medium">+5</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}