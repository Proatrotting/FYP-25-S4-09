import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { loginUser, forgotPassword } from "../services/authService";
import { setAccessToken, setCurrentUser } from "../services/UserService";
import "../styles/LoginForm.css";

function isEmail(str) {
  // Simple email regex
  return /^[\w-.]+@([\w-]+\.)+[\w-]{2,4}$/.test(str);
}

function LoginForm({ toggle }) {
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [selectedRole, setSelectedRole] = useState("USER"); // Default to USER
  const [formMessage, setFormMessage] = useState(""); // only for form validation/login
  const [showSuccessAlert, setShowSuccessAlert] = useState(false);
  const [loading, setLoading] = useState(false);

  // forgot password state
  const [showForgot, setShowForgot] = useState(false);
  const [forgotEmail, setForgotEmail] = useState("");
  const [forgotMessage, setForgotMessage] = useState("");
  const [forgotLoading, setForgotLoading] = useState(false);

  const navigate = useNavigate();

  // Helper: Validate identifier before submission
  const validate = () => {
    if (!identifier) {
      setFormMessage("Please enter your username or email.");
      return false;
    }
    if (identifier.includes("@") && !isEmail(identifier)) {
      setFormMessage("Please enter a valid email address.");
      return false;
    }
    if (!password) {
      setFormMessage("Please enter your password.");
      return false;
    }
    setFormMessage("");
    return true;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setFormMessage("");
    if (!validate()) return;

    setLoading(true);
    try {
      const response = await loginUser({
        username_or_email: identifier,
        password,
        selected_role: selectedRole, // Optional - for UI purposes, backend auto-determines
      });

      // response matches TokenResponse from backend:
      // { access_token, token_type, account_id, username, account_type }
      const token = response.access_token;
      const accountType = response.account_type;
      const user = {
        account_id: response.account_id,
        username: response.username,
        account_type: response.account_type,
      };

      // Store token and user for later API calls/dashboard
      setAccessToken(token);
      setCurrentUser(user);

      // Optional: keep your existing values
      localStorage.setItem("username", response.username);
      localStorage.setItem("role", accountType);
      setShowSuccessAlert(true);
      setTimeout(() => {
        setShowSuccessAlert(false);
        // Redirect based on actual account_type from backend response
        if (accountType === "SYSADMIN") {
          navigate("/Admin/Admin-Dashboard");
        } else {
          // FREE and PAID both go to user dashboard
          navigate("/user-dashboard");
        }
        
        toggle && toggle();
      }, 1200);
    } catch (err) {
      setFormMessage(err.message || "Login failed. Please try again.");
      setTimeout(() => setFormMessage(""), 3500);
    } finally {
      setLoading(false);
    }
  };

  const handleForgotSubmit = async (e) => {
    e.preventDefault();
    setForgotMessage("");

    if (!forgotEmail || !isEmail(forgotEmail)) {
      setForgotMessage("Please enter a valid email address.");
      return;
    }

    setForgotLoading(true);
    try {
      const res = await forgotPassword(forgotEmail);
      // Backend always returns a generic message
      setForgotMessage(res.message || "If this email exists, a reset link has been sent.");
      // Optionally clear field
      // setForgotEmail("");
    } catch (err) {
      setForgotMessage(err.message || "Failed to process password reset.");
    } finally {
      setForgotLoading(false);
    }
  };

  return (
    <div className="popup">
      <div className="popup-inner">
        <h2>Login</h2>
        <form onSubmit={handleSubmit} className="login-form">
          <label>
            Username or Email:
            <input
              type="text"
              value={identifier}
              onChange={e => setIdentifier(e.target.value)}
              placeholder="Enter username or email"
              required
              autoComplete="username"
            />
          </label>
          <label>
            Password:
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
              autoComplete="current-password"
            />
          </label>
          <label>
            Select Role:
            <select
              value={selectedRole}
              onChange={e => setSelectedRole(e.target.value)}
            >
              <option value="USER">User</option>
              <option value="SYSADMIN">Sysadmin</option>
            </select>
          </label>
          <button type="submit" disabled={loading}>
            {loading ? "Logging in..." : "Login"}
          </button>
          {formMessage && <p className="response">{formMessage}</p>}

          {/* Forgot password trigger */}
          <button
            type="button"
            className="link-button"
            onClick={() => setShowForgot(prev => !prev)}
          >
            {showForgot ? "Hide forgot password" : "Forgot Password?"}
          </button>

          {formMessage && <p className="response">{formMessage}</p>}
        </form>

        {/* Forgot password mini-form */}
        {showForgot && (
          <form onSubmit={handleForgotSubmit} className="forgot-form">
            <label>
              Enter your email:
              <input
                type="email"
                value={forgotEmail}
                onChange={e => setForgotEmail(e.target.value)}
                placeholder="your-email@example.com"
              />
            </label>
            <button type="submit" disabled={forgotLoading}>
              {forgotLoading ? "Sending..." : "Send reset link"}
            </button>
            {forgotMessage && <p className="response">{forgotMessage}</p>}
          </form>
        )} 
        <button type="button" className="close-btn" onClick={toggle}>
          Close
        </button>
        {showSuccessAlert && (
          <div className="custom-alert">
            <div className="custom-alert-content">
              <h3>Login Successful</h3>
              <p>Welcome <strong>{identifier}</strong>!</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default LoginForm;
