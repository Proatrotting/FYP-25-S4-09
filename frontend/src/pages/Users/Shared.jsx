import React, { useEffect, useState } from "react";
import { getFilesSharedWithMe, downloadFile} from "../../services/UserService";
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
        const data = await getFilesSharedWithMe(); // calls GET /shares/with-me [file:261]
        setSharedWithMe(Array.isArray(data) ? data : []);
      } catch (err) {
        console.error(err);
        setError(err.message || "Failed to load shared files");
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
      <h3 style={{ paddingLeft: "10px" }}>Files Shared With You</h3>

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
              <th>File Name</th>
              <th>Permissions</th>
              <th>Shared / Expires</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={4} style={{ textAlign: "center" }}>
                  No files shared with you
                </td>
              </tr>
            ) : (
              rows.map((s) => (
                <tr key={s.shareid}>
                  <td>{s.filename}</td>
                  <td>{s.permissions}</td>
                  <td>
                    {new Date(s.sharedat).toLocaleDateString()}
                    {s.expiresat &&
                      ` (expires ${new Date(s.expiresat).toLocaleDateString()})`}
                  </td>
                  <td>
                    {s.permissions === "DOWNLOAD" ? (
                      <button
                        className="toolbar-action-btn"
                        onClick={() => downloadFile(s.fileid, s.filename)}
                      >
                        Download
                      </button>
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