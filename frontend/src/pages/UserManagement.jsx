import React, { useState, useEffect } from "react";
import axios from "axios";
import { UserPlus, Shield, User, Pencil, Save, X, KeyRound, Power, Trash2, Search, Check } from "lucide-react";
import { useConfirm } from "../components/ConfirmModal";

// Full page names — identical to the sidebar, so the admin always knows
// exactly which page an access item grants.
const PAGES = [
  { key: "processor", label: "Data Processor", desc: "Shapefile intake, processing and migration to the map" },
  { key: "point", label: "Point Processor", desc: "Mudryia points intake and processing" },
  { key: "dashboard", label: "Dashboard", desc: "KPIs, statistics and overview charts" },
  { key: "users", label: "Users", desc: "Team members and their access (this page)" },
  { key: "database", label: "Database", desc: "Database connections and map layer settings" },
  { key: "import", label: "Data Import", desc: "Import request sheets and survey results" },
  { key: "requests", label: "Company Requests", desc: "Company requests ledger" },
  { key: "mudryia_requests", label: "Mudryia Requests", desc: "Mudryia requests ledger" },
  { key: "tracking", label: "Tracking board", desc: "Kanban board of request statuses" },
  { key: "lookups", label: "Lookup tables", desc: "Governorates, centers, villages and area units" },
  { key: "reports", label: "Reports", desc: "Reports and data exports" },
];

const pageLabel = (key) => (PAGES.find((p) => p.key === key) || {}).label || key;

const initials = (fullName, username) => {
  const src = (fullName || "").trim() || (username || "").trim();
  if (!src) return "?";
  const parts = src.split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
};

const ROLE_LABELS = {
  viewer: "Viewer (Read Only)",
  editor: "Editor (Can Upload)",
  admin: "Admin (Full Access)",
};

function IconBtn({ title, onClick, className, children }) {
  return (
    <button
      onClick={onClick}
      title={title}
      aria-label={title}
      className={"inline-flex items-center justify-center w-8 h-8 rounded-lg transition-colors " + className}
    >
      {children}
    </button>
  );
}

