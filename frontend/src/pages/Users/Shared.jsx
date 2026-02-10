import React, { useEffect, useState } from "react";
import { getFilesSharedWithMe, getFoldersSharedWithMe, downloadSharedFile, downloadSharedFolder} from "../../services/UserService";
import "../../styles/Users/UserDashboard.css";

const Shared = () => {
  const [sharedWithMe, setSharedWithMe] = useState([]);
  const [shareLoading, setShareLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const loadShared = async () => {
      setShareLoading(true);
      setError("");
      try {
        // Fetch both files and folders
        const [files, folders] = await Promise.all([
          getFilesSharedWithMe(),
          getFoldersSharedWithMe()
        ]);
        
        // Add type indicator to each item
        const filesWithType = (Array.isArray(files) ? files : []).map(f => ({ ...f, type: 'file' }));
        const foldersWithType = (Array.isArray(folders) ? folders : []).map(f => ({ ...f, type: 'folder' }));
        
        // Combine and sort by shared_at (most recent first)
        const combined = [...filesWithType, ...foldersWithType].sort(
          (a, b) => new Date(b.shared_at) - new Date(a.shared_at)
        );
        
        setSharedWithMe(combined);
      } catch (err) {
        console.error(err);
        setError(err.message || "Failed to load shared items");
        setSharedWithMe([]);
      } finally {
        setShareLoading(false);
      }
    };

    loadShared();
  }, []);

  const rows = sharedWithMe || [];

  return (
    <div className="dashboard-table-wrapper">
      <h3 style={{ paddingLeft: "10px" }}>Files/Folders Shared With You</h3>

      {error && (
        <div style={{ padding: 12, color: "#c53030", textAlign: "center" }}>
          {error}
        </div>
      )}

      {shareLoading ? (
        <div style={{ padding: 16, textAlign: "center" }}>Loading...</div>
      ) : (
        <table className="dashboard-table">
          <thead>
            <tr>
              <th>Type</th>
              <th>Name</th>
              <th>Permissions</th>
              <th>Shared / Expires</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={5} style={{ textAlign: "center" }}>
                  No files or folders shared with you
                </td>
              </tr>
            ) : (
              rows.map((s) => (
                <tr key={s.share_id}>
                  <td>{s.type === 'folder' ? '📁 Folder' : '📄 File'}</td>
                  <td>{s.file_name}</td>
                  <td>{s.permissions}</td>
                  <td>
                    {new Date(s.shared_at).toLocaleDateString()}
                    {s.expires_at &&
                      ` (expires ${new Date(s.expires_at).toLocaleDateString()})`}
                  </td>
                  <td>
                    {s.permissions === "DOWNLOAD" ? (
                      s.type === 'file' ? (
                        <button
                          className="toolbar-action-btn"
                          onClick={() => downloadSharedFile(s.share_id, s.file_name)}
                        >
                          Download
                        </button>
                      ) : (
                        <button
                          className="toolbar-action-btn"
                          onClick={() => downloadSharedFolder(s.share_id, s.file_name)}
                        >
                          Download ZIP
                        </button>
                      )
                    ) : (
                      <span>View Only</span>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      )}
    </div>
  );
};

export default Shared;