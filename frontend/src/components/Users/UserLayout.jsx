import React, { useEffect, useState, useCallback } from "react";
import { Outlet } from "react-router-dom";
import UsersNavBar from "./UsersNavBar";
import UploadQueue from "./UploadQueue";
import { UploadProvider } from './UploadContext';
import { getStorageUsage } from "../../services/UserService";

const UserLayout = () => {
  const [storageUsage, setStorageUsage] = useState(null);
  const [loadingUsage, setLoadingUsage] = useState(true);
  const [usageError, setUsageError] = useState(null);

  const refreshUsage = useCallback(async () => {
    let isMounted = true;
    setLoadingUsage(true);
    setUsageError(null);

    try {
      const data = await getStorageUsage();
      if (isMounted) {
        setStorageUsage(data);
      }
    } catch (err) {
      if (isMounted) {
        console.error("Failed to load storage usage", err);
        setUsageError(err.message || "Failed to load storage usage");
      }
    } finally {
      if (isMounted) {
        setLoadingUsage(false);
      }
    }

    return () => {
      isMounted = false;
    };
  }, []);

  useEffect(() => {
    // initial load
    refreshUsage();
  }, [refreshUsage]);

  return (
    <UploadProvider>  {/* Wrap everything for queue context */}
      <UsersNavBar
        storageUsage={storageUsage}
        loadingUsage={loadingUsage}
        usageError={usageError}
      >
        {/* Routed content */}
        <Outlet context={{ refreshUsage }} />
        
        {/* Fixed upload queue at bottom */}
        <UploadQueue />
      </UsersNavBar>
    </UploadProvider>
  );
};

export default UserLayout;