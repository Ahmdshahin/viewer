import { useState, useRef, useEffect } from "react";
import { BrowserRouter, Routes, Route, Link, useLocation, useNavigate, Navigate } from "react-router-dom";
import MapViewer from "./pages/MapViewer";
import DataProcessor from "./pages/DataProcessor";
import PointProcessor from "./pages/PointProcessor";
import Dashboard from "./pages/Dashboard";
import Login from "./pages/Login";
import UserManagement from "./pages/UserManagement";
import DbSettings from "./pages/DbSettings";
import ImportWorkbench from "./pages/ImportWorkbench";
import Requests from "./pages/Requests";
import MudryiaRequests from "./pages/MudryiaRequests";
import TrackingBoard from "./pages/TrackingBoard";
import LookupsAdmin from "./pages/LookupsAdmin";
import Reports from "./pages/Reports";
import axios from "axios";
import { LayoutDashboard, Users, LogOut, Map as MapIcon, Database, Server, MapPin, ClipboardList, UploadCloud, KanbanSquare, ListTree, Bell, BarChart3, MapPinned } from "lucide-react";

function NotificationsBell() {
  const [open, setOpen] = useState(false);
  const [unread, setUnread] = useState(0);
  const [items, setItems] = useState([]);
  const bellRef = useRef(null);
  const navigate = useNavigate();

  const openNotification = async (n) => {
    try {
      const token = localStorage.getItem("token");
      await axios.post("/api/v1/notifications/read", { id: n.id }, { headers: { Authorization: "Bearer " + token } });
    } catch (e) { /* ignore */ }
    setItems((its) => its.map((x) => (x.id === n.id ? { ...x, is_read: true } : x)));
    setUnread((u) => Math.max(0, u - 1));
    setOpen(false);
    const link = n.link_req || "";
    const m = link.match(/^(company|mudryia):(.+)$/);
    if (m) navigate((m[1] === "mudryia" ? "/mudryia-requests" : "/requests") + "?q=" + encodeURIComponent(m[2]));
  };

  const loadCount = () => {
    const token = localStorage.getItem("token");
    if (!token) return;
    axios.get("/api/v1/notifications/count", { headers: { Authorization: "Bearer " + token } })
      .then((res) => setUnread(res.data.unread))
      .catch(() => {});
  };

  useEffect(() => {
    loadCount();
    const iv = setInterval(loadCount, 30000);
    document.addEventListener("mousedown", (e) => {
      if (bellRef.current && !bellRef.current.contains(e.target)) setOpen(false);
    });
    return () => clearInterval(iv);
  }, []);

  const openPanel = async () => {
    setOpen(!open);
    if (!open) {
      const token = localStorage.getItem("token");
      try {
        const res = await axios.get("/api/v1/notifications", { headers: { Authorization: "Bearer " + token }, params: { limit: 30 } });
        setItems(res.data.items);
      } catch (e) { /* ignore */ }
    }
  };

  const markAll = async () => {
    const token = localStorage.getItem("token");
    try {
      await axios.post("/api/v1/notifications/read", { all: true }, { headers: { Authorization: "Bearer " + token } });
      setUnread(0);
      setItems((its) => its.map((n) => ({ ...n, is_read: true })));
    } catch (e) { /* ignore */ }
  };

  return (
    <div className="relative mr-3" ref={bellRef}>
      <button onClick={openPanel}
        className="relative flex items-center justify-center w-9 h-9 rounded-full bg-slate-800 text-white hover:bg-slate-700 focus:outline-none transition">
        <Bell className="w-4 h-4" />
        {unread > 0 && (
          <span className="absolute -top-1 -right-1 min-w-[18px] h-[18px] px-1 rounded-full bg-red-500 text-white text-[10px] font-bold flex items-center justify-center">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>
      {open && (
        <div className="absolute right-0 mt-2 w-80 bg-white rounded-md shadow-lg border border-gray-200 z-50 overflow-hidden">
          <div className="px-4 py-2.5 border-b border-gray-100 flex items-center justify-between">
            <p className="text-sm font-semibold text-gray-800">Notifications</p>
            <button onClick={markAll} disabled={!unread}
              className="text-xs font-semibold text-blue-600 hover:underline disabled:text-gray-300">
              Mark all read
            </button>
          </div>
          <div className="max-h-80 overflow-y-auto">
            {items.length === 0 && <p className="px-4 py-6 text-center text-xs text-gray-400">No notifications</p>}
            {items.map((n) => (
              <button key={n.id} onClick={() => openNotification(n)} className={"w-full text-left px-4 py-3 border-b border-gray-50 hover:bg-gray-50 " + (!n.is_read ? "bg-blue-50/50" : "")}>
                <p className="text-sm font-semibold text-gray-800">{n.title}</p>
                <p className="text-xs text-gray-500 mt-0.5">{n.body}</p>
                <p className="text-[10px] text-gray-400 mt-1">{n.created_at ? n.created_at.replace("T", " ").slice(0, 16) : ""}{n.link_req ? " — عرض الطلب" : ""}</p>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

const MENU_GROUPS = [
  {
    title: "Requests",
    items: [
      { key: "requests", to: "/requests", label: "Company Requests", Icon: ClipboardList },
      { key: "mudryia_requests", to: "/mudryia-requests", label: "Mudryia Requests", Icon: MapPinned },
      { key: "tracking", to: "/tracking", label: "Tracking board", Icon: KanbanSquare },
    ],
  },
  {
    title: "Processing",
    items: [
      { key: "processor", to: "/processor", label: "Data Processor", Icon: Database },
      { key: "point", to: "/point", label: "Point Processor", Icon: MapPin },
      { key: "import", to: "/import", label: "Data Import", Icon: UploadCloud },
    ],
  },
  {
    title: "Insights",
    items: [
      { key: "dashboard", to: "/dashboard", label: "Dashboard", Icon: LayoutDashboard },
      { key: "reports", to: "/reports", label: "Reports", Icon: BarChart3 },
    ],
  },
  {
    title: "Administration",
    items: [
      { key: "users", to: "/users", label: "Users", Icon: Users },
      { key: "database", to: "/db-settings", label: "Database", Icon: Server },
      { key: "lookups", to: "/lookups", label: "Lookup tables", Icon: ListTree },
    ],
  },
];

const menuInitials = (fullName, username) => {
  const src = (fullName || "").trim() || (username || "").trim();
  if (!src) return "?";
  const parts = src.split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
};

function TopBar({ setToken, role, pages, me }) {
  const [showDropdown, setShowDropdown] = useState(false);
  const dropdownRef = useRef(null);
  const location = useLocation();
  const initials = menuInitials(me && me.full_name, me && me.username);

  useEffect(() => {
    function handleClickOutside(event) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setShowDropdown(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  

  return (
    <div className="h-16 bg-slate-900 text-white flex items-center justify-between px-6 shadow-md z-50">
      
      {/* Brand */}
      <div className="text-xl font-black tracking-wider flex items-center">
        <Link to="/">GeoPortal<span className="text-blue-500">.</span></Link>
      </div>

      

      {/* Avatar */}
      <div className="flex items-center">
        <NotificationsBell />
        <div className="relative" ref={dropdownRef}>
        <button
          onClick={() => setShowDropdown(!showDropdown)}
          title={(me && (me.full_name || me.username)) || "Account"}
          className="flex items-center justify-center w-9 h-9 rounded-full bg-blue-600 text-white text-xs font-bold hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-slate-900 transition"
        >
          {initials}
        </button>
        
        {showDropdown && (
          <div className="absolute right-0 mt-2 w-64 bg-white rounded-xl shadow-xl py-1 border border-gray-200 z-50 max-h-[calc(100vh-5rem)] overflow-y-auto">
            <div className="px-4 py-3 border-b border-gray-100 flex items-center gap-3">
              <div className="h-10 w-10 rounded-full bg-blue-600 text-white flex items-center justify-center text-sm font-bold shrink-0">
                {initials}
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold text-gray-900 truncate">{(me && me.full_name) || (me && me.username) || "Account"}</p>
                <p className="text-xs text-gray-500 truncate">{me && me.username ? "@" + me.username : ""}</p>
              </div>
              <span className={"shrink-0 px-2 py-0.5 inline-flex text-[11px] leading-4 font-semibold rounded-full capitalize " + (role === "admin" ? "bg-purple-100 text-purple-800" : role === "editor" ? "bg-blue-100 text-blue-800" : "bg-gray-100 text-gray-800")}>
                {role}
              </span>
            </div>
            {MENU_GROUPS.map((group) => {
              const visible = group.items.filter((i) => pages.includes(i.key));
              if (!visible.length) return null;
              return (
                <div key={group.title} className="py-1">
                  <p className="px-4 pt-1.5 pb-1 text-[10px] font-bold uppercase tracking-wider text-gray-400">
                    {group.title}
                  </p>
                  {visible.map((i) => (
                    <Link
                      key={i.key}
                      to={i.to}
                      onClick={() => setShowDropdown(false)}
                      className="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-blue-50 hover:text-blue-800 flex items-center transition-colors"
                    >
                      <i.Icon className="w-4 h-4 mr-2.5 text-gray-400" />
                      {i.label}
                    </Link>
                  ))}
                </div>
              );
            })}
            {pages.length > 0 && (
              <div className="border-t border-gray-100 my-1"></div>
            )}
            <button
              onClick={() => { localStorage.removeItem("token"); setToken(null); }}
              className="w-full text-left px-4 py-2.5 text-sm font-semibold text-red-600 hover:bg-red-50 flex items-center transition-colors"
            >
              <LogOut className="w-4 h-4 mr-2.5" />
              Logout
            </button>
          </div>
        )}
      </div>
      </div>
    </div>
  );
}

function App() {
  const [token, setToken] = useState(localStorage.getItem("token"));
  const [me, setMe] = useState(null);

  useEffect(() => {
    if (!token) {
      setMe(null);
      return;
    }
    axios.get("/api/v1/auth/me", { headers: { Authorization: "Bearer " + token } })
      .then((res) => setMe(res.data))
      .catch(() => {
        localStorage.removeItem("token");
        setToken(null);
      });
  }, [token]);

  if (!token) {
    return <Login setToken={(t) => {
      localStorage.setItem("token", t);
      setToken(t);
    }} />;
  }

  if (!me) {
    return <div className="flex h-screen w-screen items-center justify-center text-gray-500 text-sm">Loading...</div>;
  }

  const can = (p) => (me.permissions || []).includes(p);

  return (
    <BrowserRouter>
      <div className="flex flex-col h-screen w-screen overflow-hidden bg-gray-50">
        <TopBar setToken={setToken} role={me.role} pages={me.permissions || []} me={me} />
        
        <main className="flex-1 flex flex-col relative overflow-hidden">
          <Routes>
            <Route path="/" element={<MapViewer me={me} />} />
            <Route path="/processor" element={can("processor") ? <DataProcessor /> : <Navigate to="/" />} />
            <Route path="/point" element={can("point") ? <PointProcessor /> : <Navigate to="/" />} />
            <Route path="/map" element={<Navigate to="/" />} />
            <Route path="/dashboard" element={can("dashboard") ? <Dashboard /> : <Navigate to="/" />} />
            <Route path="/users" element={can("users") ? <UserManagement /> : <Navigate to="/" />} />
            <Route path="/db-settings" element={can("database") ? <DbSettings /> : <Navigate to="/" />} />
            <Route path="/import" element={can("import") ? <ImportWorkbench /> : <Navigate to="/" />} />
            <Route path="/requests" element={can("requests") ? <Requests /> : <Navigate to="/" />} />
      <Route path="/mudryia-requests" element={can("mudryia_requests") ? <MudryiaRequests /> : <Navigate to="/" />} />
            <Route path="/tracking" element={can("tracking") ? <TrackingBoard /> : <Navigate to="/" />} />
            <Route path="/lookups" element={can("lookups") ? <LookupsAdmin /> : <Navigate to="/" />} />
            <Route path="/reports" element={can("reports") ? <Reports /> : <Navigate to="/" />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}

export default App;
