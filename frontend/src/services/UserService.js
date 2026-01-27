export const API_BASE_URL = process.env.REACT_APP_API_BASE_URL;
const TOKEN_KEY = "accessToken";
const USER_KEY = "user";

// ---------- Token + user helpers ----------
export function getAccessToken() {
  return localStorage.getItem(TOKEN_KEY) || null;
}

export function setAccessToken(token) {
  if (token) {
    localStorage.setItem(TOKEN_KEY, token);
  } else {
    localStorage.removeItem(TOKEN_KEY);
  }
}

export function setCurrentUser(user) {
  if (user) {
    localStorage.setItem(USER_KEY, JSON.stringify(user));
  } else {
    localStorage.removeItem(USER_KEY);
  }
}

export function getCurrentUser() {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

// central logout
export function logout() {
  clearAuth();
  window.location.href = "/"; // or use react-router navigation
}

// generic request wrapper
export async function authFetch(url, options = {}) {
  const token = getAccessToken();

  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };

  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const response = await fetch(url, { ...options, headers });

  if (response.status === 401) {
    // token invalid or expired -> force logout
    logout();
    throw new Error("Session expired. Please log in again.");
  }

  return response;
}

// ---------- Folder download ----------
export async function downloadFolderZip(folderId) {
  const url = `${API_BASE_URL}/files/download-folder/${folderId}`;

  const response = await authFetch(url, {
    method: "GET",
    // IMPORTANT: do NOT set "Content-Type": "application/json" here;
    // authFetch already sets JSON; we override below.
    headers: {
      // Remove/override JSON header for binary data
    },
  });

  if (!response.ok) {
    let errorText = "Failed to download folder";
    try {
      const errData = await response.json();
      errorText = errData.detail || errData.message || errorText;
    } catch {
      // ignore JSON parse error for non-JSON responses
    }
    throw new Error(errorText);
  }

  // Get filename from Content-Disposition if present
  const disposition = response.headers.get("Content-Disposition");
  let filename = "folder.zip";
  if (disposition) {
    const match = disposition.match(
      /filename\*?=['"]?(?:UTF-\d''|)([^;'"]+)['"]?/i
    );
    if (match && match[1]) {
      filename = decodeURIComponent(match[1]);
    }
  }

  const blob = await response.blob(); // ZIP binary [web:35][web:42][web:45]
  const urlObject = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = urlObject;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(urlObject);
}

// ---------- Folder upload ----------
export async function uploadFolderApi({ folderName, files, parentFolderId = null, erasureId = "MEDIUM" }) {
  // files: FileList or array of File objects from an <input webkitdirectory>
  if (!files || files.length === 0) {
    throw new Error("No files selected");
  }

  // Build files array in backend's expected shape
  const fileEntries = await Promise.all(
    Array.from(files).map(async (file) => {
      const arrayBuffer = await file.arrayBuffer();
      const base64Data = btoa(
        String.fromCharCode(...new Uint8Array(arrayBuffer))
      );

      // Use webkitRelativePath to get relative_path (fall back to file.name)
      const relativePath =
        file.webkitRelativePath && file.webkitRelativePath.length > 0
          ? file.webkitRelativePath
          : file.name;

      return {
        filename: file.name,
        data: base64Data,
        relative_path: relativePath, // matches backend model
        content_type: file.type || "application/octet-stream",
      };
    })
  );

  const body = {
    folder_name: folderName,
    files: fileEntries,
    parent_folder_id: parentFolderId,
    erasure_id: erasureId,
  };

  const response = await authFetch(`${API_BASE_URL}/files/upload-folder`, {
    method: "POST",
    body: JSON.stringify(body),
  });

  const result = await response.json();
  if (!response.ok) {
    throw new Error(
      result.detail || result.message || "Failed to upload folder"
    );
  }

  return result; // FolderUploadResponse
}

