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
    console.log('Drag handle clicked');
    setIsDraggingHandle(true);
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleMouseMove = useCallback(
    (e) => {
      if (!isDraggingHandle) return;
      const clientY = e.clientY || e.touches?.[0]?.clientY;
      const newHeight = Math.max(80, Math.min(400, window.innerHeight - clientY + 20));
      setHeight(newHeight);
    },
    [isDraggingHandle]
  );

  const handleMouseUp = useCallback(() => {
    setIsDraggingHandle(false);
  }, []);

  // Global drag handlers
  useEffect(() => {
    if (isDraggingHandle) {
      document.addEventListener("mousemove", handleMouseMove);
      document.addEventListener("mouseup", handleMouseUp);
      document.addEventListener("touchmove", handleMouseMove, { passive: false });
      document.addEventListener("touchend", handleMouseUp);
      
      return () => {
        document.removeEventListener("mousemove", handleMouseMove);
        document.removeEventListener("mouseup", handleMouseUp);
        document.removeEventListener("touchmove", handleMouseMove);
        document.removeEventListener("touchend", handleMouseUp);
      };
    }
  }, [handleMouseMove, handleMouseUp, isDraggingHandle]);

  const toggleQueue = () => {
    setIsHidden(prev => !prev);
  };

  if (isHidden && uploadQueue.length === 0) {
    // Show small reopen button when hidden and queue empty
    return (
      <div 
        className="upload-queue-toggle" 
        onClick={toggleQueue}
      >
        ↑
      </div>
    );
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
          <button type="button" onClick={toggleQueue}>
            {isHidden ? 'Show' : 'Hide'}
          </button>
          <div
            className="drag-handle"
            onMouseDown={handleMouseDown}
            onTouchStart={handleMouseDown}
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
          <div className="empty-queue">
            No uploads in progress.
          </div>
        ) : (
          uploadQueue.map(({ id, name, progress = 0, status = 'pending', timeLeft = '00:00' }) => (
            <div key={id} className="queue-row">
              <span>{name}</span>
              <span>{timeLeft}</span>
              <div className="progress-bar">
                <div
                  className="progress-fill"
                  style={{ width: `${progress}%` }}
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