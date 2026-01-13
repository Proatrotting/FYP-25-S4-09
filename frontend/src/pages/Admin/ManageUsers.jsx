import { useEffect, useState } from "react";
import {
  listUsers,
  deactivateAccount,
  activateAccount,
  deleteAccount,
  promoteToSysadmin,
} from "../../services/AdminService";
import "../../styles/Admin/ManageUsers.css";

const ACCOUNT_TYPE_OPTIONS = [
  { value: "", label: "All Types" },
  { value: "FREE", label: "Free" },
  { value: "PAID", label: "Paid" },
  { value: "SYSADMIN", label: "Sysadmin" },
];

const ACCOUNT_STATUS_OPTIONS = [
  { value: "", label: "All Statuses" },
  { value: "ACTIVE", label: "Active" },
  { value: "INACTIVE", label: "Inactive" },
];

const LIMIT = 50; // backend already supports limit/offset even if response has no total count

function ManageUsers() {
  const [users, setUsers] = useState([]);

  // filters
  const [usernameFilter, setUsernameFilter] = useState("");
  const [emailFilter, setEmailFilter] = useState("");
  const [accountTypeFilter, setAccountTypeFilter] = useState("");
  const [accountStatusFilter, setAccountStatusFilter] = useState("");

  // ui state
  const [loading, setLoading] = useState(false);
  const [actionLoadingId, setActionLoadingId] = useState(null);
  const [error, setError] = useState(null);

  // pagination (simple next/prev based on LIMIT and whether we got a full page)
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);

  const fetchUsers = async (newOffset = 0) => {
    setLoading(true);
    setError(null);

    try {
      const data = await listUsers({
        username: usernameFilter.trim() || undefined,
        email: emailFilter.trim() || undefined,
        account_type: accountTypeFilter || undefined,
        account_status: accountStatusFilter || undefined,
        limit: LIMIT,
        offset: newOffset,
      });

      setUsers(data || []);
      setOffset(newOffset);
      setHasMore((data || []).length === LIMIT);
    } catch (err) {
      setError(err.message || "Failed to load users");
      setUsers([]);
      setHasMore(false);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    // initial load
    fetchUsers(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSearch = (e) => {
    e.preventDefault();
    fetchUsers(0);
  };

  const handlePrevPage = () => {
    if (offset === 0) return;
    const newOffset = Math.max(0, offset - LIMIT);
    fetchUsers(newOffset);
  };

  const handleNextPage = () => {
    if (!hasMore) return;
    const newOffset = offset + LIMIT;
    fetchUsers(newOffset);
  };

  const formatDateTime = (isoString) => {
    if (!isoString) return "—";
    const d = new Date(isoString);
    return d.toLocaleString();
  };

  const getTypeBadgeClass = (type) => {
    const t = (type || "").toUpperCase();
    if (t === "SYSADMIN") return "type-badge type-sysadmin";
    if (t === "PAID") return "type-badge type-paid";
    return "type-badge type-free";
  };

  const getStatusBadgeClass = (status) => {
    const s = (status || "").toUpperCase();
    if (s === "ACTIVE") return "status-badge status-active";
    if (s === "INACTIVE") return "status-badge status-inactive";
    return "status-badge";
  };

  const performAction = async (account, actionFn, successMessage) => {
    try {
      setActionLoadingId(account.account_id);
      await actionFn({ account_id: account.account_id });
      // reload current page
      await fetchUsers(offset);
      // optional: you could show a toast/snackbar here
      // eslint-disable-next-line no-console
      console.log(successMessage);
    } catch (err) {
      setError(err.message || "Action failed");
    } finally {
      setActionLoadingId(null);
    }
  };

  const handleToggleStatus = (account) => {
    const isActive = (account.status || "").toUpperCase() === "ACTIVE";
    if (isActive) {
      performAction(account, deactivateAccount, "Account deactivated");
    } else {
      performAction(account, activateAccount, "Account activated");
    }
  };

  const handlePromote = (account) => {
    performAction(account, promoteToSysadmin, "User promoted to SYSADMIN");
  };

  const handleDelete = (account) => {
    const ok = window.confirm(
      `Delete account "${account.username}"? This cannot be undone.`
    );
    if (!ok) return;
    performAction(account, deleteAccount, "Account deleted");
  };

  return (
    <div className="admin-manage-users">
      <h1 className="manage-users-title">Manage Users</h1>

      {/* Filters */}
      <form className="users-filters" onSubmit={handleSearch}>
        <div className="filter-group">
          <label htmlFor="username-filter">Username</label>
          <input
            id="username-filter"
            type="text"
            placeholder="Search by username"
            value={usernameFilter}
            onChange={(e) => setUsernameFilter(e.target.value)}
          />
        </div>

        <div className="filter-group">
          <label htmlFor="email-filter">Email</label>
          <input
            id="email-filter"
            type="text"
            placeholder="Search by email"
            value={emailFilter}
            onChange={(e) => setEmailFilter(e.target.value)}
          />
        </div>

        <div className="filter-group">
          <label htmlFor="type-filter">Account Type</label>
          <select
            id="type-filter"
            value={accountTypeFilter}
            onChange={(e) => setAccountTypeFilter(e.target.value)}
          >
            {ACCOUNT_TYPE_OPTIONS.map((opt) => (
              <option key={opt.value || "all"} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        <div className="filter-group">
          <label htmlFor="status-filter">Status</label>
          <select
            id="status-filter"
            value={accountStatusFilter}
            onChange={(e) => setAccountStatusFilter(e.target.value)}
          >
            {ACCOUNT_STATUS_OPTIONS.map((opt) => (
              <option key={opt.value || "all"} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        <button type="submit" className="users-search-btn" disabled={loading}>
          {loading ? "Loading..." : "Apply Filters"}
        </button>
      </form>

      {/* Error */}
      {error && <div className="users-error">{error}</div>}

      {/* Table */}
      <div className="users-table-wrapper">
        <table className="users-table">
          <thead>
            <tr>
              <th>Username</th>
              <th>Email</th>
              <th>Type</th>
              <th>Status</th>
              <th>Created</th>
              <th className="col-actions">Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.length === 0 && !loading && (
              <tr>
                <td colSpan={6} className="users-empty">
                  No users found.
                </td>
              </tr>
            )}
            {users.map((user) => {
              const isActive =
                (user.status || "").toUpperCase() === "ACTIVE";
              const isSysadmin =
                (user.account_type || "").toUpperCase() === "SYSADMIN";
              const busy = actionLoadingId === user.account_id;

              return (
                <tr key={user.account_id}>
                  <td className="cell-username">{user.username}</td>
                  <td className="cell-email">{user.email}</td>
                  <td>
                    <span className={getTypeBadgeClass(user.account_type)}>
                      {user.account_type}
                    </span>
                  </td>
                  <td>
                    <span className={getStatusBadgeClass(user.status)}>
                      {user.status}
                    </span>
                  </td>
                  <td className="cell-created">
                    {formatDateTime(user.created_at)}
                  </td>
                  <td className="cell-actions">
                    <button
                      type="button"
                      className="user-action-btn subtle"
                      onClick={() => handleToggleStatus(user)}
                      disabled={busy}
                    >
                      {isActive ? "Deactivate" : "Activate"}
                    </button>
                    <button
                      type="button"
                      className="user-action-btn primary"
                      onClick={() => handlePromote(user)}
                      disabled={busy || isSysadmin}
                      title={
                        isSysadmin
                          ? "Already SYSADMIN"
                          : "Promote to SYSADMIN"
                      }
                    >
                      Promote
                    </button>
                    <button
                      type="button"
                      className="user-action-btn danger"
                      onClick={() => handleDelete(user)}
                      disabled={busy}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="users-pagination">
        <button
          type="button"
          className="users-page-btn"
          onClick={handlePrevPage}
          disabled={offset === 0 || loading}
        >
          ← Previous
        </button>
        <span className="users-page-info">
          Showing {offset + 1}–
          {offset + users.length} users
        </span>
        <button
          type="button"
          className="users-page-btn"
          onClick={handleNextPage}
          disabled={!hasMore || loading}
        >
          Next →
        </button>
      </div>
    </div>
  );
}

export default ManageUsers;