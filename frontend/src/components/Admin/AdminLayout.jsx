import React from "react";
import { Outlet } from "react-router-dom";
import AdminNavBar from "./AdminNavBar";

const AdminLayout = () => {
  return (
    <div className="admin-layout">
      <AdminNavBar />
      <main className="admin-main-content">
        <Outlet />
      </main>
    </div>
  );
};

export default AdminLayout;