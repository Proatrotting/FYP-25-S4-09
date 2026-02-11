import { useState } from "react";
import { BrowserRouter as Router, Routes, Route } from "react-router-dom";
import HomePage from "./pages/HomePage";
import ContactUs from "./pages/ContactUs";
import LoginForm from "./components/LoginForm";
import RegisterForm from "./components/RegisterForm";
import Tutorial from "./pages/Tutorial";
import Testimonials from "./pages/Testimonials";  
import ResetPassword from "./pages/ResetPassword";
import Layout from "./components/Layout";
import UserLayout from "./components/Users/UserLayout";
import UserDashboard from "./pages/Users/UserDashboard";
import ActivityHistory from "./pages/Users/ActivityHistory";
import UserManagement from "./pages/Users/UserManagement";
import AccountManagement from "./pages/Users/AccountManagementService";
import Shared from "./pages/Users/Shared";
import AnonymousDownload from "./pages/Users/AnonymousDownload";
import Bin from "./pages/Users/Bin";
import AdminLayout from "./components/Admin/AdminLayout";
import Dashboard from "./pages/Admin/Dashboard";
import ManageUsers from "./pages/Admin/ManageUsers";
import Nodes from "./pages/Admin/Nodes";

function App() {
  const [showLogin, setShowLogin] = useState(false);
  const [showRegister, setShowRegister] = useState(false);

  const toggleLogin = () => setShowLogin((prev) => !prev);
  const toggleRegister = () => setShowRegister((prev) => !prev);

  // Optional: callback when registration succeeds
  const handleRegisterSuccess = () => {
    setShowRegister(false);
    setShowLogin(true);
  };

  return (
    <Router>
      <Routes>
        {/* PUBLIC PAGES use Layout (with public navbar) */}
        <Route element={<Layout toggleLogin={toggleLogin} />}>
          <Route
            path="/"
            element={
              <HomePage
                toggleLogin={toggleLogin}
                toggleRegister={toggleRegister}
              />
            }
          />
          <Route path="/contact-us" element={<ContactUs />} />
          <Route path="/tutorial" element={<Tutorial/>} />
          <Route path="/testimonials" element={<Testimonials/>} />
        </Route>

        {/* Public share links - handles both files and folders */}
        <Route path="/share/:token" element={<AnonymousDownload />} />
        <Route path="/shares/files/access/:token" element={<AnonymousDownload />} />
        <Route path="/shares/folders/access/:token" element={<AnonymousDownload />} />

        {/* Password Reset Page */}
        <Route path="/reset-password" element={<ResetPassword />} />

        {/* REGISTERED USERS PAGES use UserLayout (with UsersNavBar only) */}
        {/* Dashboard under /user-dashboard */}
        <Route path="/user-dashboard" element={<UserLayout />}>
          <Route index element={<UserDashboard />} />
        </Route>
        {/* Shared under /shared with same layout */}
        <Route path="/shared" element={<UserLayout />}>
          <Route index element={<Shared />} />
        </Route> 
        {/* Activity history under /activity-history with same layout */}
        <Route path="/activity-history" element={<UserLayout />}>
          <Route index element={<ActivityHistory />} />
        </Route>
        {/* User Management under /user-management with same layout */}
        <Route path="/user-management" element={<UserLayout />}>
          <Route index element={<UserManagement />} />
        </Route>  
        {/* Account Management under /account-management with same layout */}
        <Route path="/account-management" element={<UserLayout />}>
          <Route index element={<AccountManagement />} />
        </Route> 
        {/* Recycle Bin under /recycle-bin with same layout */}
        <Route path="/users/bin" element={<UserLayout />}>
          <Route index element={<Bin />} />
        </Route>

        {/* ADMIN USERS PAGES use AdminLayout (with AdminNavBar only) */}
        <Route path="/admin" element={<AdminLayout />}>
          <Route path="dashboard" element={<Dashboard />} />
          <Route path="users" element={<ManageUsers />} />
          <Route path="nodes" element={<Nodes />} />
        </Route>

      </Routes>

      {/* Global modals */}
      {showLogin && <LoginForm toggle={toggleLogin} />}
      {showRegister && (
        <RegisterForm
          onClose={toggleRegister}
          onRegisterSuccess={handleRegisterSuccess}
        />
      )}
    </Router>
  );
}

export default App;
