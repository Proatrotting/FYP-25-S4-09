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

      <nav className="admin-nav-links" onClick={handleNavClick}>
        <NavLink to="/admin/dashboard" className={({ isActive }) => "admin-nav-item" + (isActive ? " admin-nav-item.active" : "") } >
            Dashboard
        </NavLink>
        <NavLink to="/admin/users" className={({ isActive }) => "admin-nav-item" + (isActive ? " admin-nav-item.active" : "") } >
            Manage Users
        </NavLink>
        <NavLink to="/admin/nodes" className={({ isActive }) => "admin-nav-item" + (isActive ? " admin-nav-item.active" : "") } >
            Nodes
        </NavLink>
      </nav>

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