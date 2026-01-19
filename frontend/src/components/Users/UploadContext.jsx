import React, { createContext, useContext, useState } from 'react';

const UploadContext = createContext();

export const UploadProvider = ({ children }) => {
  const [uploadQueue, setUploadQueue] = useState([]); // [{id, file, name, progress:0, status:'pending|uploading|success|error', timeLeft}]

  const addToQueue = (file, folderId, erasureId) => {
    const id = Date.now() + Math.random();
    setUploadQueue(prev => [...prev, {id, file, name: file.name, folderId, erasureId, progress: 0, status: 'pending', timeLeft: '00:00'}]);
    return id;
  };

  const updateQueueItem = (id, updates) => {
    setUploadQueue(prev => prev.map(item => item.id === id ? {...item, ...updates} : item));
  };

  const removeFromQueue = (id) => {
    setUploadQueue(prev => prev.filter(item => item.id !== id));
  };

  return (
    <UploadContext.Provider value={{uploadQueue, addToQueue, updateQueueItem, removeFromQueue}}>
      {children}
    </UploadContext.Provider>
  );
};

export const useUploadQueue = () => useContext(UploadContext);