import { useState, useRef, useEffect } from "react";
import { BrowserRouter, Routes, Route, Link, useLocation, Navigate } from "react-router-dom";
import MapViewer from "./pages/MapViewer";
import DataProcessor from "./pages/DataProcessor";
import Dashboard from "./pages/Dashboard";
import Login from "./pages/Login";
import UserManagement from "./pages/UserManagement";
import DbSettings from "./pages/DbSettings";
import axios from "axios";
import { LayoutDashboard, Users, LogOut, User as UserIcon, Map as MapIcon, Database, Server } from "lucide-react";

function TopBar({ setToken, role, pages }) {
  const [showDropdown, setShowDropdown] = useState(false);
  const dropdownRef = useRef(null);
  const location = useLocation();

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
      <div className="relative" ref={dropdownRef}>
        <button 
          onClick={() => setShowDropdown(!showDropdown)}
          className="flex items-center justify-center w-9 h-9 rounded-full bg-blue-600 text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-slate-900 transition"
        >
          <UserIcon className="w-4 h-4" />
        </button>
        
        {showDropdown && (
          <div className="absolute right-0 mt-2 w-48 bg-white rounded-md shadow-lg py-1 border border-gray-200 z-50">
                        <div className="px-4 py-2 border-b border-gray-100">
              <p className="text-sm font-medium text-gray-900 capitalize">{role} Account</p>
            </div>
            {pages.includes('processor') && (
              <Link to="/processor" onClick={() => setShowDropdown(false)} className="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 flex items-center transition-colors">
                <Database className="w-4 h-4 mr-2" />
                Data Processor
              </Link>
            )}
            {pages.includes('dashboard') && (
              <Link to="/dashboard" onClick={() => setShowDropdown(false)} className="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 flex items-center transition-colors">
                <LayoutDashboard className="w-4 h-4 mr-2" />
                Dashboard
              </Link>
            )}
            {pages.includes('users') && (
              <Link to="/users" onClick={() => setShowDropdown(false)} className="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 flex items-center transition-colors">
                <Users className="w-4 h-4 mr-2" />
                Users
              </Link>
            )}
            {pages.includes('database') && (
              <Link to="/db-settings" onClick={() => setShowDropdown(false)} className="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 flex items-center transition-colors">
                <Server className="w-4 h-4 mr-2" />
                Database
              </Link>
            )}
            {pages.length > 0 && (
              <div className="border-t border-gray-100 my-1"></div>
            )}
            <button
              onClick={() => { localStorage.removeItem("token"); setToken(null); }}
              className="w-full text-left px-4 py-2 text-sm text-red-600 hover:bg-red-50 flex items-center transition-colors"
            >
              <LogOut className="w-4 h-4 mr-2" />
              Logout
            </button>
          </div>
        )}
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
        <TopBar setToken={setToken} role={me.role} pages={me.permissions || []} />
        
        <main className="flex-1 flex flex-col relative overflow-hidden">
          <Routes>
            <Route path="/" element={<MapViewer />} />
            <Route path="/processor" element={can("processor") ? <DataProcessor /> : <Navigate to="/" />} />
            <Route path="/map" element={<Navigate to="/" />} />
            <Route path="/dashboard" element={can("dashboard") ? <Dashboard /> : <Navigate to="/" />} />
            <Route path="/users" element={can("users") ? <UserManagement /> : <Navigate to="/" />} />
            <Route path="/db-settings" element={can("database") ? <DbSettings /> : <Navigate to="/" />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}

export default App;
