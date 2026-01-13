import { useState } from "react";
import { getUserActivity } from "../../services/AdminService";
import "../../styles/Admin/Dashboard.css";

const ACTION_TYPE_OPTIONS = [
  { value: "", label: "All Actions" },
  { value: "LOGIN", label: "Login" },
  { value: "LOGOUT", label: "Logout" },
  { value: "FILE_UPLOAD", label: "File Upload" },
  { value: "FILE_DOWNLOAD", label: "File Download" },
  { value: "FILE_DELETE", label: "File Delete" },
  { value: "FILE_SHARE", label: "File Share" },
  { value: "ACCOUNT_UPDATE", label: "Account Update" },
];

const LIMIT = 20;

function Dashboard() {
  const [activities, setActivities] = useState([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Filters
  const [usernameFilter, setUsernameFilter] = useState("");
  const [actionTypeFilter, setActionTypeFilter] = useState("");

  // Fetch activities
  const fetchActivities = async (newOffset = 0) => {
    if (!usernameFilter.trim()) {
      setActivities([]);
      setTotal(0);
      setError(null);
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const data = await getUserActivity({
        username: usernameFilter.trim(),
        action_type: actionTypeFilter || undefined,
        limit: LIMIT,
        offset: newOffset,
      });

      setActivities(data.activities || []);
      setTotal(data.total || 0);
      setOffset(newOffset);
    } catch (err) {
      setError(err.message || "Failed to load activities");
      setActivities([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  };

  // Handle search button click
  const handleSearch = (e) => {
    e.preventDefault();
    setOffset(0);
    fetchActivities(0);
  };

  // Pagination handlers
  const handlePrevPage = () => {
    const newOffset = Math.max(0, offset - LIMIT);
    fetchActivities(newOffset);
  };

  const handleNextPage = () => {
    const newOffset = offset + LIMIT;
    if (newOffset < total) {
      fetchActivities(newOffset);
    }
  };

  const currentPage = Math.floor(offset / LIMIT) + 1;
  const totalPages = Math.ceil(total / LIMIT);

  // Format datetime for display
  const formatDateTime = (isoString) => {
    if (!isoString) return "—";
    const date = new Date(isoString);
    return date.toLocaleString();
  };

  // Get badge class for action type
  const getActionBadgeClass = (actionType) => {
    const type = actionType?.toUpperCase() || "";
    if (type.includes("LOGIN")) return "badge-login";
    if (type.includes("LOGOUT")) return "badge-logout";
    if (type.includes("UPLOAD")) return "badge-upload";
    if (type.includes("DOWNLOAD")) return "badge-download";
    if (type.includes("DELETE")) return "badge-delete";
    if (type.includes("SHARE")) return "badge-share";
    return "badge-default";
  };

  return (
    <div className="admin-dashboard">
      <h1 className="dashboard-title">Activity Dashboard</h1>

      {/* Search / Filter Form */}
      <form className="activity-filters" onSubmit={handleSearch}>
        <div className="filter-group">
          <label htmlFor="username-filter">Username</label>
          <input
            id="username-filter"
            type="text"
            placeholder="Enter username"
            value={usernameFilter}
            onChange={(e) => setUsernameFilter(e.target.value)}
          />
        </div>

        <div className="filter-group">
          <label htmlFor="action-type-filter">Action Type</label>
          <select
            id="action-type-filter"
            value={actionTypeFilter}
            onChange={(e) => setActionTypeFilter(e.target.value)}
          >
            {ACTION_TYPE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        <button type="submit" className="search-btn" disabled={loading}>
          {loading ? "Searching..." : "Search"}
        </button>
      </form>

      {/* Error Message */}
      {error && <div className="activity-error">{error}</div>}

      {/* Results Info */}
      {!error && total > 0 && (
        <div className="activity-info">
          Showing {offset + 1}–{Math.min(offset + LIMIT, total)} of {total} activities
        </div>
      )}

      {/* Activity Table */}
      {activities.length > 0 && (
        <div className="activity-table-wrapper">
          <table className="activity-table">
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Action</th>
                <th>Resource Type</th>
                <th>Resource ID</th>
                <th>IP Address</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {activities.map((activity) => (
                <tr key={activity.activity_id}>
                  <td className="cell-timestamp">
                    {formatDateTime(activity.created_at)}
                  </td>
                  <td>
                    <span
                      className={`action-badge ${getActionBadgeClass(
                        activity.action_type
                      )}`}
                    >
                      {activity.action_type}
                    </span>
                  </td>
                  <td>{activity.resource_type || "—"}</td>
                  <td className="cell-resource-id">
                    {activity.resource_id || "—"}
                  </td>
                  <td>{activity.ip_address || "—"}</td>
                  <td className="cell-details">
                    {activity.details
                      ? JSON.stringify(activity.details).slice(0, 50) +
                        (JSON.stringify(activity.details).length > 50
                          ? "..."
                          : "")
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Empty State */}
      {!loading && !error && activities.length === 0 && usernameFilter && (
        <div className="activity-empty">No activities found for this user.</div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="activity-pagination">
          <button
            className="pagination-btn"
            onClick={handlePrevPage}
            disabled={offset === 0 || loading}
          >
            ← Previous
          </button>
          <span className="pagination-info">
            Page {currentPage} of {totalPages}
          </span>
          <button
            className="pagination-btn"
            onClick={handleNextPage}
            disabled={offset + LIMIT >= total || loading}
          >
            Next →
          </button>
        </div>
      )}
    </div>
  );
}

export default Dashboard;