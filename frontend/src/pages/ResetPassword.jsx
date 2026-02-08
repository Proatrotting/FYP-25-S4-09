import React, { useState, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { resetPassword } from "../services/authService";
import "../styles/LoginForm.css";

function ResetPassword() {
  const [searchParams] = useSearchParams();
  const [token, setToken] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    const tokenParam = searchParams.get("token");
    if (tokenParam) {
      setToken(tokenParam);
    } else {
      setMessage("Invalid or missing reset token.");
    }
  }, [searchParams]);

  const validate = () => {
    if (!newPassword) {
      setMessage("Please enter a new password.");
      return false;
    }
    if (newPassword.length < 8) {
      setMessage("Password must be at least 8 characters long.");
      return false;
    }
    if (newPassword !== confirmPassword) {
      setMessage("Passwords do not match.");
      return false;
    }
    setMessage("");
    return true;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setMessage("");

    if (!token) {
      setMessage("Invalid or missing reset token.");
      return;
    }

    if (!validate()) return;

    setLoading(true);
    try {
      const res = await resetPassword(token, newPassword);
      setSuccess(true);
      setMessage(res.message || "Password reset successful! Redirecting to home...");
      
      // Redirect to home page after 3 seconds
      setTimeout(() => {
        navigate("/");
      }, 3000);
    } catch (err) {
      setMessage(err.message || "Failed to reset password. The link may have expired.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="popup">
      <div className="popup-inner">
        <h2>Reset Password</h2>
        <form onSubmit={handleSubmit} className="login-form">
          <label>
            New Password:
            <input
              type="password"
              value={newPassword}
              onChange={e => setNewPassword(e.target.value)}
              placeholder="Enter new password"
              required
              autoComplete="new-password"
              disabled={!token}
            />
          </label>
          <label>
            Confirm Password:
            <input
              type="password"
              value={confirmPassword}
              onChange={e => setConfirmPassword(e.target.value)}
              placeholder="Confirm new password"
              required
              autoComplete="new-password"
              disabled={!token}
            />
          </label>
          <button type="submit" disabled={loading || !token || success}>
            {loading ? "Resetting..." : success ? "Success!" : "Reset Password"}
          </button>
          {message && (
            <p className={`response ${success ? "success" : ""}`}>
              {message}
            </p>
          )}
        </form>
        <button 
          type="button" 
          className="close-btn" 
          onClick={() => navigate("/")}
          style={{ display: 'block', margin: '0 auto' }}
        >
          Back to Home
        </button>
      </div>
    </div>
  );
}

export default ResetPassword;
