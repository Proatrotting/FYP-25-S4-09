import React, { useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { API_BASE_URL } from "../../services/UserService";
import "../../styles/Users/AnonymousDownload.css";

const AnonymousDownload = () => {
  const { token } = useParams();
  const [searchParams] = useSearchParams();
  const [loading, setLoading] = useState(true);
  const [info, setInfo] = useState(null);
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [accessGranted, setAccessGranted] = useState(false);
  const [accessLoading, setAccessLoading] = useState(false);
  
  // For folder browsing
  const [currentFolderId, setCurrentFolderId] = useState(null);
  const [folderContents, setFolderContents] = useState({ folders: [], files: [] });
  const [breadcrumbs, setBreadcrumbs] = useState([]);

  // Try to detect if it's a file or folder by checking both endpoints
  useEffect(() => {
    const loadInfo = async () => {
      setLoading(true);
      setError("");
      
      try {
        // Try file first
        let res = await fetch(`${API_BASE_URL}/shares/files/info/${token}`);
        let data = await res.json();
        
        if (!res.ok) {
          // Try folder
          res = await fetch(`${API_BASE_URL}/shares/folders/info/${token}`);
          data = await res.json();
          
          if (!res.ok) {
            throw new Error(data.detail || data.message || "Share not found");
          }
        }
        
        setInfo(data);
      } catch (err) {
        setError(err.message || "Failed to load share info");
      } finally {
        setLoading(false);
      }
    };

    if (token) {
      loadInfo();
    }
  }, [token]);

  const handleAccess = async () => {
    if (!info) return;
    
    setError("");
    setAccessLoading(true);
    
    try {
      const endpoint = info.resource_type === "FILE" 
        ? `${API_BASE_URL}/shares/files/access`
        : `${API_BASE_URL}/shares/folders/access`;
      
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          share_token: token,
          password: password.trim() || null,
        }),
      });
      
      const data = await res.json();
      
      if (!res.ok) {
        throw new Error(data.detail || data.message || "Access denied");
      }

      setAccessGranted(true);

      // If it's a file with DOWNLOAD permission, auto-download
      if (info.resource_type === "FILE" && data.permissions === "DOWNLOAD") {
        handleDownloadFile();
      } else if (info.resource_type === "FOLDER") {
        // Set root folder ID and load contents
        setCurrentFolderId(data.folder_id);
        setBreadcrumbs([{ id: data.folder_id, name: data.folder_name }]);
        loadFolderContents(data.folder_id);
      }
    } catch (err) {
      setError(err.message || "Failed to access share");
    } finally {
      setAccessLoading(false);
    }
  };

  const handleDownloadFile = () => {
    window.location.href = `${API_BASE_URL}/shares/files/shared-download/${token}?password=${encodeURIComponent(password || "")}`;
  };

  const handleDownloadFolder = () => {
    window.location.href = `${API_BASE_URL}/shares/folders/shared-download/${token}?password=${encodeURIComponent(password || "")}`;
  };

  const loadFolderContents = async (folderId) => {
    try {
      const endpoint = folderId === breadcrumbs[0]?.id
        ? `${API_BASE_URL}/shares/folders/browse/${token}?password=${encodeURIComponent(password || "")}`
        : `${API_BASE_URL}/shares/folders/subfolder/${token}/${folderId}?password=${encodeURIComponent(password || "")}`;
      
      const res = await fetch(endpoint);
      const data = await res.json();
      
      if (!res.ok) {
        throw new Error(data.detail || "Failed to load folder contents");
      }
      
      setFolderContents({
        folders: data.subfolders || [],
        files: data.files || []
      });
    } catch (err) {
      setError(err.message);
    }
  };

  const handleNavigateToFolder = (folder) => {
    setCurrentFolderId(folder.folder_id);
    setBreadcrumbs([...breadcrumbs, { id: folder.folder_id, name: folder.name }]);
    loadFolderContents(folder.folder_id);
  };

  const handleNavigateToBreadcrumb = (index) => {
    const newBreadcrumbs = breadcrumbs.slice(0, index + 1);
    setBreadcrumbs(newBreadcrumbs);
    setCurrentFolderId(newBreadcrumbs[newBreadcrumbs.length - 1].id);
    loadFolderContents(newBreadcrumbs[newBreadcrumbs.length - 1].id);
  };

  const handleDownloadFolderFile = (fileId, fileName) => {
    // Use the stream endpoint for direct download
    const url = `${API_BASE_URL}/shares/files/shared-download-stream/${token}/${fileId}?password=${encodeURIComponent(password || "")}`;
    const link = document.createElement('a');
    link.href = url;
    link.download = fileName;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleDownloadSubfolder = (folderId) => {
    window.location.href = `${API_BASE_URL}/shares/folders/shared-download-subfolder/${token}/${folderId}?password=${encodeURIComponent(password || "")}`;
  };

  if (loading) {
    return (
      <div className="anon-download-container">
        <div className="anon-download-card">
          <div className="loading-spinner"></div>
          <p>Loading shared resource...</p>
        </div>
      </div>
    );
  }

  if (error && !info) {
    return (
      <div className="anon-download-container">
        <div className="anon-download-card error">
          <h2>❌ Error</h2>
          <p>{error}</p>
        </div>
      </div>
    );
  }

  if (!info) {
    return (
      <div className="anon-download-container">
        <div className="anon-download-card">
          <h2>Share not found</h2>
          <p>This share link may be invalid or has been deleted.</p>
        </div>
      </div>
    );
  }

  const isExpired = info.is_expired;

  return (
    <div className="anon-download-container">
      <div className="anon-download-card">
        <div className="share-header">
          <h1>
            {info.resource_type === "FILE" ? "📄" : "📁"} Shared {info.resource_type}
          </h1>
        </div>

        <div className="share-info">
          <div className="info-row">
            <span className="info-label">Name:</span>
            <span className="info-value">{info.resource_name}</span>
          </div>
          <div className="info-row">
            <span className="info-label">Shared by:</span>
            <span className="info-value">{info.shared_by_username}</span>
          </div>
          <div className="info-row">
            <span className="info-label">Type:</span>
            <span className="info-value">{info.resource_type}</span>
          </div>
          <div className="info-row">
            <span className="info-label">Permissions:</span>
            <span className="info-value badge">{info.permissions}</span>
          </div>
          {info.expires_at && (
            <div className="info-row">
              <span className="info-label">Expires:</span>
              <span className="info-value">
                {new Date(info.expires_at).toLocaleString()}
              </span>
            </div>
          )}
        </div>

        {isExpired && (
          <div className="alert alert-error">
            <strong>⚠️ Expired:</strong> This share link has expired.
          </div>
        )}

        {!isExpired && !accessGranted && (
          <div className="access-section">
            {info.requires_password && (
              <div className="form-group">
                <label htmlFor="password-input">
                  🔒 Password Required
                </label>
                <input
                  id="password-input"
                  type="password"
                  className="form-input"
                  placeholder="Enter the one-time password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleAccess()}
                />
              </div>
            )}

            {!info.requires_password && (
              <div className="alert alert-info">
                ℹ️ No password required for this share.
              </div>
            )}

            {error && (
              <div className="alert alert-error">
                {error}
              </div>
            )}

            <button
              type="button"
              className="btn btn-primary"
              onClick={handleAccess}
              disabled={accessLoading}
            >
              {accessLoading ? "Verifying..." : info.resource_type === "FILE" ? "Download File" : "Access Folder"}
            </button>
          </div>
        )}

        {!isExpired && accessGranted && info.resource_type === "FOLDER" && (
          <div className="folder-browser">
            <div className="browser-header">
              <div className="breadcrumb">
                {breadcrumbs.map((crumb, index) => (
                  <React.Fragment key={crumb.id}>
                    {index > 0 && <span className="breadcrumb-separator">/</span>}
                    <button
                      className="breadcrumb-item"
                      onClick={() => handleNavigateToBreadcrumb(index)}
                    >
                      {crumb.name}
                    </button>
                  </React.Fragment>
                ))}
              </div>
              <button
                className="btn btn-download"
                onClick={handleDownloadFolder}
                title="Download entire folder as ZIP"
              >
                ⬇️ Download All
              </button>
            </div>

            <div className="folder-contents">
              {folderContents.folders.length === 0 && folderContents.files.length === 0 && (
                <div className="empty-folder">
                  📭 This folder is empty
                </div>
              )}

              {folderContents.folders.length > 0 && (
                <div className="items-section">
                  <h3>📁 Folders</h3>
                  <div className="items-list">
                    {folderContents.folders.map((folder) => (
                      <div key={folder.folder_id} className="item-row folder-row">
                        <button
                          className="item-name"
                          onClick={() => handleNavigateToFolder(folder)}
                        >
                          📁 {folder.name}
                        </button>
                        <button
                          className="btn btn-small"
                          onClick={() => handleDownloadSubfolder(folder.folder_id)}
                          title="Download this folder"
                        >
                          ⬇️
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {folderContents.files.length > 0 && (
                <div className="items-section">
                  <h3>📄 Files</h3>
                  <div className="items-list">
                    {folderContents.files.map((file) => (
                      <div key={file.file_id} className="item-row file-row">
                        <span className="item-name">
                          📄 {file.file_name}
                        </span>
                        <span className="file-size">
                          {formatFileSize(file.file_size)}
                        </span>
                        <button
                          className="btn btn-small"
                          onClick={() => handleDownloadFolderFile(file.file_id, file.file_name)}
                          title="Download this file"
                        >
                          ⬇️
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

// Helper function to format file size
function formatFileSize(bytes) {
  if (!bytes) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return Math.round(bytes / Math.pow(k, i) * 100) / 100 + " " + sizes[i];
}

export default AnonymousDownload;
