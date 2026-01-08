import React, { useRef, useState, useEffect } from "react";
import "../../styles/Users/UserDashboard.css";
import { useNavigate } from "react-router-dom";
import { createFolder, listFolders, moveFolder, 
         uploadFile, listFiles, downloadFile, 
         getFileInfo, searchFilesAndFolders, moveFile,
         createFileShare,createFolderShare,
         searchShareUsers, shareFileWithUser,
         binDeleteFile, binDeleteFolder, uploadFolderApi,
         downloadFolderZip} from "../../services/UserService";
import { Tooltip } from "./Tooltip";

const UserDashboard = () => {
  const navigate = useNavigate();
  const [currentPath, setCurrentPath] = useState("/Home");
  const [currentFolderId, setCurrentFolderId] = useState(null); // null = root
  const [isCreatingFolder, setIsCreatingFolder] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [erasureLevel, setErasureLevel] = useState("MEDIUM");
  const [files, setFiles] = useState([]);
  const [folders, setFolders] = useState([]);       
  const [searchQuery, setSearchQuery] = useState(""); 
  const [moveTargets, setMoveTargets] = useState({}); // { [fileId]: folderId | "" }
  const [dragItem, setDragItem] = useState(null); // { type: 'file' | 'folder', id: string }
  const [isDragging, setIsDragging] = useState(false);
  const [shareModalOpen, setShareModalOpen] = useState(false);
  const [shareData, setShareData] = useState(null);
  const [shareLoading, setShareLoading] = useState(false);
  const [shareUsername, setShareUsername] = useState("");
  const [sharePermissions, setSharePermissions] = useState("DOWNLOAD");
  const [userSuggestions, setUserSuggestions] = useState([]);
  const [showUserSuggestions, setShowUserSuggestions] = useState(false);
  const [publicShareData, setPublicShareData] = useState(null);
  const [publicShareLoading, setPublicShareLoading] = useState(false);
  const [publicPassword, setPublicPassword] = useState("");
  const [publicExpires, setPublicExpires] = useState("never"); 

  const [openMenuFileId, setOpenMenuFileId] = useState(null);
  const [openMenuType, setOpenMenuType] = useState(null); // "file" | "folder"
  const [menuPosition, setMenuPosition] = useState({ x: 0, y: 0 });

  const folderInputRef = useRef(null);
  const [isUploadingFolder, setIsUploadingFolder] = useState(false);

  const toggleMenu = (id, type, event) => {
    setOpenMenuFileId((prev) => (prev === id ? null : id));
    setOpenMenuType(type || null);

    if (event) {
      const rect = event.currentTarget.getBoundingClientRect();
      // Show menu below the button, aligned left
      setMenuPosition({
        x: rect.left,
        y: rect.bottom + window.scrollY,
      });
    }
  };

  const closeMenu = () => {
    setOpenMenuFileId(null);
    setOpenMenuType(null);
  };

  // Load root folders and files on mount
  useEffect(() => {
    const loadInitial = async () => {
      try {
        const [foldersData, filesData] = await Promise.all([
          listFolders(null), // root folders
          listFiles(),
        ]);
        setFolders(foldersData);
        setFiles(filesData);
      } catch (err) {
        console.error(err);
      }
    };
    loadInitial();
  }, []);

  // Helper: reload folders for current folder
  const refreshFolders = async (folderId) => {
    try {
      const data = await listFolders(folderId || null);
      setFolders(data);
    } catch (err) {
      console.error(err);
    }
  };

  const handleDownloadFolder = async (folder) => {
    try {
      await downloadFolderZip(folder.folder_id);
    } catch (err) {
      console.error("Failed to download folder", err);
      alert(err.message || "Failed to download folder");
    }
  };

  const handleUploadFolderClick = () => {
    if (folderInputRef.current) {
      folderInputRef.current.value = ""; // allow reselect same folder
      folderInputRef.current.click();
    }
  };

  const handleFolderChange = async (e) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;

    // Derive folder name from first file's webkitRelativePath
    const first = files[0];
    let folderName = "New Folder";
    if (first.webkitRelativePath) {
      const parts = first.webkitRelativePath.split("/");
      if (parts.length > 1) {
        folderName = parts[0]; // top-level folder name
      }
    }

    try {
      setIsUploadingFolder(true);
      const result = await uploadFolderApi({
        folderName,
        files,
        parentFolderId: currentFolderId, // or null if you always upload at root
        erasureId: erasureLevel,
      });
      console.log("Folder upload result:", result);
      // Refresh listing after upload
      await fetchFilesAndFolders(currentFolderId);
    } catch (err) {
      console.error("Failed to upload folder", err);
      alert(err.message || "Failed to upload folder");
    } finally {
      setIsUploadingFolder(false);
    }
  };

  const handleCreateFolderConfirm = async () => {
    const trimmed = newFolderName.trim();
    if (!trimmed) {
      alert("Folder name cannot be empty");
      return;
    }

    setIsLoading(true);
    try {
      await createFolder({
        name: trimmed,
        parentFolderId: currentFolderId,
      });

      // reload folders for current folder
      await refreshFolders(currentFolderId);

      setIsCreatingFolder(false);
      setNewFolderName("");
    } catch (err) {
      console.error(err);
      alert(err.message || "Failed to create folder");
    } finally {
      setIsLoading(false);
    }
  };

  // Navigation
  const enterFolder = async (folder) => {
    const newFolderId = folder.folder_id;
    setCurrentFolderId(newFolderId);
    setCurrentPath((prev) =>
      prev === "/" ? `/${folder.name}` : `${prev}/${folder.name}`
    );
    await refreshFolders(newFolderId);
    // later: also filter/load files by folder if backend supports it
  };

  const goUpOneLevel = async () => {
    if (currentFolderId === null) return;

    const currentFolder = folders.find((f) => f.folder_id === currentFolderId);
    const parentId = currentFolder?.parent_folder_id || null;

    setCurrentFolderId(parentId);

    const parts = currentPath.split("/").filter(Boolean);
    parts.pop();
    setCurrentPath(parts.length ? `/${parts.join("/")}` : "/");

    await refreshFolders(parentId);
  };

  // Load files when dashboard mounts
  useEffect(() => {
    const load = async () => {
      try {
        const data = await listFiles();
        setFiles(data);
      } catch (err) {
        console.error(err);
      }
    };
    load();
  }, []);

  function formatFileSize(bytes) {
  if (!bytes && bytes !== 0) return "";
  if (bytes === 0) return "0 B";

  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = bytes;
  let unitIndex = 0;

  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }

  const decimals = size < 10 && unitIndex > 0 ? 2 : size < 100 ? 1 : 0;
    return `${size.toFixed(decimals)} ${units[unitIndex]}`;
  }

  const fileInputRef = useRef(null); 

  const handleUploadClick = () => {
    if (fileInputRef.current) {
      fileInputRef.current.click();
    }
  };

  const handleFileChange = async (e) => {
    const selectedFiles = Array.from(e.target.files || []);
    if (selectedFiles.length === 0) return;

    setIsLoading(true);
    try {
      // Upload sequentially; you can parallelize later if needed
      for (const file of selectedFiles) {
        // eslint-disable-next-line no-await-in-loop
        await uploadFile({
          file,
          folderId: currentFolderId,
          erasureId: erasureLevel,
        });
      }

      // After all uploads, refresh list once
      const data = await listFiles();
      setFiles(data);
    } catch (err) {
      console.error(err);
      alert(err.message || "Failed to upload one or more files");
    } finally {
      setIsLoading(false);
      e.target.value = ""; // allow selecting same files again
    }
  };

  const handleDownload = async (file) => {
    try {
      await downloadFile(file.file_id, file.file_name);
    } catch (err) {
      console.error(err);
      alert(err.message || "Failed to download file");
    }
  };

  // File Info modal state
  const [fileInfoModalOpen, setFileInfoModalOpen] = useState(false);
  const [fileInfoData, setFileInfoData] = useState(null);

  const openFileInfo = async (file) => {
    try {
      const info = await getFileInfo(file.file_id);
      setFileInfoData(info);
      setFileInfoModalOpen(true);
    } catch (err) {
      console.error(err);
      alert(err.message || "Failed to load file info");
    }
  };

  const closeFileInfo = () => {
    setFileInfoModalOpen(false);
    setFileInfoData(null);
  };

  // Search state
  async function handleSearchSubmit(e) {
    e.preventDefault();
    try {
      const result = await searchFilesAndFolders(searchQuery);
      setFiles(result.files || []);
      setFolders(result.folders || []);
    } catch (err) {
      console.error(err);
      alert(err.message);
    }
  }

  function handleSearchChange(e) {
    setSearchQuery(e.target.value);
  }

  function handleCreateFolderCancel() {
    setIsCreatingFolder(false);
    setNewFolderName("");
  }

  const visibleFolders = folders.filter((f) =>
    currentFolderId === null
      ? f.parent_folder_id === null // root folders
      : f.parent_folder_id === currentFolderId
  );
  const visibleFiles = files.filter((f) =>
    currentFolderId === null
      ? !f.folder_id // root files
      : f.folder_id === currentFolderId
  );

  function handleMoveTargetChange(fileId, folderId) {
    setMoveTargets((prev) => ({
      ...prev,
      [fileId]: folderId,
    }));
  }

  async function handleMoveFile(file) {
    const targetFolderId = moveTargets[file.file_id] || null;
    if (!targetFolderId) {
      alert("Please select a folder first");
      return;
    }

    try {
      await moveFile({ fileId: file.file_id, newFolderId: targetFolderId });
      // refresh current view: folders and files
      await loadCurrentFolderData();
      alert("File moved successfully");
    } catch (err) {
      console.error(err);
      alert(err.message || "Failed to move file");
    }
  }

  async function handleMoveFolder(folder) {
    const targetFolderId = moveTargets[folder.folder_id] || null;
    if (targetFolderId === folder.folder_id) {
      alert("Cannot move a folder into itself");
      return;
    }
    if (!targetFolderId) {
      alert("Please select a folder first");
      return;
    }
    try {
      await moveFolder({
        folderId: folder.folder_id,
        newParentFolderId: targetFolderId,
      });
      await loadCurrentFolderData(); // reload folders + files for currentFolderId
      alert("Folder moved successfully");
    } catch (err) {
      console.error(err);
      alert(err.message || "Failed to move folder");
    }
  }

  // Drag-and-drop handlers
  const handleDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleDragLeave = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDrop = async (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    const droppedFiles = Array.from(e.dataTransfer.files || []);
    if (droppedFiles.length === 0) return;

    setIsLoading(true);
    try {
      for (const file of droppedFiles) {
        // eslint-disable-next-line no-await-in-loop
        await uploadFile({
          file,
          folderId: currentFolderId,
          erasureId: erasureLevel,
        });
      }
      const data = await listFiles(); // or listFiles(currentFolderId) if you filter by folder
      setFiles(data);
    } catch (err) {
      console.error(err);
      alert(err.message || "Failed to upload one or more files");
    } finally {
      setIsLoading(false);
    }
  };

  // Folder sharing handler
  const handleShareFolder = (folder) => {
    setShareData({ fileId: folder.folder_id, fileName: folder.name, isFolder: true });
    setShareUsername("");
    setSharePermissions("DOWNLOAD");
    setUserSuggestions([]);
    setShowUserSuggestions(false);
    setPublicShareData(null);
    setShareModalOpen(true);
  };

  // File sharing handler
  const handleShareFile = (file) => {
    setShareData({ fileId: file.file_id, fileName: file.file_name });
    setShareUsername("");
    setSharePermissions("DOWNLOAD");
    setUserSuggestions([]);
    setShowUserSuggestions(false);
    setPublicShareData(null);       // reset
    setShareModalOpen(true);
  };

  // Handle share username input change
  const handleShareUsernameChange = async (e) => {
    const value = e.target.value;
    setShareUsername(value);

    if (value.length < 2) {
      setUserSuggestions([]);
      setShowUserSuggestions(false);
      return;
    }

    try {
      const users = await searchShareUsers(value);
      setUserSuggestions(users);
      setShowUserSuggestions(true);
    } catch (err) {
      console.error(err);
      setUserSuggestions([]);
      setShowUserSuggestions(false);
    }
  };

  const handleSelectShareUser = (username) => {
    setShareUsername(username);
    setShowUserSuggestions(false);
  };

  // Submit share to user
  const handleSubmitShareToUser = async () => {
    if (!shareData?.fileId) return;
    if (!shareUsername.trim()) {
      alert("Please enter a username to share with");
      return;
    }

    setShareLoading(true);
    try {
      const res = await shareFileWithUser({
        fileId: shareData.fileId,
        username: shareUsername.trim(),
        permissions: sharePermissions,
      });
      alert(res.message || "File shared successfully");
      setShareModalOpen(false);
      setShareData(null);
    } catch (err) {
      console.error(err);
      alert(err.message || "Failed to share file");
    } finally {
      setShareLoading(false);
    }
  };

  // Handle creating public share link
  const handleCreatePublicLink = async () => {
    if (!shareData) return;

    const expiresHours = getExpiresHoursFromOption(publicExpires);
    const requirePassword = publicPassword.trim().length > 0;

    setPublicShareLoading(true);
    try {
      const payload = {
        sharedWithUsername: null,
        permissions: sharePermissions,
        expiresHours,
        requirePassword,
      };

      const res = shareData.isFolder
        ? await createFolderShare({ folderId: shareData.fileId, ...payload })
        : await createFileShare({ fileId: shareData.fileId, ...payload });

      setPublicShareData(res);
    } catch (err) {
      console.error(err);
      alert(err.message || "Failed to create public share link");
    } finally {
      setPublicShareLoading(false);
    }
  };

  const getExpiresHoursFromOption = (value) => {
    switch (value) {
      case "1h":
        return 1;
      case "24h":
        return 24;
      case "1w":
        return 24 * 7;
      case "1m":
        return 24 * 30;
      case "never":
      default:
        return null; // backend: no expiration
    }
  };

  const handleSoftDeleteFolder = async (folder) => {
    const confirmed = window.confirm(
      `Move folder "${folder.name}" and all its contents to Recycle Bin?`
    );
    if (!confirmed) return;

    try {
      await binDeleteFolder({ folderId: folder.folder_id });
      await loadCurrentFolderData(); // same helper you use after upload/move
    } catch (err) {
      console.error(err);
      alert(err.message || "Failed to move folder to Recycle Bin");
    }
  };

  const handleSoftDeleteFile = async (file) => {
    const confirmed = window.confirm(
      `Move file "${file.file_name}" to Recycle Bin?`
    );
    if (!confirmed) return;

    try {
      await binDeleteFile({ fileId: file.file_id });
      await loadCurrentFolderData();
    } catch (err) {
      console.error(err);
      alert(err.message || "Failed to move file to Recycle Bin");
    }
  };

  const loadCurrentFolderData = async () => {
    try {
      const [foldersResult, filesResult] = await Promise.all([
        listFolders(currentFolderId),
        listFiles(currentFolderId),
      ]);

      // Adjust to your actual response shapes
      setFolders(foldersResult.folders || foldersResult || []);
      setFiles(filesResult.files || filesResult || []);
    } catch (err) {
      console.error("Failed to reload current folder:", err);
    }
  };

  return (
    <div className="dashboard-container">
      {/* Top controls: current folder + search + actions */}
      <div className="dashboard-toolbar">
        <div className="toolbar-left">
          <label className="toolbar-label">Current Folder Location</label>
          <input
            className="toolbar-input"
            type="text"
            value={currentPath}
            readOnly
          />
        </div>

        <div className="toolbar-center">
          <form onSubmit={handleSearchSubmit}>
            <input
              className="search-input"
              type="text"
              placeholder="Search files by name"
              value={searchQuery}
              onChange={handleSearchChange}
            />
          </form>
        </div>

        <div className="toolbar-right">
          <button
            className="toolbar-action-btn-1"
            onClick={goUpOneLevel}
            disabled={isLoading || currentFolderId === null}
          >
            ↩ Back
          </button>
          <button
            className="toolbar-action-btn"
            onClick={() => setIsCreatingFolder(true)}
            disabled={isLoading}
          >
            + Create Folder
          </button>
          {/* Hidden file input for single/multi file upload */}
          <input
            type="file"
            ref={fileInputRef}
            style={{ display: "none" }}
            onChange={handleFileChange}
            multiple
          />
          {/* Hidden input for folder upload */}
          <input
            type="file"
            ref={folderInputRef}
            style={{ display: "none" }}
            webkitdirectory="true"
            directory=""
            multiple
            onChange={handleFolderChange}
          />
          {/* Erasure level selector */}
          <Tooltip
            label={
                <>
                  <strong>Select Redundancy Level</strong>
                  <br /><br />
                  <strong>Low Redundancy (4+2 = 6 fragments)</strong><br />
                  Provides basic protection. Your file is split into pieces with a few backups, so it can still be recovered even if up to 2 pieces are lost.
                  <br /><br />
                  <strong>Medium Redundancy (6+3 = 9 fragments)</strong><br />
                  A balanced option. More pieces and more backups, allowing the file to be recovered even if up to 3 pieces go missing.
                  <br /><br />
                  <strong>High Redundancy (8+4 = 12 fragments)</strong><br />
                  The safest option. Lots of backups, so the file can be recovered even if up to 4 pieces are lost. Good for important data.
                </>
              }
          >
          <select
            className="toolbar-select"
            value={erasureLevel}
            onChange={(e) => setErasureLevel(e.target.value)}
            disabled={isLoading}
            aria-describedby="redundancy-tooltip"
          >
            <option value="LOW">Low</option>
            <option value="MEDIUM">Medium</option>
            <option value="HIGH">High</option>
          </select>
        </Tooltip>
          <button
            className="toolbar-action-btn"
            onClick={handleUploadClick}
            disabled={isLoading}
          >
            + Upload File
          </button>
          {/* NEW: Upload Folder button */}
          <button
            className="toolbar-action-btn"
            onClick={handleUploadFolderClick}
            disabled={isLoading || isUploadingFolder}
          >
            {isUploadingFolder ? "Uploading Folder..." : "+ Upload Folder"}
          </button>
        </div>
      </div>

      {/* Inline create-folder bar */}
      {isCreatingFolder && (
        <div className="create-folder-bar">
          <input
            type="text"
            className="toolbar-input"
            placeholder="Folder name"
            value={newFolderName}
            onChange={(e) => setNewFolderName(e.target.value)}
            disabled={isLoading}
          />
          <button
            className="toolbar-action-btn"
            onClick={handleCreateFolderConfirm}
            disabled={isLoading}
          >
            Create
          </button>
          <button
            className="toolbar-action-btn"
            onClick={handleCreateFolderCancel}
            disabled={isLoading}
          >
            Cancel
          </button>
        </div>
      )}

      {/* Files table */}
      <div className={`dashboard-table-wrapper ${isDragging ? "dragging" : ""}`}
           onDragOver={handleDragOver}
           onDragLeave={handleDragLeave}
           onDrop={handleDrop}>
        <table className="dashboard-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Size</th>
              <th>Modified Date</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {/* Recycle Bin fixed row */}
            <tr
              className="folder-row"
              style={{ cursor: "pointer", backgroundColor: "#f8f9fb" }}
              onClick={() => navigate("/users/bin")}
            >
              <td colSpan={4}>
                <strong>🗑️ #recyclebin</strong>{" "}
                <span style={{ marginLeft: 12, fontSize: "12px", color: "#666" }}>
                  View deleted files and folders
                </span>
              </td>
            </tr>
            {visibleFolders.length === 0 && visibleFiles.length === 0 ? (
              <tr>
                <td colSpan={4} style={{ textAlign: "center" }}>
                  No items found
                </td>
              </tr>
            ) : (
              <>
                {/* Folders */}
                {visibleFolders.map((folder) => (
                  <tr
                    key={folder.folder_id}
                    className="folder-row"
                    draggable
                    onDragStart={(e) => {
                      e.stopPropagation();
                      setDragItem({ type: "folder", id: folder.folder_id });
                    }}
                    onDragEnd={() => setDragItem(null)}
                    onDragOver={(e) => {
                      e.preventDefault();
                    }}
                    onDrop={async (e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      if (!dragItem) return;

                      try {
                        if (dragItem.type === "file") {
                          await moveFile({
                            fileId: dragItem.id,
                            newFolderId: folder.folder_id,
                          });
                          await loadCurrentFolderData();
                        } else if (dragItem.type === "folder") {
                          await moveFolder({
                            folderId: dragItem.id,
                            newParentFolderId: folder.folder_id,
                          });
                          await loadCurrentFolderData();
                        }
                      } catch (err) {
                        console.error(err);
                        alert(err.message || "Failed to move item");
                      } finally {
                        setDragItem(null);
                      }
                    }}
                    onClick={() => enterFolder(folder)}
                    style={{ cursor: "pointer" }}
                  >
                    <td>📁 {folder.name}</td>
                    <td>Folder</td>
                    <td>{new Date(folder.created_at).toLocaleString()}</td>
                    <td
                      className="table-actions-cell"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <div className="actions-menu-wrapper">
                        <button
                          type="button"
                          className="table-action-trigger"
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleMenu(folder.folder_id, "folder", e);
                          }}
                        >
                          ⋮
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}

                {/* Files */}
                {visibleFiles.length === 0 ? (
                  <tr>
                    <td colSpan={4} style={{ textAlign: "center" }}>
                      No files found
                    </td>
                  </tr>
                ) : (
                  visibleFiles.map((file) => (
                    <tr
                      key={file.file_id}
                      draggable
                      onDragStart={() =>
                        setDragItem({ type: "file", id: file.file_id })
                      }
                      onDragEnd={() => setDragItem(null)}
                    >
                      <td>{file.file_name}</td>
                      <td>{formatFileSize(file.file_size)}</td>
                      <td>{new Date(file.uploaded_at).toLocaleString()}</td>
                      <td className="table-actions-cell">
                        <div className="actions-menu-wrapper">
                          <button
                            type="button"
                            className="table-action-trigger"
                            onClick={(e) => {
                              e.stopPropagation();
                              toggleMenu(file.file_id, "file", e);
                            }}
                          >
                            ⋮
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </>
            )}
          </tbody>
        </table>
      </div>

      {/* File Info Modal */}
      {fileInfoModalOpen && fileInfoData && (
        <div className="modal-backdrop" onClick={closeFileInfo}>
          <div
            className="modal-content"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="modal-title">File Info</h3>
            <div className="modal-body">
              <p><strong>Name:</strong> {fileInfoData.file_name}</p>
              <p><strong>Size:</strong> {formatFileSize(fileInfoData.file_size)}</p>
              <p><strong>Uploaded:</strong> {new Date(fileInfoData.uploaded_at).toLocaleString()}</p>
              <p><strong>Erasure Profile:</strong> {fileInfoData.erasure_id}</p>
              <p><strong>Logical Path:</strong> {fileInfoData.logical_path}</p>
            </div>
            <div className="modal-footer">
              <button
                type="button"
                className="toolbar-action-btn"
                onClick={closeFileInfo}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
      
      {/* Share Modal */}
      {shareModalOpen && shareData && (
        <div
          className="modal-backdrop"
          onClick={() => setShowUserSuggestions(false)}
        >
          <div
            className="modal-content"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="modal-title">Share</h3>
            <div className="modal-body">
              <p>
                <strong>File/Folder:</strong> {shareData.fileName}
              </p>

              <div className="form-group">
                <label>One-Time Password (Optional)</label>
                <input
                  type="text"
                  className="toolbar-input"
                  placeholder="Leave empty for no password"
                  value={publicPassword}
                  onChange={(e) => setPublicPassword(e.target.value)}
                />
              </div>

              <div className="form-group">
                <label>Expires In</label>
                <select
                  className="toolbar-input"
                  value={publicExpires}
                  onChange={(e) => setPublicExpires(e.target.value)}
                >
                  <option value="never">Never</option>
                  <option value="1h">1 Hour</option>
                  <option value="24h">24 Hours</option>
                  <option value="1w">1 Week</option>
                  <option value="1m">1 Month</option>
                </select>
              </div>

              <div className="form-group">
                <label>Username to share with (Optional)</label>
                <div style={{ position: "relative" }}>
                  <input
                    type="text"
                    className="toolbar-input"
                    placeholder="Enter username..."
                    value={shareUsername}
                    onChange={handleShareUsernameChange}
                  />
                  {showUserSuggestions && userSuggestions.length > 0 && (
                    <div className="user-suggestions">
                      {userSuggestions.map((u) => (
                        <div
                          key={u.username}
                          className="user-suggestion"
                          onClick={() => handleSelectShareUser(u.username)}
                        >
                          <strong>{u.username}</strong>
                          <br />
                          <small>{u.email}</small>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              <div className="form-group">
                <label>Permissions</label>
                <select
                  className="toolbar-input"
                  value={sharePermissions}
                  onChange={(e) => setSharePermissions(e.target.value)}
                >
                  <option value="VIEW">View Only</option>
                  <option value="DOWNLOAD">Download</option>
                </select>
              </div>

              <div className="form-group">
                <label>Public Link (optional)</label>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <button
                    type="button"
                    className="toolbar-action-btn"
                    onClick={handleCreatePublicLink}
                    disabled={publicShareLoading}
                  >
                    {publicShareLoading ? "Generating..." : "Generate Link"}
                  </button>
                  {publicShareData && (
                    <button
                      type="button"
                      className="toolbar-action-btn"
                      onClick={() => {
                        const frontendBase = window.location.origin;
                        const fullUrl = `${frontendBase}/shares/files/access/${publicShareData.share_token}`;

                        const textToCopy = `${fullUrl}${
                          publicShareData.one_time_password
                            ? ` (password: ${publicShareData.one_time_password})`
                            : ""
                        }`;
                        navigator.clipboard.writeText(textToCopy).catch(() => {});
                      }}
                                      >
                                        Copy Link
                                      </button>
                                    )}
                </div>

                {publicShareData && (
                  <div style={{ marginTop: 8, fontSize: 13 }} className="share-url-text">
                    <div>
                      <strong>URL:</strong>{" "}
                      <code>{publicShareData.share_url}</code>
                    </div>
                    {publicShareData.one_time_password && (
                      <div>
                        <strong>Password:</strong>{" "}
                        <code>{publicShareData.one_time_password}</code>
                      </div>
                    )}
                    {publicShareData.expires_at && (
                      <div>
                        <strong>Expires:</strong>{" "}
                        {new Date(publicShareData.expires_at).toLocaleString()}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>

            <div className="modal-footer">
              <button
                type="button"
                className="toolbar-action-btn"
                onClick={handleSubmitShareToUser}
                disabled={shareLoading}
              >
                Share
              </button>
              <button
                type="button"
                className="toolbar-action-btn"
                onClick={() => {
                  setShareModalOpen(false);
                  setShareData(null);
                }}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {openMenuFileId && (
        <div
          className="actions-menu-dropdown floating-menu"
          style={{
            position: "fixed",
            top: menuPosition.y,
            left: menuPosition.x,
            zIndex: 9999,
          }}
          onClick={(e) => e.stopPropagation()}
        >
          {openMenuType === "folder" && (
            <>
              <button
                type="button"
                className="actions-menu-item"
                onClick={() => {
                  const folder = folders.find((f) => f.folder_id === openMenuFileId);
                  if (!folder) return;
                  closeMenu();
                  handleDownloadFolder(folder);
                }}
              >
                Download
              </button>

              <button
                type="button"
                className="actions-menu-item"
                onClick={() => {
                  const folder = folders.find((f) => f.folder_id === openMenuFileId);
                  if (!folder) return;
                  closeMenu();
                  handleSoftDeleteFolder(folder);
                }}
              >
                Delete
              </button>

              <div className="actions-menu-item">
                <select
                  className="search-input"
                  value={moveTargets[openMenuFileId] || ""}
                  onChange={(e) =>
                    handleMoveTargetChange(openMenuFileId, e.target.value)
                  }
                >
                  <option value="">Select folder</option>
                  {folders.map((f) => (
                    <option key={f.folder_id} value={f.folder_id}>
                      {f.name}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className="table-action-trigger"
                  style={{ marginLeft: 4 }}
                  onClick={() => {
                    const folder = folders.find((f) => f.folder_id === openMenuFileId);
                    if (!folder) return;
                    closeMenu();
                    handleMoveFolder(folder);
                  }}
                >
                  Move
                </button>
              </div>

              <button
                type="button"
                className="actions-menu-item"
                onClick={() => {
                  const folder = folders.find((f) => f.folder_id === openMenuFileId);
                  if (!folder) return;
                  closeMenu();
                  handleShareFolder(folder);
                }}
                disabled={shareLoading}
              >
                Share
              </button>
            </>
          )}

          {openMenuType === "file" && (
            <>
              <button
                type="button"
                className="actions-menu-item"
                onClick={() => {
                  const file = visibleFiles.find((f) => f.file_id === openMenuFileId);
                  if (!file) return;
                  closeMenu();
                  handleDownload(file);
                }}
              >
                Download
              </button>

              <button
                type="button"
                className="actions-menu-item"
                onClick={() => {
                  const file = visibleFiles.find((f) => f.file_id === openMenuFileId);
                  if (!file) return;
                  closeMenu();
                  handleSoftDeleteFile(file);
                }}
              >
                Delete
              </button>

              <div className="actions-menu-item">
                <select
                  className="search-input"
                  value={moveTargets[openMenuFileId] || ""}
                  onChange={(e) =>
                    handleMoveTargetChange(openMenuFileId, e.target.value)
                  }
                >
                  <option value="">Select folder</option>
                  {folders.map((f) => (
                    <option key={f.folder_id} value={f.folder_id}>
                      {f.name}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className="table-action-trigger"
                  style={{ marginLeft: 4 }}
                  onClick={() => {
                    const file = visibleFiles.find(
                      (f) => f.file_id === openMenuFileId
                    );
                    if (!file) return;
                    closeMenu();
                    handleMoveFile(file);
                  }}
                >
                  Move
                </button>
              </div>

              <button
                type="button"
                className="actions-menu-item"
                onClick={() => {
                  const file = visibleFiles.find((f) => f.file_id === openMenuFileId);
                  if (!file) return;
                  closeMenu();
                  handleShareFile(file);
                }}
                disabled={shareLoading}
              >
                Share
              </button>

              <button
                type="button"
                className="actions-menu-item"
                onClick={() => {
                  const file = visibleFiles.find((f) => f.file_id === openMenuFileId);
                  if (!file) return;
                  closeMenu();
                  openFileInfo(file);
                }}
              >
                File Info
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
};

export default UserDashboard;
