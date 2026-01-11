import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { getCurrentUser, clearAuth } from "../../services/UserService";
import "../../styles/Admin/AdminNavBar.css";
import ShardLogo from "../Shard_Logo.png";

function AdminNavBar() {
  const [menuOpen, setMenuOpen] = useState(false);

  const navigate = useNavigate();

  const user = getCurrentUser();
  const username = user?.username || "Admin";

  const handleLogout = () => {
    clearAuth();
    navigate("/");
  };

  const handleNavClick = () => {
    setMenuOpen(false);
  };

  return (
    <nav className={`admin-navbar ${menuOpen ? "menu-open" : ""}`}>
      <div className="admin-navbar-left">
        <div className="admin-logo">
          <img src={ShardLogo} alt="Admin Logo" className="admin-logo-img" />
          <span className="admin-title">Admin Panel</span>
        </div>
      </div>

      <button
        className="admin-hamburger"
        onClick={() => setMenuOpen((prev) => !prev)}
        aria-label="Toggle navigation"
      >
        <span className="bar" />
        <span className="bar" />
        <span className="bar" />
      </button>

      <ul className="admin-nav-links">
        <li className={`admin-nav-item${location.pathname === "/admin/dashboard" ? " active" : ""}`} onClick={handleNavClick}>
          <Link to="/admin/dashboard">Dashboard</Link>
        </li>
        <li className={`admin-nav-item${location.pathname === "/admin/users" ? " active" : ""}`} onClick={handleNavClick}>
          <Link to="/admin/users">Manage Users</Link>
        </li>
        <li className={`admin-nav-item${location.pathname === "/admin/nodes" ? " active" : ""}`} onClick={handleNavClick}>
          <Link to="/admin/nodes">Nodes</Link>
        </li>
      </ul>

      <div className="admin-header-right">
        <span className="admin-welcome-text">
          Welcome, {username}
        </span>
        <button
          type="button"
          className="admin-logout-button"
          onClick={handleLogout}
        >
          Log out
        </button>
      </div>
    </nav>
  );
}

export default AdminNavBar;