export default function UserManagement() {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [newUser, setNewUser] = useState({ username: "", password: "", full_name: "", role: "viewer" });
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [editingId, setEditingId] = useState(null);
  const [editForm, setEditForm] = useState({ full_name: "", role: "viewer", is_active: true });
  const [pwUser, setPwUser] = useState(null);
  const [pwPassword, setPwPassword] = useState("");
  const [pwBusy, setPwBusy] = useState(false);
  const [accessUser, setAccessUser] = useState(null);
  const [accessSel, setAccessSel] = useState([]);
  const [accessBusy, setAccessBusy] = useState(false);
  const [userFilter, setUserFilter] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [askConfirm, confirmModal] = useConfirm();

  const authH = () => ({ headers: { Authorization: "Bearer " + localStorage.getItem("token") } });

  const fetchUsers = async () => {
    try {
      const res = await axios.get("/api/v1/users", authH());
      setUsers(res.data);
      setError("");
    } catch (err) {
      setError("Failed to load users");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchUsers();
  }, []);

  // Escape closes any open modal.
  useEffect(() => {
    const h = (e) => {
      if (e.key === "Escape") { setAccessUser(null); closePw(); }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  const handleCreateUser = async (e) => {
    e.preventDefault();
    setError("");
    setSuccess("");
    try {
      await axios.post("/api/v1/users", newUser, authH());
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
      await axios.put(`/api/v1/users/${editingId}`, editForm, authH());
      setSuccess("User updated successfully");
      setEditingId(null);
      fetchUsers();
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to update user");
    }
  };

  const toggleActive = async (user) => {
    setError("");
    setSuccess("");
    try {
      await axios.put(`/api/v1/users/${user.id}`, { is_active: !user.is_active }, authH());
      setSuccess(`@${user.username} ${user.is_active ? "deactivated" : "activated"}`);
      fetchUsers();
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to update status");
    }
  };

  const openPw = (user) => {
    setPwUser(user);
    setPwPassword("");
    setError("");
    setSuccess("");
  };

  const closePw = () => {
    setPwUser(null);
    setPwPassword("");
    setPwBusy(false);
  };

  const changePassword = async (e) => {
    e.preventDefault();
    if (pwPassword.length < 6) {
      setError("Password must be at least 6 characters.");
      return;
    }
    setPwBusy(true);
    try {
      await axios.put(`/api/v1/users/${pwUser.id}`, { password: pwPassword }, authH());
      setSuccess(`Password changed for @${pwUser.username}`);
      closePw();
      fetchUsers();
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to change password");
      setPwBusy(false);
    }
  };

  // ---- Access editor (full page names) ----
  const openAccess = (user) => {
    setAccessUser(user);
    setAccessSel([...(user.permissions || [])]);
    setError("");
    setSuccess("");
  };

  const closeAccess = () => {
    setAccessUser(null);
    setAccessSel([]);
    setAccessBusy(false);
  };

  const toggleAccessSel = (key) => {
    setAccessSel((sel) => (sel.includes(key) ? sel.filter((k) => k !== key) : [...sel, key]));
  };

  const saveAccess = async () => {
    if (!accessUser || accessBusy) return;
    setAccessBusy(true);
    try {
      await axios.put(`/api/v1/users/${accessUser.id}`, { permissions: accessSel }, authH());
      setSuccess(`Access updated for @${accessUser.username} (${accessSel.length} of ${PAGES.length} pages)`);
      closeAccess();
      fetchUsers();
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to update access");
      setAccessBusy(false);
    }
  };

  const requestDelete = (user) => askConfirm({
    title: "Delete user?",
    message: `Permanently delete @${user.username}?\nThis only works if the user is not linked to any saved data (rows they created or audit records).`,
    confirmLabel: "Delete",
    danger: true,
    onConfirm: () => deleteUser(user),
  });

  const deleteUser = async (user) => {
    setError("");
    setSuccess("");
    try {
      await axios.delete(`/api/v1/users/${user.id}`, authH());
      setSuccess(`User @${user.username} deleted.`);
      fetchUsers();
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to delete user");
    }
  };

  const filteredUsers = users.filter((u) => {
    const q = userFilter.trim().toLowerCase();
    if (q && !(u.username || "").toLowerCase().includes(q) && !(u.full_name || "").toLowerCase().includes(q)) return false;
    if (roleFilter && u.role !== roleFilter) return false;
    if (statusFilter === "active" && !u.is_active) return false;
    if (statusFilter === "inactive" && u.is_active) return false;
    return true;
  });

  const roleCounts = {
    admin: users.filter((u) => u.role === "admin").length,
    editor: users.filter((u) => u.role === "editor").length,
    viewer: users.filter((u) => u.role === "viewer").length,
  };

  const accessChips = (user) => {
    const perms = user.permissions || [];
    const shown = perms.slice(0, 3);
    const rest = perms.length - shown.length;
    return (
      <div className="flex flex-wrap gap-1 max-w-[320px]">
        {shown.map((k) => (
          <span key={k} className="inline-flex items-center gap-1 text-[11px] font-medium bg-blue-50 text-blue-700 border border-blue-200 rounded-full px-2 py-0.5">
            <Check className="w-3 h-3" />{pageLabel(k)}
          </span>
        ))}
        {rest > 0 && (
          <span className="inline-flex items-center text-[11px] font-semibold bg-slate-100 text-slate-600 border border-slate-200 rounded-full px-2 py-0.5">
            +{rest} more
          </span>
        )}
        {perms.length === 0 && (
          <span className="text-xs text-gray-400">No access</span>
        )}
      </div>
    );
  };

  return (
    <div className="h-[calc(100vh-4.5rem)] flex flex-col gap-4 p-4 md:p-6 w-full overflow-hidden">
      <div className="flex-none flex justify-between items-center flex-wrap gap-2">
        <div>
          <h1 className="text-3xl font-bold text-slate-800">Team Management</h1>
          <p className="text-gray-500 mt-1">
            Manage GeoPortal access for your team.
            <span className="ml-2 text-xs font-medium text-gray-500">
              {roleCounts.admin} admin · {roleCounts.editor} editors · {roleCounts.viewer} viewers
            </span>
          </p>
        </div>
      </div>

      {(error || success) && (
        <div className="flex-none grid grid-cols-1 lg:grid-cols-4 gap-8 mb-0">
          <div className="lg:col-span-1">
            {error && <div className="mb-4 p-3 bg-red-50 text-red-700 text-sm rounded-lg border border-red-200">{error}</div>}
            {success && <div className="mb-4 p-3 bg-green-50 text-green-700 text-sm rounded-lg border border-green-200">{success}</div>}
          </div>
        </div>
      )}

      <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-4 gap-4 md:gap-6 overflow-y-auto lg:overflow-visible">

        {/* Create User Form */}
        <div className="lg:col-span-1 min-h-0">
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 lg:max-h-full lg:overflow-auto">
            <h2 className="text-lg font-semibold flex items-center mb-1 text-gray-800">
              <UserPlus className="w-5 h-5 mr-2 text-blue-600" />
              Add New User
            </h2>
            <p className="text-xs text-gray-400 mb-4">They can sign in right after creation.</p>

            <form onSubmit={handleCreateUser} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Username</label>
                <input
                  type="text" required
                  placeholder="e.g. sara_n"
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
                  value={newUser.username} onChange={e => setNewUser({ ...newUser, username: e.target.value })}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Full Name</label>
                <input
                  type="text" required
                  placeholder="e.g. Sara Nasser"
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
                  value={newUser.full_name} onChange={e => setNewUser({ ...newUser, full_name: e.target.value })}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
                <input
                  type="password" required minLength={6}
                  placeholder="Minimum 6 characters"
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
                  value={newUser.password} onChange={e => setNewUser({ ...newUser, password: e.target.value })}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Role</label>
                <select
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500 bg-white"
                  value={newUser.role} onChange={e => setNewUser({ ...newUser, role: e.target.value })}
                >
                  <option value="viewer">{ROLE_LABELS.viewer}</option>
                  <option value="editor">{ROLE_LABELS.editor}</option>
                  <option value="admin">{ROLE_LABELS.admin}</option>
                </select>
              </div>
              <button type="submit" className="w-full bg-blue-600 text-white rounded-md py-2 text-sm font-medium hover:bg-blue-700 transition">
                Create Account
              </button>
            </form>
          </div>
        </div>

        {/* Users List */}
        <div className="lg:col-span-3 min-h-0 flex flex-col">
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 flex flex-col min-h-0 lg:h-full overflow-hidden">
            <div className="flex-none flex items-center gap-3 px-6 py-3 border-b border-gray-200 flex-wrap">
              <p className="text-sm font-medium text-gray-600 mr-auto">{filteredUsers.length} of {users.length} user(s)</p>
              <div className="relative flex-1 min-w-[180px] sm:flex-none">
                <Search className="w-4 h-4 text-gray-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
                <input
                  type="text"
                  placeholder="Search by name or username..."
                  value={userFilter}
                  onChange={(e) => setUserFilter(e.target.value)}
                  className="pl-8 pr-3 py-1.5 w-full sm:w-56 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>
              <select
                value={roleFilter}
                onChange={(e) => setRoleFilter(e.target.value)}
                title="Filter by role"
                className="px-2.5 py-1.5 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-1 focus:ring-blue-500 bg-white"
              >
                <option value="">All roles</option>
                <option value="viewer">Viewer</option>
                <option value="editor">Editor</option>
                <option value="admin">Admin</option>
              </select>
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                title="Filter by status"
                className="px-2.5 py-1.5 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-1 focus:ring-blue-500 bg-white"
              >
                <option value="">All statuses</option>
                <option value="active">Active</option>
                <option value="inactive">Inactive</option>
              </select>
            </div>
            <div className="hidden md:block flex-1 min-h-0 overflow-auto">
              <table className="min-w-[960px] w-full divide-y divide-gray-200">
                <thead className="bg-gray-50 sticky top-0 z-10">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">User</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Role</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Access</th>
                    <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Actions</th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {filteredUsers.map((user) => {
                    const perms = user.permissions || [];
                    return (
                      <tr key={user.id} className="hover:bg-gray-50 transition">
                        <td className="px-6 py-3 whitespace-nowrap">
                          <div className="flex items-center">
                            <div className="flex-shrink-0 h-9 w-9 rounded-full bg-blue-100 text-blue-700 flex items-center justify-center text-xs font-bold">
                              {initials(user.full_name, user.username)}
                            </div>
                            <div className="ml-3">
                              {editingId === user.id ? (
                                <input
                                  type="text"
                                  className="w-40 border border-gray-300 rounded-md px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
                                  value={editForm.full_name}
                                  onChange={(e) => setEditForm({ ...editForm, full_name: e.target.value })}
                                />
                              ) : (
                                <div className="text-sm font-medium text-gray-900">{user.full_name || "—"}</div>
                              )}
                              <div className="text-xs text-gray-500">@{user.username}</div>
                            </div>
                          </div>
                        </td>
                        <td className="px-6 py-3 whitespace-nowrap">
                          {editingId === user.id ? (
                            <select
                              className="border border-gray-300 rounded-md px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500 bg-white"
                              value={editForm.role}
                              onChange={(e) => setEditForm({ ...editForm, role: e.target.value })}
                            >
                              <option value="viewer">{ROLE_LABELS.viewer}</option>
                              <option value="editor">{ROLE_LABELS.editor}</option>
                              <option value="admin">{ROLE_LABELS.admin}</option>
                            </select>
                          ) : (
                            <span className={"px-2 inline-flex text-xs leading-5 font-semibold rounded-full " + (user.role === 'admin' ? 'bg-purple-100 text-purple-800' : user.role === 'editor' ? 'bg-blue-100 text-blue-800' : 'bg-gray-100 text-gray-800')}>
                              {ROLE_LABELS[user.role] || user.role}
                            </span>
                          )}
                        </td>
                        <td className="px-6 py-3 whitespace-nowrap">
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
                        <td className="px-6 py-3">
                          <div className="flex items-start gap-2">
                            {accessChips(user)}
                            <button
                              onClick={() => openAccess(user)}
                              title="Manage page access"
                              className="shrink-0 inline-flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] font-semibold bg-slate-100 text-slate-700 hover:bg-blue-50 hover:text-blue-700 border border-slate-200 transition-colors"
                            >
                              <Shield className="w-3.5 h-3.5" /> Manage
                            </button>
                          </div>
                        </td>
                        <td className="px-6 py-3 whitespace-nowrap">
                          {editingId === user.id ? (
                            <div className="flex gap-1 justify-end">
                              <IconBtn title="Save changes" onClick={saveEdit} className="bg-green-600 text-white hover:bg-green-700">
                                <Save className="w-4 h-4" />
                              </IconBtn>
                              <IconBtn title="Cancel editing" onClick={cancelEdit} className="bg-gray-200 text-gray-700 hover:bg-gray-300">
                                <X className="w-4 h-4" />
                              </IconBtn>
                            </div>
                          ) : (
                            <div className="flex gap-1 justify-end">
                              <IconBtn title="Edit name / role" onClick={() => startEdit(user)} className="bg-slate-100 text-slate-700 hover:bg-slate-200">
                                <Pencil className="w-4 h-4" />
                              </IconBtn>
                              <IconBtn
                                title={user.is_active ? "Deactivate user" : "Activate user"}
                                onClick={() => toggleActive(user)}
                                className={user.is_active ? "bg-red-50 text-red-700 hover:bg-red-100" : "bg-emerald-50 text-emerald-700 hover:bg-emerald-100"}
                              >
                                <Power className="w-4 h-4" />
                              </IconBtn>
                              <IconBtn title="Change password" onClick={() => openPw(user)} className="bg-amber-50 text-amber-700 hover:bg-amber-100">
                                <KeyRound className="w-4 h-4" />
                              </IconBtn>
                              <IconBtn title="Delete user (only if not linked to data)" onClick={() => requestDelete(user)} className="bg-red-50 text-red-700 hover:bg-red-100">
                                <Trash2 className="w-4 h-4" />
                              </IconBtn>
                            </div>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                  {loading && (
                    <tr>
                      <td colSpan="5" className="px-6 py-8 text-center text-gray-500">
                        Loading users...
                      </td>
                    </tr>
                  )}
                  {!loading && filteredUsers.length === 0 && (
                    <tr>
                      <td colSpan="5" className="px-6 py-8 text-center text-gray-500">
                        {users.length === 0 ? "No users yet — create the first account on the left." : "No users match your search."}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            {/* Mobile cards */}
            <div className="md:hidden divide-y divide-gray-200 flex-1 min-h-0 overflow-auto">
              {filteredUsers.map((user) => (
                <div key={user.id} className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <div className="h-9 w-9 rounded-full bg-blue-100 text-blue-700 flex items-center justify-center text-xs font-bold shrink-0">
                      {initials(user.full_name, user.username)}
                    </div>
                    <div className="min-w-0 flex-1">
                      {editingId === user.id ? (
                        <input
                          type="text"
                          className="w-full border border-gray-300 rounded-md px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
                          value={editForm.full_name}
                          onChange={(e) => setEditForm({ ...editForm, full_name: e.target.value })}
                        />
                      ) : (
                        <div className="text-sm font-medium text-gray-900 truncate">{user.full_name || "—"}</div>
                      )}
                      <div className="text-xs text-gray-500 truncate">@{user.username}</div>
                    </div>
                    {editingId === user.id ? (
                      <select
                        className="border border-gray-300 rounded-md px-1 py-1 text-xs bg-white shrink-0"
                        value={editForm.role}
                        onChange={(e) => setEditForm({ ...editForm, role: e.target.value })}
                      >
                        <option value="viewer">Viewer</option>
                        <option value="editor">Editor</option>
                        <option value="admin">Admin</option>
                      </select>
                    ) : (
                      <span className={"shrink-0 px-2 inline-flex text-xs leading-5 font-semibold rounded-full " + (user.role === 'admin' ? 'bg-purple-100 text-purple-800' : user.role === 'editor' ? 'bg-blue-100 text-blue-800' : 'bg-gray-100 text-gray-800')}>
                        {user.role}
                      </span>
                    )}
                    {editingId === user.id ? (
                      <label className="inline-flex items-center text-[11px] text-gray-600 cursor-pointer shrink-0">
                        <input
                          type="checkbox"
                          checked={editForm.is_active}
                          onChange={(e) => setEditForm({ ...editForm, is_active: e.target.checked })}
                          className="mr-1 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                        />
                        Active
                      </label>
                    ) : (
                      <span className={"shrink-0 px-2 inline-flex text-xs leading-5 font-semibold rounded-full " + (user.is_active ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800')}>
                        {user.is_active ? 'Active' : 'Inactive'}
                      </span>
                    )}
                  </div>
                  <div className="mt-2 flex items-start gap-2">
                    {accessChips(user)}
                    <button
                      onClick={() => openAccess(user)}
                      className="shrink-0 inline-flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] font-semibold bg-slate-100 text-slate-700 hover:bg-blue-50 hover:text-blue-700 border border-slate-200 transition-colors"
                    >
                      <Shield className="w-3.5 h-3.5" /> Manage
                    </button>
                  </div>
                  <div className="mt-2 flex gap-1">
                    {editingId === user.id ? (
                      <>
                        <IconBtn title="Save changes" onClick={saveEdit} className="bg-green-600 text-white hover:bg-green-700">
                          <Save className="w-4 h-4" />
                        </IconBtn>
                        <IconBtn title="Cancel editing" onClick={cancelEdit} className="bg-gray-200 text-gray-700 hover:bg-gray-300">
                          <X className="w-4 h-4" />
                        </IconBtn>
                      </>
                    ) : (
                      <>
                        <IconBtn title="Edit name / role" onClick={() => startEdit(user)} className="bg-slate-100 text-slate-700 hover:bg-slate-200">
                          <Pencil className="w-4 h-4" />
                        </IconBtn>
                        <IconBtn
                          title={user.is_active ? "Deactivate user" : "Activate user"}
                          onClick={() => toggleActive(user)}
                          className={user.is_active ? "bg-red-50 text-red-700 hover:bg-red-100" : "bg-emerald-50 text-emerald-700 hover:bg-emerald-100"}
                        >
                          <Power className="w-4 h-4" />
                        </IconBtn>
                        <IconBtn title="Change password" onClick={() => openPw(user)} className="bg-amber-50 text-amber-700 hover:bg-amber-100">
                          <KeyRound className="w-4 h-4" />
                        </IconBtn>
                        <IconBtn title="Delete user (only if not linked to data)" onClick={() => requestDelete(user)} className="bg-red-50 text-red-700 hover:bg-red-100">
                          <Trash2 className="w-4 h-4" />
                        </IconBtn>
                      </>
                    )}
                  </div>
                </div>
              ))}
              {loading && <p className="px-4 py-8 text-center text-sm text-gray-500">Loading users...</p>}
              {!loading && filteredUsers.length === 0 && (
                <p className="px-4 py-8 text-center text-sm text-gray-500">
                  {users.length === 0 ? "No users yet — create the first account above." : "No users match your search."}
                </p>
              )}
            </div>
          </div>
        </div>

      </div>

      {/* Access editor */}
      {accessUser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={closeAccess}>
          <div className="bg-white rounded-xl shadow-xl w-full max-w-lg max-h-[85vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
            <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
              <div>
                <h3 className="text-base font-semibold text-gray-800 flex items-center gap-2">
                  <Shield className="w-4 h-4 text-blue-600" /> Page access
                </h3>
                <p className="text-xs text-gray-500 mt-0.5">
                  {accessUser.full_name || accessUser.username} · @{accessUser.username} ·{" "}
                  <span className="font-semibold text-blue-700">{accessSel.length} of {PAGES.length} selected</span>
                </p>
              </div>
              <button onClick={closeAccess} title="Close" className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500">
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="px-5 py-2 flex items-center gap-2 border-b border-gray-50">
              <button
                onClick={() => setAccessSel(PAGES.map((p) => p.key))}
                className="text-xs font-semibold text-blue-600 hover:text-blue-800"
              >
                Select all
              </button>
              <span className="text-gray-300">|</span>
              <button
                onClick={() => setAccessSel([])}
                className="text-xs font-semibold text-gray-500 hover:text-gray-700"
              >
                Clear
              </button>
            </div>
            <div className="px-3 py-2 overflow-y-auto">
              {PAGES.map((p) => {
                const on = accessSel.includes(p.key);
                return (
                  <label
                    key={p.key}
                    className={"flex items-start gap-3 px-2 py-2.5 rounded-lg cursor-pointer transition-colors " + (on ? "bg-blue-50/60 hover:bg-blue-50" : "hover:bg-gray-50")}
                  >
                    <input
                      type="checkbox"
                      checked={on}
                      onChange={() => toggleAccessSel(p.key)}
                      className="mt-0.5 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                    />
                    <span>
                      <span className="block text-sm font-medium text-gray-800">{p.label}</span>
                      <span className="block text-xs text-gray-400 mt-0.5">{p.desc}</span>
                    </span>
                  </label>
                );
              })}
            </div>
            <div className="px-5 py-3 border-t border-gray-100 flex justify-end gap-2">
              <button
                onClick={closeAccess}
                className="px-4 py-2 rounded-md text-sm font-medium bg-gray-100 text-gray-700 hover:bg-gray-200 transition"
              >
                Cancel
              </button>
              <button
                onClick={saveAccess}
                disabled={accessBusy}
                className="px-4 py-2 rounded-md text-sm font-medium bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition"
              >
                {accessBusy ? "Saving..." : "Save access"}
              </button>
            </div>
          </div>
        </div>
      )}

      {pwUser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={closePw}>
          <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-sm mx-4" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-semibold flex items-center text-gray-800 mb-1">
              <KeyRound className="w-5 h-5 mr-2 text-amber-600" />
              Change Password
            </h3>
            <p className="text-sm text-gray-500 mb-4">
              Set a new password for <span className="font-medium text-gray-700">@{pwUser.username}</span>
            </p>
            <form onSubmit={changePassword} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">New password</label>
                <input
                  type="password" required minLength={6}
                  autoFocus
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-amber-500"
                  value={pwPassword} onChange={(e) => setPwPassword(e.target.value)}
                />
                <p className="text-xs text-gray-400 mt-1">Minimum 6 characters.</p>
              </div>
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={closePw}
                  className="px-4 py-2 rounded-md text-sm font-medium bg-gray-100 text-gray-700 hover:bg-gray-200 transition"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={pwBusy}
                  className="px-4 py-2 rounded-md text-sm font-medium bg-amber-600 text-white hover:bg-amber-700 disabled:opacity-50 transition"
                >
                  {pwBusy ? "Saving..." : "Change password"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
      {confirmModal}
    </div>
  );
}
