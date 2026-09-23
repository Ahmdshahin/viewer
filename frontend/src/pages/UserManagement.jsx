import React, { useState, useEffect } from "react";
import axios from "axios";
import { UserPlus, Shield, User, CheckCircle, XCircle, Pencil, Save, X } from "lucide-react";

export default function UserManagement() {
  const [users, setUsers] = useState([]);
  const [newUser, setNewUser] = useState({ username: "", password: "", full_name: "", role: "viewer" });
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [editingId, setEditingId] = useState(null);
  const [editForm, setEditForm] = useState({ full_name: "", role: "viewer", is_active: true });

  const PAGES = [
    { key: "processor", label: "Proc" },
    { key: "point", label: "Pnt" },
    { key: "dashboard", label: "Dash" },
    { key: "users", label: "Users" },
    { key: "database", label: "DB" },
  ];

  const togglePage = async (user, page) => {
    const has = (user.permissions || []).includes(page);
    const next = has ? user.permissions.filter((p) => p !== page) : [...(user.permissions || []), page];
    try {
      const token = localStorage.getItem("token");
      await axios.put(`/api/v1/users/${user.id}`, { permissions: next }, {
        headers: { Authorization: "Bearer " + token }
      });
      setSuccess(`Access updated for @${user.username}`);
      fetchUsers();
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to update access");
    }
  };

  const fetchUsers = async () => {
    try {
      const token = localStorage.getItem("token");
      const res = await axios.get("/api/v1/users", {
        headers: { Authorization: "Bearer " + token }
      });
      setUsers(res.data);
    } catch (err) {
      setError("Failed to load users");
    }
  };

  useEffect(() => {
    fetchUsers();
  }, []);

  const handleCreateUser = async (e) => {
    e.preventDefault();
    setError("");
    setSuccess("");
    try {
      const token = localStorage.getItem("token");
      await axios.post("/api/v1/users", newUser, {
        headers: { Authorization: "Bearer " + token }
      });
      setSuccess("User created successfully");
      setNewUser({ username: "", password: "", full_name: "", role: "viewer" });
      fetchUsers();
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to create user");
    }
  };

  const startEdit = (u) => {
    setEditingId(u.id);
    setEditForm({ full_name: u.full_name || "", role: u.role, is_active: u.is_active });
    setError("");
    setSuccess("");
  };

  const cancelEdit = () => {
    setEditingId(null);
    setError("");
    setSuccess("");
  };

  const saveEdit = async () => {
    try {
      const token = localStorage.getItem("token");
      await axios.put(`/api/v1/users/${editingId}`, editForm, {
        headers: { Authorization: "Bearer " + token }
      });
      setSuccess("User updated successfully");
      setEditingId(null);
      fetchUsers();
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to update user");
    }
  };

  return (
    <div className="p-8 w-full">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-3xl font-bold text-slate-800">Team Management</h1>
          <p className="text-gray-500 mt-1">Manage GeoPortal access for your 20-person team.</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-8">
        
        {/* Create User Form */}
        <div className="lg:col-span-1">
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
            <h2 className="text-lg font-semibold flex items-center mb-4 text-gray-800">
              <UserPlus className="w-5 h-5 mr-2 text-blue-600" />
              Add New User
            </h2>
            
            {error && <div className="mb-4 p-3 bg-red-50 text-red-700 text-sm rounded">{error}</div>}
            {success && <div className="mb-4 p-3 bg-green-50 text-green-700 text-sm rounded">{success}</div>}
            
            <form onSubmit={handleCreateUser} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Username</label>
                <input 
                  type="text" required
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
                  value={newUser.username} onChange={e => setNewUser({...newUser, username: e.target.value})}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Full Name</label>
                <input 
                  type="text" required
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
                  value={newUser.full_name} onChange={e => setNewUser({...newUser, full_name: e.target.value})}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
                <input 
                  type="password" required
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
                  value={newUser.password} onChange={e => setNewUser({...newUser, password: e.target.value})}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Role</label>
                <select 
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
                  value={newUser.role} onChange={e => setNewUser({...newUser, role: e.target.value})}
                >
                  <option value="viewer">Viewer (Read Only)</option>
                  <option value="editor">Editor (Can Upload)</option>
                  <option value="admin">Admin (Full Access)</option>
                </select>
              </div>
              <button type="submit" className="w-full bg-blue-600 text-white rounded-md py-2 text-sm font-medium hover:bg-blue-700 transition">
                Create Account
              </button>
            </form>
          </div>
        </div>

        {/* Users List */}
        <div className="lg:col-span-3">
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">User</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Role</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Access</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Actions</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {users.map((user) => (
                  <tr key={user.id} className="hover:bg-gray-50 transition">
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center">
                        <div className="flex-shrink-0 h-10 w-10 rounded-full bg-slate-100 flex items-center justify-center text-slate-500">
                          <User className="h-5 w-5" />
                        </div>
                        <div className="ml-4">
                          {editingId === user.id ? (
                            <input
                              type="text"
                              className="w-44 border border-gray-300 rounded-md px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
                              value={editForm.full_name}
                              onChange={(e) => setEditForm({ ...editForm, full_name: e.target.value })}
                            />
                          ) : (
                            <div className="text-sm font-medium text-gray-900">{user.full_name || "—"}</div>
                          )}
                          <div className="text-sm text-gray-500">@{user.username}</div>
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      {editingId === user.id ? (
                        <select
                          className="border border-gray-300 rounded-md px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
                          value={editForm.role}
                          onChange={(e) => setEditForm({ ...editForm, role: e.target.value })}
                        >
                          <option value="viewer">viewer</option>
                          <option value="editor">editor</option>
                          <option value="admin">admin</option>
                        </select>
                      ) : (
                        <span className={"px-2 inline-flex text-xs leading-5 font-semibold rounded-full " + (user.role === 'admin' ? 'bg-purple-100 text-purple-800' : user.role === 'editor' ? 'bg-blue-100 text-blue-800' : 'bg-gray-100 text-gray-800')}>
                          {user.role}
                        </span>
                      )}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      {editingId === user.id ? (
                        <label className="inline-flex items-center text-xs text-gray-600 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={editForm.is_active}
                            onChange={(e) => setEditForm({ ...editForm, is_active: e.target.checked })}
                            className="mr-1.5 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                          />
                          Active
                        </label>
                      ) : (
                        <span className={"px-2 inline-flex text-xs leading-5 font-semibold rounded-full " + (user.is_active ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800')}>
                          {user.is_active ? 'Active' : 'Inactive'}
                        </span>
                      )}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex gap-3">
                        {PAGES.map((p) => (
                          <label key={p.key} className="flex items-center space-x-1 text-xs text-gray-600 cursor-pointer" title={p.key}>
                            <input
                              type="checkbox"
                              checked={(user.permissions || []).includes(p.key)}
                              onChange={() => togglePage(user, p.key)}
                              className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                            />
                            <span>{p.label}</span>
                          </label>
                        ))}
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      {editingId === user.id ? (
                        <div className="flex gap-2">
                          <button
                            onClick={saveEdit}
                            className="inline-flex items-center px-2 py-1 rounded text-xs font-semibold bg-green-600 text-white hover:bg-green-700"
                          >
                            <Save className="w-3 h-3 mr-1" /> Save
                          </button>
                          <button
                            onClick={cancelEdit}
                            className="inline-flex items-center px-2 py-1 rounded text-xs font-semibold bg-gray-200 text-gray-700 hover:bg-gray-300"
                          >
                            <X className="w-3 h-3 mr-1" /> Cancel
                          </button>
                        </div>
                      ) : (
                        <button
                          onClick={() => startEdit(user)}
                          className="inline-flex items-center px-2 py-1 rounded text-xs font-semibold bg-slate-100 text-slate-700 hover:bg-slate-200"
                        >
                          <Pencil className="w-3 h-3 mr-1" /> Edit
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
                {users.length === 0 && (
                  <tr>
                    <td colSpan="5" className="px-6 py-8 text-center text-gray-500">
                      Loading users...
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

      </div>
    </div>
  );
}
