import React, { useEffect, useState } from "react";
import {
  listNodes,
  markNodeActive,
  markNodeInactive,
} from "../../services/AdminService";
import "../../styles/Admin/Nodes.css";

function Nodes() {
  const [nodes, setNodes] = useState([]);
  const [loading, setLoading] = useState(false);
  const [actionLoadingId, setActionLoadingId] = useState(null);
  const [error, setError] = useState(null);

  const fetchNodes = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listNodes();
      setNodes(data || []);
    } catch (err) {
      setError(err.message || "Failed to load nodes");
      setNodes([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchNodes();
  }, []);

  const formatDateTime = (value) => {
    if (!value) return "—";
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return String(value);
    return d.toLocaleString();
  };

  const getStatusBadgeClass = (isActive) =>
    isActive ? "node-status-badge active" : "node-status-badge inactive";

  const getRoleBadgeClass = (role) =>
    `node-role-badge ${
      (role || "").toUpperCase() === "MASTER" ? "master" : "worker"
    }`;

  const handleToggleNode = async (node) => {
    try {
      setActionLoadingId(node.node_id);
      if (node.is_active) {
        await markNodeInactive(node.node_id);
      } else {
        await markNodeActive(node.node_id);
      }
      await fetchNodes();
    } catch (err) {
      setError(err.message || "Failed to update node status");
    } finally {
      setActionLoadingId(null);
    }
  };

  const totalNodes = nodes.length;
  const activeNodes = nodes.filter((n) => n.is_active).length;
  const inactiveNodes = totalNodes - activeNodes;

  return (
    <div className="admin-nodes">
      <div className="nodes-header">
        <h1 className="nodes-title">Nodes Status</h1>
        <button
          type="button"
          className="nodes-refresh-btn"
          onClick={fetchNodes}
          disabled={loading}
        >
          {loading ? "Refreshing..." : "Refresh"}
        </button>
      </div>

      {/* Summary cards */}
      <div className="nodes-summary">
        <div className="nodes-summary-card total">
          <span className="summary-label">Total Nodes</span>
          <span className="summary-value">{totalNodes}</span>
        </div>
        <div className="nodes-summary-card active">
          <span className="summary-label">Active</span>
          <span className="summary-value">{activeNodes}</span>
        </div>
        <div className="nodes-summary-card inactive">
          <span className="summary-label">Inactive</span>
          <span className="summary-value">{inactiveNodes}</span>
        </div>
      </div>

      {error && <div className="nodes-error">{error}</div>}

      <div className="nodes-table-wrapper">
        <table className="nodes-table">
          <thead>
            <tr>
              <th>Node ID</th>
              <th>Role</th>
              <th>Status</th>
              <th>Last Heartbeat</th>
              <th>Controls</th>
            </tr>
          </thead>
          <tbody>
            {nodes.length === 0 && !loading && (
              <tr>
                <td colSpan={5} className="nodes-empty">
                  No nodes found.
                </td>
              </tr>
            )}
            {nodes.map((node) => (
              <tr key={node.node_id}>
                <td className="cell-node-id">{node.node_id}</td>
                <td>
                  <span className={getRoleBadgeClass(node.node_role)}>
                    {node.node_role || "UNKNOWN"}
                  </span>
                </td>
                <td>
                  <span className={getStatusBadgeClass(node.is_active)}>
                    {node.is_active ? "Active" : "Inactive"}
                  </span>
                </td>
                <td className="cell-heartbeat">
                  {formatDateTime(node.heartbeat_at)}
                </td>
                <td className="cell-controls">
                  <button
                    type="button"
                    className="node-action-btn toggle"
                    onClick={() => handleToggleNode(node)}
                    disabled={actionLoadingId === node.node_id}
                  >
                    {node.is_active ? "Mark Inactive" : "Mark Active"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default Nodes;