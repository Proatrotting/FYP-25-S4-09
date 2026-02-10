import React, { useState, useCallback, useRef, useEffect } from 'react';
import { useUploadQueue } from './UploadContext';
import '../../styles/Users/UploadQueue.css'; 

const UploadQueue = () => {
  const { uploadQueue, removeFromQueue } = useUploadQueue();
  const [height, setHeight] = useState(80);
  const [isDraggingHandle, setIsDraggingHandle] = useState(false);
  const [isHidden, setIsHidden] = useState(false);
  const barRef = useRef(null);

  const handleMouseDown = useCallback((e) => {
    setIsDraggingHandle(true);
    e.preventDefault();
  }, []);

  const handleMouseMove = useCallback(
    (e) => {
      if (!isDraggingHandle || !barRef.current) return;
      const rect = barRef.current.getBoundingClientRect();
      const newHeight = window.innerHeight - rect.top;
      setHeight(Math.max(80, Math.min(400, newHeight)));
    },
    [isDraggingHandle]
  );

  const handleMouseUp = useCallback(() => {
    setIsDraggingHandle(false);
  }, []);

  useEffect(() => {
    if (isDraggingHandle) {
      document.addEventListener("mousemove", handleMouseMove);
      document.addEventListener("mouseup", handleMouseUp);
      return () => {
        document.removeEventListener("mousemove", handleMouseMove);
        document.removeEventListener("mouseup", handleMouseUp);
      };
    }
  }, [handleMouseMove, handleMouseUp, isDraggingHandle]);

  const handleTouchStart = (e) => {
    setIsDraggingHandle(true);
    e.preventDefault();
  };

  const handleTouchMove = (e) => {
    if (!barRef.current) return;
    const rect = barRef.current.getBoundingClientRect();
    const newHeight = window.innerHeight - rect.top;
    setHeight(Math.max(80, Math.min(400, newHeight)));
  };

  const handleTouchEnd = () => {
    setIsDraggingHandle(false);
  };

  if (isHidden) {
    return null;
  }

  return (
    <div
      ref={barRef}
      className="upload-queue-container"
      style={{ height: `${height}px` }}
    >
      <div className="upload-queue-header">
        <div className="upload-queue-title">
          Upload Queue{uploadQueue.length > 0 ? ` (${uploadQueue.length})` : ""}
        </div>
        <div className="queue-actions">
          <button type="button" onClick={() => setIsHidden(true)}>
            Hide
          </button>
          <div
            className="drag-handle"
            onMouseDown={handleMouseDown}
            onTouchStart={handleTouchStart}
            onTouchMove={handleTouchMove}
            onTouchEnd={handleTouchEnd}
          >
            ⋮⋮
          </div>
        </div>
      </div>

      <div className="upload-queue-columns">
        <span>File</span>
        <span>Time Left</span>
        <span>Progress</span>
        <span>Status</span>
      </div>

      <div className="upload-queue-list">
        {uploadQueue.length === 0 ? (
          <div
            className="empty-queue"
            style={{ padding: "16px", textAlign: "center", color: "#9ca3af" }}
          >
            No uploads in progress.
          </div>
        ) : (
          uploadQueue.map(({ id, name, progress, status, timeLeft }) => (
            <div key={id} className="queue-row">
              <span>{name}</span>
              <span>{timeLeft}</span>
              <div className="progress-bar">
                <div
                  className="progress-fill"
                  style={{ width: `${progress || 0}%` }}
                />
              </div>
              <span className={`status ${status}`}>{status}</span>
              <button type="button" onClick={() => removeFromQueue(id)}>
                ×
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  );
};

export default UploadQueue;