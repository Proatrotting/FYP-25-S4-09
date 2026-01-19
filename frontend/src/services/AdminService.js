import { API_BASE_URL, authFetch } from "./UserService";

/**
 * Fetch user activity as sysadmin.
 * @param {Object} params - Query parameters
 * @param {string} [params.account_id] - Target account ID
 * @param {string} [params.username] - Target username (used if account_id not provided)
 * @param {string} [params.action_type] - Filter by action type (e.g., LOGIN, FILE_UPLOAD)
 * @param {number} [params.limit=50] - Number of activities to return
 * @param {number} [params.offset=0] - Number of activities to skip
 * @returns {Promise<Object>} - Activity response with activities[], total, limit, offset
 */
export async function getUserActivity({
  account_id,
  username,
  action_type,
  limit = 50,
  offset = 0,
} = {}) {
  const queryParams = new URLSearchParams();

  if (account_id) queryParams.append("account_id", account_id);
  if (username) queryParams.append("username", username);
  if (action_type) queryParams.append("action_type", action_type);
  queryParams.append("limit", limit.toString());
  queryParams.append("offset", offset.toString());

  const url = `${API_BASE_URL}/sysadmin/activity?${queryParams.toString()}`;

  const response = await authFetch(url, { method: "GET" });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || "Failed to fetch user activity");
  }

  return response.json();
}

export async function listUsers({
  username,
  email,
  account_type,
  account_status,
  limit = 50,
  offset = 0,
} = {}) {
  const params = new URLSearchParams();

  if (username) params.append("username", username);
  if (email) params.append("email", email);
  if (account_type) params.append("account_type", account_type);
  if (account_status) params.append("account_status", account_status);
  params.append("limit", String(limit));
  params.append("offset", String(offset));

  const url = `${API_BASE_URL}/sysadmin/accounts?${params.toString()}`;

  const response = await authFetch(url, { method: "GET" });

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || "Failed to fetch users");
  }

  return response.json();
}

export async function deactivateAccount({ account_id, username }) {
  const url = `${API_BASE_URL}/sysadmin/accounts/deactivate`;
  const body = JSON.stringify({ account_id, username });

  const response = await authFetch(url, {
    method: "POST",
    body,
  });

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || "Failed to deactivate account");
  }

  return response.json();
}

export async function activateAccount({ account_id, username }) {
  const url = `${API_BASE_URL}/sysadmin/accounts/activate`;
  const body = JSON.stringify({ account_id, username });

  const response = await authFetch(url, {
    method: "POST",
    body,
  });

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || "Failed to activate account");
  }

  return response.json();
}

export async function deleteAccount({ account_id, username }) {
  const params = new URLSearchParams();
  if (account_id) params.append("account_id", account_id);
  if (username) params.append("username", username);

  const url = `${API_BASE_URL}/sysadmin/accounts?${params.toString()}`;

  const response = await authFetch(url, {
    method: "DELETE",
  });

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || "Failed to delete account");
  }

  return response.json();
}

export async function promoteToSysadmin({ account_id, username }) {
  const url = `${API_BASE_URL}/sysadmin/accounts/promote-to-sysadmin`;
  const body = JSON.stringify({ account_id, username });

  const response = await authFetch(url, {
    method: "POST",
    body,
  });

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || "Failed to promote to sysadmin");
  }

  return response.json();
}

// ---------- Nodes status ----------

export async function listNodes() {
  const url = `${API_BASE_URL}/sysadmin/nodes`;

  const response = await authFetch(url, { method: "GET" });

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || "Failed to fetch nodes");
  }

  return response.json();
}

export async function markNodeActive(node_id) {
  const url = `${API_BASE_URL}/sysadmin/nodes/mark-active`;
  const body = JSON.stringify({ node_id });

  const response = await authFetch(url, {
    method: "POST",
    body,
  });

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || "Failed to mark node active");
  }

  return response.json();
}

export async function markNodeInactive(node_id) {
  const url = `${API_BASE_URL}/sysadmin/nodes/mark-inactive`;
  const body = JSON.stringify({ node_id });

  const response = await authFetch(url, {
    method: "POST",
    body,
  });

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || "Failed to mark node inactive");
  }

  return response.json();
}