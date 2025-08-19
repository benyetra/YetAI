'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Layout from '@/components/Layout';
import { useAuth } from '@/components/Auth';
import { apiClient } from '@/lib/api';
import { 
  Users, 
  Search, 
  Edit, 
  Trash2, 
  Shield, 
  Key,
  Star,
  UserCheck,
  UserX,
  X,
  Save,
  AlertCircle,
  Eye,
  EyeOff
} from 'lucide-react';

interface User {
  id: number;
  email: string;
  username: string;
  first_name: string;
  last_name: string;
  subscription_tier: string;
  is_admin: boolean;
  is_verified: boolean;
  created_at: string;
  last_login: string;
  totp_enabled: boolean;
}

export default function AdminUsersPage() {
  const { isAuthenticated, loading, user, token } = useAuth();
  const router = useRouter();
  
  const [users, setUsers] = useState<User[]>([]);
  const [searchTerm, setSearchTerm] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [editingPassword, setEditingPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [showPasswordReset, setShowPasswordReset] = useState(false);
  const [tempPassword, setTempPassword] = useState('');
  const [message, setMessage] = useState<{type: 'success' | 'error', text: string} | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newUser, setNewUser] = useState({
    email: '',
    username: '',
    password: 'password123',
    first_name: '',
    last_name: '',
    subscription_tier: 'free',
    is_admin: false,
    is_verified: true
  });

  useEffect(() => {
    if (!loading && (!isAuthenticated || !user?.is_admin)) {
      router.push('/dashboard');
    } else if (isAuthenticated && user?.is_admin) {
      loadUsers();
    }
  }, [isAuthenticated, loading, user, router]);

  const loadUsers = async () => {
    setIsLoading(true);
    try {
      const response = await apiClient.get(`/api/admin/users${searchTerm ? `?search=${searchTerm}` : ''}`, token);
      if (response.status === 'success') {
        setUsers(response.users);
      }
    } catch (error) {
      setMessage({ type: 'error', text: 'Failed to load users' });
    } finally {
      setIsLoading(false);
    }
  };

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    loadUsers();
  };

  const handleEdit = (user: User) => {
    setEditingUser({ ...user });
    setEditingPassword(''); // Reset password field
    setShowPassword(false); // Reset password visibility
    setShowEditModal(true);
  };

  const handleUpdate = async () => {
    if (!editingUser) return;
    
    setIsLoading(true);
    try {
      const updateData: any = {
        email: editingUser.email,
        username: editingUser.username,
        first_name: editingUser.first_name,
        last_name: editingUser.last_name,
        subscription_tier: editingUser.subscription_tier,
        is_admin: editingUser.is_admin,
        is_verified: editingUser.is_verified,
        totp_enabled: editingUser.totp_enabled
      };
      
      // Only include password if it's been set
      if (editingPassword.trim()) {
        updateData.password = editingPassword;
      }
      
      const response = await apiClient.put(
        `/api/admin/users/${editingUser.id}`,
        updateData,
        token
      );
      
      if (response.status === 'success') {
        setMessage({ type: 'success', text: 'User updated successfully' });
        setShowEditModal(false);
        loadUsers();
      }
    } catch (error) {
      setMessage({ type: 'error', text: 'Failed to update user' });
    } finally {
      setIsLoading(false);
    }
  };

  const handleDelete = async (userId: number) => {
    if (!confirm('Are you sure you want to delete this user?')) return;
    
    setIsLoading(true);
    try {
      const response = await apiClient.delete(`/api/admin/users/${userId}`, token);
      if (response.status === 'success') {
        setMessage({ type: 'success', text: 'User deleted successfully' });
        loadUsers();
      }
    } catch (error: any) {
      setMessage({ type: 'error', text: error.detail || 'Failed to delete user' });
    } finally {
      setIsLoading(false);
    }
  };

  const handleCreateUser = async () => {
    if (!newUser.email || !newUser.username) {
      setMessage({ type: 'error', text: 'Email and username are required' });
      return;
    }

    // Validate username format
    if (!/^[a-zA-Z0-9_-]+$/.test(newUser.username)) {
      setMessage({ type: 'error', text: 'Username can only contain letters, numbers, underscores, and hyphens' });
      return;
    }

    if (newUser.username.length < 3) {
      setMessage({ type: 'error', text: 'Username must be at least 3 characters long' });
      return;
    }
    
    setIsLoading(true);
    try {
      const response = await apiClient.post('/api/admin/users', newUser, token);
      if (response.status === 'success') {
        setMessage({ type: 'success', text: response.message });
        setShowCreateModal(false);
        setNewUser({
          email: '',
          username: '',
          password: 'password123',
          first_name: '',
          last_name: '',
          subscription_tier: 'free',
          is_admin: false,
          is_verified: true
        });
        loadUsers();
      }
    } catch (error: any) {
      setMessage({ type: 'error', text: error.detail || 'Failed to create user' });
    } finally {
      setIsLoading(false);
    }
  };

  const handlePasswordReset = async (userId: number) => {
    setIsLoading(true);
    try {
      const response = await apiClient.post(`/api/admin/users/${userId}/reset-password`, {}, token);
      if (response.status === 'success') {
        setTempPassword(response.temporary_password);
        setShowPasswordReset(true);
        setMessage({ type: 'success', text: 'Password reset successfully' });
      }
    } catch (error) {
      setMessage({ type: 'error', text: 'Failed to reset password' });
    } finally {
      setIsLoading(false);
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

  if (!isAuthenticated || !user?.is_admin) {
    return null;
  }

  return (
    <Layout>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <Users className="w-8 h-8 text-blue-600" />
            <h1 className="text-3xl font-bold text-gray-900">User Management</h1>
          </div>
          <div className="flex space-x-3">
            <button
              onClick={() => setShowCreateModal(true)}
              className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors flex items-center"
            >
              <Users className="w-4 h-4 mr-2" />
              Create User
            </button>
            <button
              onClick={() => router.push('/admin')}
              className="px-4 py-2 bg-gray-600 text-white rounded-lg hover:bg-gray-700 transition-colors"
            >
              Back to Admin
            </button>
          </div>
        </div>

        {message && (
          <div className={`rounded-lg p-4 ${
            message.type === 'success' ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800'
          }`}>
            <div className="flex items-center">
              <AlertCircle className="w-5 h-5 mr-2" />
              {message.text}
            </div>
          </div>
        )}

        {/* Search Bar */}
        <form onSubmit={handleSearch} className="bg-white rounded-lg border border-gray-200 p-4">
          <div className="flex space-x-4">
            <div className="flex-1 relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 w-5 h-5" />
              <input
                type="text"
                placeholder="Search by name, email, or username..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>
            <button
              type="submit"
              disabled={isLoading}
              className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50"
            >
              Search
            </button>
          </div>
        </form>

        {/* Users Table */}
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">User</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Subscription</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Security</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Last Login</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {users.map((user) => (
                  <tr key={user.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div>
                        <div className="text-sm font-medium text-gray-900">
                          {user.first_name} {user.last_name}
                        </div>
                        <div className="text-sm text-gray-500">@{user.username}</div>
                        <div className="text-sm text-gray-400">{user.email}</div>
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                        user.subscription_tier === 'premium' 
                          ? 'bg-yellow-100 text-yellow-800' 
                          : 'bg-gray-100 text-gray-800'
                      }`}>
                        {user.subscription_tier === 'premium' && <Star className="w-3 h-3 mr-1" />}
                        {user.subscription_tier}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex space-x-2">
                        {user.is_admin && (
                          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-purple-100 text-purple-800">
                            <Shield className="w-3 h-3 mr-1" />
                            Admin
                          </span>
                        )}
                        {user.is_verified ? (
                          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
                            <UserCheck className="w-3 h-3 mr-1" />
                            Verified
                          </span>
                        ) : (
                          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800">
                            <UserX className="w-3 h-3 mr-1" />
                            Unverified
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      {user.totp_enabled && (
                        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800">
                          <Shield className="w-3 h-3 mr-1" />
                          2FA
                        </span>
                      )}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {user.last_login ? new Date(user.last_login).toLocaleDateString() : 'Never'}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm">
                      <div className="flex space-x-2">
                        <button
                          onClick={() => handleEdit(user)}
                          className="text-blue-600 hover:text-blue-900"
                          title="Edit user"
                        >
                          <Edit className="w-4 h-4" />
                        </button>
                        <button
                          onClick={() => handlePasswordReset(user.id)}
                          className="text-yellow-600 hover:text-yellow-900"
                          title="Reset password"
                        >
                          <Key className="w-4 h-4" />
                        </button>
                        <button
                          onClick={() => handleDelete(user.id)}
                          className="text-red-600 hover:text-red-900"
                          title="Delete user"
                          disabled={user.id === user?.id}
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Edit Modal */}
        {showEditModal && editingUser && (
          <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
            <div className="bg-white rounded-lg max-w-md w-full p-6">
              <div className="flex items-center justify-between mb-6">
                <h2 className="text-xl font-semibold">Edit User</h2>
                <button
                  onClick={() => setShowEditModal(false)}
                  className="text-gray-400 hover:text-gray-600"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Email Address</label>
                  <input
                    type="email"
                    value={editingUser.email}
                    onChange={(e) => setEditingUser({ ...editingUser, email: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Username</label>
                  <input
                    type="text"
                    value={editingUser.username}
                    onChange={(e) => setEditingUser({ ...editingUser, username: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    placeholder="username123"
                  />
                  <p className="text-xs text-gray-500 mt-1">
                    3+ characters, letters, numbers, underscores and hyphens only
                  </p>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">First Name</label>
                  <input
                    type="text"
                    value={editingUser.first_name}
                    onChange={(e) => setEditingUser({ ...editingUser, first_name: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Last Name</label>
                  <input
                    type="text"
                    value={editingUser.last_name}
                    onChange={(e) => setEditingUser({ ...editingUser, last_name: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">New Password</label>
                  <div className="relative">
                    <input
                      type={showPassword ? "text" : "password"}
                      value={editingPassword}
                      onChange={(e) => setEditingPassword(e.target.value)}
                      placeholder="Leave blank to keep current password"
                      className="w-full px-3 py-2 pr-10 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(!showPassword)}
                      className="absolute inset-y-0 right-0 flex items-center pr-3 text-gray-400 hover:text-gray-600"
                    >
                      {showPassword ? (
                        <EyeOff className="w-4 h-4" />
                      ) : (
                        <Eye className="w-4 h-4" />
                      )}
                    </button>
                  </div>
                  <p className="text-xs text-gray-500 mt-1">
                    Leave blank to keep the current password unchanged
                  </p>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Subscription Tier</label>
                  <select
                    value={editingUser.subscription_tier}
                    onChange={(e) => setEditingUser({ ...editingUser, subscription_tier: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="free">Free</option>
                    <option value="premium">Premium</option>
                  </select>
                </div>

                <div className="flex items-center space-x-4">
                  <label className="flex items-center">
                    <input
                      type="checkbox"
                      checked={editingUser.is_admin}
                      onChange={(e) => setEditingUser({ ...editingUser, is_admin: e.target.checked })}
                      className="mr-2"
                    />
                    <span className="text-sm">Admin</span>
                  </label>

                  <label className="flex items-center">
                    <input
                      type="checkbox"
                      checked={editingUser.is_verified}
                      onChange={(e) => setEditingUser({ ...editingUser, is_verified: e.target.checked })}
                      className="mr-2"
                    />
                    <span className="text-sm">Verified</span>
                  </label>
                  
                  <label className="flex items-center">
                    <input
                      type="checkbox"
                      checked={editingUser.totp_enabled}
                      onChange={(e) => setEditingUser({ ...editingUser, totp_enabled: e.target.checked })}
                      className="mr-2"
                    />
                    <span className="text-sm">2FA Enabled</span>
                  </label>
                </div>
              </div>

              <div className="flex justify-end space-x-3 mt-6">
                <button
                  onClick={() => setShowEditModal(false)}
                  className="px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  onClick={handleUpdate}
                  disabled={isLoading}
                  className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
                >
                  <Save className="w-4 h-4 inline mr-2" />
                  Save Changes
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Password Reset Modal */}
        {showPasswordReset && (
          <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
            <div className="bg-white rounded-lg max-w-md w-full p-6">
              <div className="flex items-center justify-between mb-6">
                <h2 className="text-xl font-semibold">Password Reset</h2>
                <button
                  onClick={() => {
                    setShowPasswordReset(false);
                    setTempPassword('');
                  }}
                  className="text-gray-400 hover:text-gray-600"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              <p className="text-sm text-gray-600 mb-4">
                The user's password has been reset. Share this temporary password with them:
              </p>

              <div className="bg-gray-100 rounded-lg p-4 font-mono text-center text-lg">
                {tempPassword}
              </div>

              <p className="text-sm text-red-600 mt-4">
                ⚠️ This password will not be shown again. Make sure to copy it now.
              </p>

              <button
                onClick={() => {
                  navigator.clipboard.writeText(tempPassword);
                  setMessage({ type: 'success', text: 'Password copied to clipboard' });
                }}
                className="w-full mt-4 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
              >
                Copy Password
              </button>
            </div>
          </div>
        )}

        {/* Create User Modal */}
        {showCreateModal && (
          <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
            <div className="bg-white rounded-lg max-w-md w-full p-6">
              <div className="flex items-center justify-between mb-6">
                <h2 className="text-xl font-semibold">Create New User</h2>
                <button
                  onClick={() => setShowCreateModal(false)}
                  className="text-gray-400 hover:text-gray-600"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Email Address *</label>
                  <input
                    type="email"
                    value={newUser.email}
                    onChange={(e) => setNewUser({ ...newUser, email: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    placeholder="user@example.com"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Username *</label>
                  <input
                    type="text"
                    value={newUser.username}
                    onChange={(e) => setNewUser({ ...newUser, username: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    placeholder="username123"
                  />
                  <p className="text-xs text-gray-500 mt-1">
                    3+ characters, letters, numbers, underscores and hyphens only
                  </p>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
                  <input
                    type="text"
                    value={newUser.password}
                    onChange={(e) => setNewUser({ ...newUser, password: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">First Name</label>
                  <input
                    type="text"
                    value={newUser.first_name}
                    onChange={(e) => setNewUser({ ...newUser, first_name: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Last Name</label>
                  <input
                    type="text"
                    value={newUser.last_name}
                    onChange={(e) => setNewUser({ ...newUser, last_name: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Subscription Tier</label>
                  <select
                    value={newUser.subscription_tier}
                    onChange={(e) => setNewUser({ ...newUser, subscription_tier: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="free">Free</option>
                    <option value="premium">Premium</option>
                  </select>
                </div>

                <div className="flex items-center space-x-4">
                  <label className="flex items-center">
                    <input
                      type="checkbox"
                      checked={newUser.is_admin}
                      onChange={(e) => setNewUser({ ...newUser, is_admin: e.target.checked })}
                      className="mr-2"
                    />
                    <span className="text-sm">Admin</span>
                  </label>

                  <label className="flex items-center">
                    <input
                      type="checkbox"
                      checked={newUser.is_verified}
                      onChange={(e) => setNewUser({ ...newUser, is_verified: e.target.checked })}
                      className="mr-2"
                    />
                    <span className="text-sm">Verified</span>
                  </label>
                </div>
              </div>

              <div className="flex justify-end space-x-3 mt-6">
                <button
                  onClick={() => setShowCreateModal(false)}
                  className="px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  onClick={handleCreateUser}
                  disabled={isLoading || !newUser.email || !newUser.username}
                  className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50"
                >
                  <Users className="w-4 h-4 inline mr-2" />
                  Create User
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </Layout>
  );
}