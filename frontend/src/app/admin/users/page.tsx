'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Layout from '@/components/Layout';
import { useAuth } from '@/components/Auth';
import { apiClient } from '@/lib/api';
import AppLoading from '@/components/yetai/AppLoading';
import PageHeader from '@/components/yetai/PageHeader';
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
  EyeOff,
  Database
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
  is_hidden: boolean;
  created_at: string;
  last_login: string;
  totp_enabled: boolean;
}

export default function AdminUsersPage() {
  const { isAuthenticated, loading, user: currentUser, token } = useAuth();
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
    is_verified: true,
    is_hidden: false
  });

  useEffect(() => {
    if (!loading && (!isAuthenticated || !currentUser?.is_admin)) {
      router.push('/dashboard');
    } else if (isAuthenticated && currentUser?.is_admin) {
      loadUsers();
    }
  }, [isAuthenticated, loading, currentUser, router]);

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
        is_hidden: editingUser.is_hidden,
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
          is_verified: true,
          is_hidden: false
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

  const handleDeleteAllBets = async (userId: number, username: string) => {
    if (!confirm(`Are you sure you want to delete ALL bets for user "${username}"? This action cannot be undone and is intended for testing purposes only.`)) return;
    
    setIsLoading(true);
    try {
      const response = await apiClient.delete(`/api/admin/users/${userId}/bets`, token);
      if (response.status === 'success') {
        const totalDeleted = (response.bets_deleted || 0) + (response.parlay_bets_deleted || 0);
        setMessage({
          type: 'success',
          text: `Successfully deleted ${totalDeleted} bets for ${username} (${response.bets_deleted || 0} regular bets, ${response.parlay_bets_deleted || 0} parlay bets)`
        });
      }
    } catch (error: any) {
      setMessage({ type: 'error', text: error.detail || 'Failed to delete user bets' });
    } finally {
      setIsLoading(false);
    }
  };

  if (loading) {
    return (
      <Layout requiresAuth fullWidth>
        <AppLoading label="Loading users…" />
      </Layout>
    );
  }

  if (!isAuthenticated || !currentUser?.is_admin) {
    return null;
  }

  return (
    <Layout requiresAuth fullWidth>
      <PageHeader
        title="User Management"
        subtitle="View, edit, and manage all user accounts"
        actions={
          <>
            <button
              type="button"
              onClick={() => setShowCreateModal(true)}
              className="btn btn-primary"
            >
              <Users className="w-4 h-4" />
              Create User
            </button>
            <button type="button" onClick={() => router.push('/admin')} className="btn">
              Back to Admin
            </button>
          </>
        }
      />

      <div className="space-y-6">
        {message && (
          <div className={`${
            message.type === 'success' ? 'alert alert-success' : 'alert alert-error'
          }`} style={{ marginBottom: 16 }}>
            <div className="flex items-center">
              <AlertCircle className="w-5 h-5 mr-2" />
              {message.text}
            </div>
          </div>
        )}

        {/* Search Bar */}
        <form onSubmit={handleSearch} className="card card-tight">
          <div className="flex space-x-4">
            <div className="flex-1 relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 dim w-5 h-5" />
              <input
                type="text"
                placeholder="Search by name, email, or username..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="input w-full pl-10"
              />
            </div>
            <button
              type="submit"
              disabled={isLoading}
              className="btn btn-primary transition-colors disabled:opacity-50"
            >
              Search
            </button>
          </div>
        </form>

        {/* Users Table */}
        <div className="card" style={{ padding: 0 }}>
          <div className="data-table-wrap">
            <table className="data-table">
              <thead className="">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium dim uppercase tracking-wider">User</th>
                  <th className="px-6 py-3 text-left text-xs font-medium dim uppercase tracking-wider">Subscription</th>
                  <th className="px-6 py-3 text-left text-xs font-medium dim uppercase tracking-wider">Status</th>
                  <th className="px-6 py-3 text-left text-xs font-medium dim uppercase tracking-wider">Security</th>
                  <th className="px-6 py-3 text-left text-xs font-medium dim uppercase tracking-wider">Last Login</th>
                  <th className="px-6 py-3 text-left text-xs font-medium dim uppercase tracking-wider">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border)]">
                {users.map((user) => (
                  <tr key={user.id} className="">
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div>
                        <div className="text-sm font-medium ">
                          {user.first_name} {user.last_name}
                        </div>
                        <div className="text-sm dim">@{user.username}</div>
                        <div className="text-sm dim">{user.email}</div>
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
(user.subscription_tier === 'pro' || user.subscription_tier === 'elite')
                          ? 'bg-yellow-100 text-yellow-800' 
                          : 'bg-gray-100 '
                      }`}>
                        {(user.subscription_tier === 'pro' || user.subscription_tier === 'elite') && <Star className="w-3 h-3 mr-1" />}
                        {user.subscription_tier === 'pro' ? 'Pro' : user.subscription_tier === 'elite' ? 'Elite' : user.subscription_tier}
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
                        {user.is_hidden && (
                          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 ">
                            <EyeOff className="w-3 h-3 mr-1" />
                            Hidden
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
                    <td className="px-6 py-4 whitespace-nowrap text-sm dim">
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
                          onClick={() => handleDeleteAllBets(user.id, user.username)}
                          className="text-orange-600 hover:text-orange-900"
                          title="Delete all bets (testing only)"
                          disabled={isLoading}
                        >
                          <Database className="w-4 h-4" />
                        </button>
                        <button
                          onClick={() => handleDelete(user.id)}
                          className="text-red-600 hover:text-red-900 disabled:opacity-50 disabled:cursor-not-allowed"
                          title={user.id === currentUser?.id ? "Cannot delete yourself" : "Delete user"}
                          disabled={user.id === currentUser?.id}
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
                  className="dim hover:muted"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium muted mb-1">Email Address</label>
                  <input
                    type="email"
                    value={editingUser.email}
                    onChange={(e) => setEditingUser({ ...editingUser, email: e.target.value })}
                    className="w-full px-3 py-2 border border-[var(--border)] rounded-lg focus:ring-2 focus:ring-blue-500"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium muted mb-1">Username</label>
                  <input
                    type="text"
                    value={editingUser.username}
                    onChange={(e) => setEditingUser({ ...editingUser, username: e.target.value })}
                    className="w-full px-3 py-2 border border-[var(--border)] rounded-lg focus:ring-2 focus:ring-blue-500"
                    placeholder="username123"
                  />
                  <p className="text-xs dim mt-1">
                    3+ characters, letters, numbers, underscores and hyphens only
                  </p>
                </div>

                <div>
                  <label className="block text-sm font-medium muted mb-1">First Name</label>
                  <input
                    type="text"
                    value={editingUser.first_name}
                    onChange={(e) => setEditingUser({ ...editingUser, first_name: e.target.value })}
                    className="w-full px-3 py-2 border border-[var(--border)] rounded-lg focus:ring-2 focus:ring-blue-500"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium muted mb-1">Last Name</label>
                  <input
                    type="text"
                    value={editingUser.last_name}
                    onChange={(e) => setEditingUser({ ...editingUser, last_name: e.target.value })}
                    className="w-full px-3 py-2 border border-[var(--border)] rounded-lg focus:ring-2 focus:ring-blue-500"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium muted mb-1">New Password</label>
                  <div className="relative">
                    <input
                      type={showPassword ? "text" : "password"}
                      value={editingPassword}
                      onChange={(e) => setEditingPassword(e.target.value)}
                      placeholder="Leave blank to keep current password"
                      className="w-full px-3 py-2 pr-10 border border-[var(--border)] rounded-lg focus:ring-2 focus:ring-blue-500"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(!showPassword)}
                      className="absolute inset-y-0 right-0 flex items-center pr-3 dim hover:muted"
                    >
                      {showPassword ? (
                        <EyeOff className="w-4 h-4" />
                      ) : (
                        <Eye className="w-4 h-4" />
                      )}
                    </button>
                  </div>
                  <p className="text-xs dim mt-1">
                    Leave blank to keep the current password unchanged
                  </p>
                </div>

                <div>
                  <label className="block text-sm font-medium muted mb-1">Subscription Tier</label>
                  <select
                    value={editingUser.subscription_tier}
                    onChange={(e) => setEditingUser({ ...editingUser, subscription_tier: e.target.value })}
                    className="w-full px-3 py-2 border border-[var(--border)] rounded-lg focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="free">Free</option>
                    <option value="pro">Pro</option>
                    <option value="elite">Elite</option>
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
                      checked={editingUser.is_hidden}
                      onChange={(e) => setEditingUser({ ...editingUser, is_hidden: e.target.checked })}
                      className="mr-2"
                    />
                    <span className="text-sm">Hidden (from leaderboard & public displays)</span>
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
                  className="px-4 py-2 border border-[var(--border)] rounded-lg "
                >
                  Cancel
                </button>
                <button
                  onClick={handleUpdate}
                  disabled={isLoading}
                  className="btn btn-primary disabled:opacity-50"
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
                  className="dim hover:muted"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              <p className="text-sm muted mb-4">
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
                className="w-full mt-4 btn btn-primary"
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
                  className="dim hover:muted"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium muted mb-1">Email Address *</label>
                  <input
                    type="email"
                    value={newUser.email}
                    onChange={(e) => setNewUser({ ...newUser, email: e.target.value })}
                    className="w-full px-3 py-2 border border-[var(--border)] rounded-lg focus:ring-2 focus:ring-blue-500"
                    placeholder="user@example.com"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium muted mb-1">Username *</label>
                  <input
                    type="text"
                    value={newUser.username}
                    onChange={(e) => setNewUser({ ...newUser, username: e.target.value })}
                    className="w-full px-3 py-2 border border-[var(--border)] rounded-lg focus:ring-2 focus:ring-blue-500"
                    placeholder="username123"
                  />
                  <p className="text-xs dim mt-1">
                    3+ characters, letters, numbers, underscores and hyphens only
                  </p>
                </div>

                <div>
                  <label className="block text-sm font-medium muted mb-1">Password</label>
                  <input
                    type="text"
                    value={newUser.password}
                    onChange={(e) => setNewUser({ ...newUser, password: e.target.value })}
                    className="w-full px-3 py-2 border border-[var(--border)] rounded-lg focus:ring-2 focus:ring-blue-500"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium muted mb-1">First Name</label>
                  <input
                    type="text"
                    value={newUser.first_name}
                    onChange={(e) => setNewUser({ ...newUser, first_name: e.target.value })}
                    className="w-full px-3 py-2 border border-[var(--border)] rounded-lg focus:ring-2 focus:ring-blue-500"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium muted mb-1">Last Name</label>
                  <input
                    type="text"
                    value={newUser.last_name}
                    onChange={(e) => setNewUser({ ...newUser, last_name: e.target.value })}
                    className="w-full px-3 py-2 border border-[var(--border)] rounded-lg focus:ring-2 focus:ring-blue-500"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium muted mb-1">Subscription Tier</label>
                  <select
                    value={newUser.subscription_tier}
                    onChange={(e) => setNewUser({ ...newUser, subscription_tier: e.target.value })}
                    className="w-full px-3 py-2 border border-[var(--border)] rounded-lg focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="free">Free</option>
                    <option value="pro">Pro</option>
                    <option value="elite">Elite</option>
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

                  <label className="flex items-center">
                    <input
                      type="checkbox"
                      checked={newUser.is_hidden}
                      onChange={(e) => setNewUser({ ...newUser, is_hidden: e.target.checked })}
                      className="mr-2"
                    />
                    <span className="text-sm">Hidden</span>
                  </label>
                </div>
              </div>

              <div className="flex justify-end space-x-3 mt-6">
                <button
                  onClick={() => setShowCreateModal(false)}
                  className="px-4 py-2 border border-[var(--border)] rounded-lg "
                >
                  Cancel
                </button>
                <button
                  onClick={handleCreateUser}
                  disabled={isLoading || !newUser.email || !newUser.username}
                  className="btn btn-primary disabled:opacity-50"
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