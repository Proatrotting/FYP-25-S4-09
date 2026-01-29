import React, { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import '../styles/NavBar.css';
import ShardLogo from './Shard_Logo.png'; 


function NavBar({ toggleLogin }) {
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);

  const handleNavClick = () => {
    // Close menu after clicking a link on mobile
    setMenuOpen(false);
  };
  
  return (
    <nav className={`navbar ${menuOpen ? "menu-open" : ""}`}>
      <div className="logo">
        <img src={ShardLogo} alt="App Logo" className="logo-img" />
      </div>
      <button
        className="hamburger"
        onClick={() => setMenuOpen((prev) => !prev)}
        aria-label="Toggle navigation"
      >
        <span className="bar" />
        <span className="bar" />
        <span className="bar" />
      </button>
      <ul className="nav-links">
        <li className={`nav-item${location.pathname === "/" ? " active" : ""}`} onClick={handleNavClick}>
          <Link to="/">Home</Link>
        </li>
        <li className={`nav-item${location.pathname === "/contact-us" ? " active" : ""}`} onClick={handleNavClick}>
          <Link to="/contact-us">Contact Us</Link>
        </li>
        <li className="nav-item" onClick={handleNavClick}>Tutorial</li>
        <li className={`nav-item${location.pathname === "/testimonials" ? " active" : ""}`} onClick={handleNavClick}>
          <Link to="/testimonials">Testimonials</Link>
        </li>
      </ul>
      <button className="login-btn" onClick={() => {
          toggleLogin();
          setMenuOpen(false); // close menu after login click on mobile
        }}>Log In</button>
    </nav>
  );
}

export default NavBar;
