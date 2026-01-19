import React, { useState, useCallback, useRef, useEffect } from 'react';
import { useUploadQueue } from './UploadContext'; // adjust path
import '../../styles/Users/UploadQueue.css'; 

const UploadQueue = () => {
  const { uploadQueue, removeFromQueue } = useUploadQueue();
  const [height, setHeight] = useState(80); // min 80px
  const [isDraggingHandle, setIsDraggingHandle] = useState(false);
  const [isHidden, setIsHidden] = useState(false);
  const barRef = useRef(null);

  const handleMouseDown = useCallback((e) => {
    setIsDraggingHandle(true);
    e.preventDefault();
  }, []);

  const handleMouseMove = useCallback((e) => {
    if (!isDraggingHandle || !barRef.current) return;
    const rect = barRef.current.getBoundingClientRect();
    const newHeight = window.innerHeight - rect.top;
    setHeight(Math.max(80, Math.min(400, newHeight)));
  }, [isDraggingHandle]);

  const handleMouseUp = useCallback(() => {
    setIsDraggingHandle(false);
  }, []);

  useEffect(() => {
    if (isDraggingHandle) {
      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
      return () => {
        document.removeEventListener('mousemove', handleMouseMove);
        document.removeEventListener('mouseup', handleMouseUp);
      };
    }
  }, [handleMouseMove, handleMouseUp, isDraggingHandle]);

  // Touch for mobile
  const handleTouchStart = (e) => {
    setIsDraggingHandle(true);
    e.preventDefault();
  };

  return (
    <div ref={barRef} className="upload-queue-container" style={{ height: `${height}px` }}>
      <div className="upload-queue-header">
        <div className="upload-queue-title">Upload Queue ({uploadQueue.length})</div>
        <div className="queue-actions">
          <button onClick={() => setIsHidden(true)}>Hide</button>
          <div className="drag-handle" onMouseDown={handleMouseDown} onTouchStart={handleTouchStart}>⋮⋮</div>
        </div>
      </div>
      <div className="upload-queue-columns">
        <span>File</span>
        <span>Time Left</span>
        <span>Progress</span>
        <span>Status</span>
      </div>
      <div className="upload-queue-list">
        {uploadQueue.map(({ id, name, progress, status, timeLeft }) => (
          <div key={id} className="queue-row">
            <span>{name}</span>
            <span>{timeLeft}</span>
            <div className="progress-bar">
              <div className="progress-fill" style={{ width: `${progress}%` }} />
            </div>
            <span className={`status ${status}`}>{status}</span>
            <button onClick={() => removeFromQueue(id)}>×</button>
          </div>
        ))}
      </div>
    </div>
  );
};

export default UploadQueue;