// ---------- File upload ----------
export async function uploadFile({ file, folderId = null, erasureId = "MEDIUM" }, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${API_BASE_URL}/files/upload`);

    const formData = new FormData();
    formData.append('file', file);
    formData.append('filename', file.name);
    formData.append('folder_id', folderId || '');
    formData.append('erasure_id', erasureId);

    // Auth header from token
    const token = getAccessToken();
    xhr.setRequestHeader('Authorization', `Bearer ${token}`);

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) {
        const progress = (e.loaded / e.total) * 100;
        onProgress?.(progress);
      }
    };

    xhr.onload = () => {
      if (xhr.status === 200 || xhr.status === 201) {
        resolve(JSON.parse(xhr.responseText));
      } else {
        reject(new Error('Upload failed'));
      }
    };
  });
}

// ---------- File list ----------
export async function listFiles() {
  const response = await authFetch(`${API_BASE_URL}/files/list`, {
    method: "GET",
  });

  const result = await response.json();
  if (!response.ok) {
    throw new Error(result.detail || result.message || "Failed to list files");
  }

  // Backend returns { files: [...] } matching FileListResponse
  return result.files || [];
}

// ---------- File download ----------
export async function downloadFile(fileId, fileName) {
  const token = getAccessToken();
  if (!token) {
    throw new Error("Not authenticated");
  }

  const response = await fetch(`${API_BASE_URL}/files/download/${fileId}`, {
    method: "GET",
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || "Failed to download file");
  }

  // Response is raw bytes with Content-Disposition header
  const blob = await response.blob();

  // Try to extract filename from Content-Disposition; fall back to provided name
  const disposition = response.headers.get("Content-Disposition");
  let downloadName = fileName || "download";
  if (disposition) {
    const match = disposition.match(/filename="?([^"]+)"?/i);
    if (match && match[1]) {
      downloadName = match[1];
    }
  }

  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = downloadName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}

// ---------- File info ----------
export async function getFileInfo(fileId) {
  const response = await authFetch(`${API_BASE_URL}/files/info/${fileId}`, {
    method: "GET",
  });

  const result = await response.json();
  if (!response.ok) {
    throw new Error(result.detail || result.message || "Failed to get file info");
  }

  // Backend returns a single FileInfo object
  return result;
}

// ---------- Search: files + folders ----------
export async function searchFilesAndFolders(query) {
  const token = getAccessToken();
  if (!token) {
    throw new Error("Not authenticated");
  }

  const params = new URLSearchParams({ q: query });

  const response = await fetch(
    `${API_BASE_URL}/search/files-and-folders?${params.toString()}`,
    {
      method: "GET",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
    }
  );

  const result = await response.json();

  if (!response.ok) {
    throw new Error(
      result.detail || result.message || "Failed to search files and folders"
    );
  }

  // result has: { files: [...], folders: [...], total_files, total_folders, total }
  return result;
}

// ---------- Move file ----------
export async function moveFile({ fileId, newFolderId }) {
  const response = await authFetch(
    `${API_BASE_URL}/folders/files/${fileId}/move`,
    {
      method: "PATCH",
      body: JSON.stringify({
        new_folder_id: newFolderId || null, // null = move to root
      }),
    }
  );

  const result = await response.json();
  if (!response.ok) {
    throw new Error(
      result.detail || result.message || "Failed to move file"
    );
  }

  // backend returns FileResponse
  return result;
}

// ---------- Folders ----------
export async function createFolder({ name, parentFolderId = null }) {
  const response = await authFetch(`${API_BASE_URL}/folders`, {
    method: "POST",
    body: JSON.stringify({
      name,
      parent_folder_id: parentFolderId, // backend field
    }),
  });

  const result = await response.json();
  if (!response.ok) {
    throw new Error(result.detail || result.message || "Failed to create folder");
  }

  return result; // FolderResponse
}

// list folders with optional parent_folder_id
export async function listFolders(parentFolderId = null) {
  const params = new URLSearchParams();
  if (parentFolderId) {
    params.append("parent_folder_id", parentFolderId);
  }
  const response = await authFetch(
    `${API_BASE_URL}/folders/list?${params.toString()}`
  );
  const result = await response.json();
  if (!response.ok) {
    throw new Error(result.detail || result.message || "Failed to list folders");
  }
  return result.folders || result;
}

// ---------- Move folder ----------
export async function moveFolder({ folderId, newParentFolderId }) {
  const response = await authFetch(
    `${API_BASE_URL}/folders/${folderId}/move`,
    {
      method: "PATCH",
      body: JSON.stringify({
        new_parent_folder_id: newParentFolderId || null, // null = root
      }),
    }
  );

  const result = await response.json();
  if (!response.ok) {
    throw new Error(
      result.detail || result.message || "Failed to move folder"
    );
  }
  return result; // FolderResponse
}

// ---------- File sharing ----------
export async function createFileShare({
  fileid,
  sharedwithusername = null,
  permissions = "DOWNLOAD",
  expireshours = null,
  requirepassword = false,
}) {
  const body = {
    fileid,
    sharedwithusername,
    permissions,
    expireshours,
    requirepassword,
  };

  const response = await authFetch(`${API_BASE_URL}/shares/files/create`, {
    method: "POST",
    body: JSON.stringify(body),
  });

  const result = await response.json();
  if (!response.ok) {
    throw new Error(result.detail || result.message || "Failed to create file share");
  }
  // result: { shareid, sharetoken, onetimepassword, shareurl, expiresat, permissions }
  return result;
}

// ---------- Folder sharing ----------
export async function createFolderShare({
  folderid,
  sharedwithusername = null,
  permissions = "DOWNLOAD",
  expireshours = null,
  requirepassword = false,
}) {
  const body = {
    folderid,
    sharedwithusername,
    permissions,
    expireshours,
    requirepassword,
  };

  const response = await authFetch(`${API_BASE_URL}/shares/folders/create`, {
    method: "POST",
    body: JSON.stringify(body),
  });

  const result = await response.json();
  if (!response.ok) {
    throw new Error(result.detail || result.message || "Failed to create folder share");
  }
  return result;
}

// ---------- Sharing: list "shared with me" ----------
export async function getFilesSharedWithMe() {
  const response = await authFetch(`${API_BASE_URL}/shares/files/with-me`, {
    method: "GET",
  });

  const result = await response.json();
  if (!response.ok) {
    throw new Error(result.detail || result.message || "Failed to load shared files");
  }
  return result; // array of SharedWithMeResponse
}

export async function getFoldersSharedWithMe() {
  const response = await authFetch(`${API_BASE_URL}/shares/folders/with-me`, {
    method: "GET",
  });

  const result = await response.json();
  if (!response.ok) {
    throw new Error(result.detail || result.message || "Failed to load shared folders");
  }
  return result;
}

// ---------- Sharing: search users ----------
export async function searchShareUsers(query) {
  if (!query || query.length < 2) return [];
  const response = await authFetch(
    `${API_BASE_URL}/shares/users/search?q=${encodeURIComponent(query)}`,
    { method: "GET" }
  );

  const result = await response.json();
  if (!response.ok) {
    throw new Error(result.detail || result.message || "Failed to search users");
  }

  return result; // array of { username, email, ... }
}

// ---------- Sharing: share file with specific user ----------
export async function shareFileWithUser({ fileid, username, permissions, expireshours = null }) {
  const body = {
    fileid,
    username,
    permissions,
    expireshours,
  };

  const response = await authFetch(
    `${API_BASE_URL}/shares/files/share-with-user`,
    {
      method: "POST",
      body: JSON.stringify(body),
    }
  );

  const result = await response.json();
  if (!response.ok) {
    throw new Error(result.detail || result.message || "Failed to share file");
  }
  // { message, shareid, permissions, expiresat }
  return result;
}

// ---------- Storage usage ----------
export async function getStorageUsage() {
  const token = getAccessToken();
  if (!token) {
    throw new Error("Not authenticated");
  }

  const response = await authFetch(`${API_BASE_URL}/storage/usage`, {
    method: "GET",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
  });

  const result = await response.json();
  if (!response.ok) {
    throw new Error(
      result.detail || result.message || "Failed to fetch storage usage"
    );
  }

  return result;
}

// Delete folder (hard delete)
export async function deleteFolder(folderId) {
  const response = await authFetch(
    `${API_BASE_URL}/folders/${folderId}`,
    {
      method: "DELETE",
    }
  );

  const result = await response.json();
  if (!response.ok) {
    throw new Error(
      result.detail || result.message || "Failed to delete folder"
    );
  }
  return result; // { message, deleted_folder_id, deleted_folder_name }
}

// Delete file (hard delete)
export async function deleteFile(fileId) {
  const response = await authFetch(
    `${API_BASE_URL}/files/${fileId}`,
    {
      method: "DELETE",
    }
  );

  const result = await response.json();
  if (!response.ok) {
    throw new Error(
      result.detail || result.message || "Failed to delete file"
    );
  }
  return result; // { message, deleted_file_id, deleted_file_name }
}

// ---- Recycle Bin: soft delete ----

// Move a file to recycle bin
export async function binDeleteFile({ fileId, deletionReason = "USER_DELETE" }) {
  const response = await authFetch(
    `${API_BASE_URL}/bin/delete-file`,
    {
      method: "POST",
      body: JSON.stringify({
        file_id: fileId,
        deletion_reason: deletionReason,
      }),
    }
  );

  const result = await response.json();
  if (!response.ok) {
    throw new Error(result.detail || result.message || "Failed to move file to recycle bin");
  }
  return result; // { message, bin_id, expires_at, retention_days }
}

// Move a folder (and its contents) to recycle bin
export async function binDeleteFolder({ folderId, deletionReason = "USER_DELETE" }) {
  const response = await authFetch(
    `${API_BASE_URL}/bin/delete-folder`,
    {
      method: "POST",
      body: JSON.stringify({
        folder_id: folderId,
        deletion_reason: deletionReason,
      }),
    }
  );

  const result = await response.json();
  if (!response.ok) {
    throw new Error(result.detail || result.message || "Failed to move folder to recycle bin");
  }
  return result;
}

// ---- Recycle Bin: list / restore / empty ----

export async function listBinItems() {
  const response = await authFetch(
    `${API_BASE_URL}/bin/list`,
    { method: "GET" }
  );

  const result = await response.json();
  if (!response.ok) {
    throw new Error(result.detail || result.message || "Failed to load recycle bin items");
  }
  return result; // Array<BinItemResponse>
}

export async function getBinStats() {
  const response = await authFetch(
    `${API_BASE_URL}/bin/stats`,
    { method: "GET" }
  );

  const result = await response.json();
  if (!response.ok) {
    throw new Error(result.detail || result.message || "Failed to load recycle bin stats");
  }
  return result; // BinStatsResponse
}

export async function restoreBinItem(binId) {
  const response = await authFetch(
    `${API_BASE_URL}/bin/restore`,
    {
      method: "POST",
      body: JSON.stringify({ bin_id: binId }),
    }
  );

  const result = await response.json();
  if (!response.ok) {
    throw new Error(result.detail || result.message || "Failed to restore item");
  }
  return result;
}

export async function emptyBin() {
  const response = await authFetch(
    `${API_BASE_URL}/bin/empty`,
    { method: "DELETE" }
  );

  const result = await response.json();
  if (!response.ok) {
    throw new Error(result.detail || result.message || "Failed to empty recycle bin");
  }
  return result;
}

export async function permanentDeleteBinItem(binId) {
  const response = await authFetch(
    `${API_BASE_URL}/bin/permanent-delete/${binId}`,
    { method: "DELETE" }
  );

  const result = await response.json();
  if (!response.ok) {
    throw new Error(result.detail || result.message || "Failed to permanently delete item");
  }
  return result;
}