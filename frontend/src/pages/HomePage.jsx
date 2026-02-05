import React from "react";
import '../styles/HomePage.css';


function HomePage({ toggleRegister }) {
  return (
    <div className="home-container">
      <div className="main-content">
        <section className="about-us card">
          <h2>About Us</h2>
          <p>
            Shard is a secure file sharing and data recovery platform designed to protect sensitive information through secret-sharing techniques. Instead of storing a full file in one location, Shard splits each file into multiple encrypted fragments and stores them across user-selected devices or locations. A file can only be reconstructed when a minimum number of fragments are collected, offering strong security, resilience against device loss, and protection beyond traditional encryption systems.<br /><br />
            With an intuitive interface, Shard allows users to manage, distribute, and recover their files easily and securely. Whether storing fragments on USB drives, external disks, or local directories, users gain full control over how their data is distributed, accessed, and recovered. Shard combines security, fault tolerance, and usability, making it an ideal solution for individuals and organizations that require reliable protection of sensitive files.
          </p>
        </section>

        <button className="register-btn" onClick={toggleRegister}>
          Register
        </button>

        <section className="system-requirements card">
          <h2>🖥️ System Requirements for Users</h2>
          <ol>
            <li>
              <strong>Supported Platforms</strong>
              <ul>
                <li>Windows 10 or later</li>
                <li>macOS 10.15 or later</li>
                <li>Ubuntu Linux 20.04 or later</li>
                <li>File splitting and fragment storage are optimized for desktop environments.</li>
              </ul>
            </li>
            <li>
              <strong>Supported Web Browsers</strong>
              <ul>
                <li>Google Chrome (recommended)</li>
                <li>Microsoft Edge</li>
                <li>Mozilla Firefox</li>
                <li>Safari (latest versions)</li>
                <li>Browser must support: HTML5 file handling, Local file system access via pickers, Web Notifications API, Secure HTTPS connections</li>
              </ul>
            </li>
            <li>
              <strong>Hardware Requirements</strong>
              <ul>
                <li>Minimum: 4 GB RAM, free disk space ≥ 2× file size (for temp processing), USB ports</li>
                <li>Recommended: 8 GB RAM+, SSD storage, multiple external storage devices</li>
              </ul>
            </li>
            <li>
              <strong>Network Requirements</strong>
              <ul>
                <li>Internet required for login (SSO), metadata sync, activity logs, sharing fragments.</li>
                <li>Offline: file splitting, fragment storage, reconstruction, local notifications</li>
                <li>Core operations possible offline after authentication</li>
              </ul>
            </li>
            <li>
              <strong>Permissions and Security Requirements</strong>
              <ul>
                <li>Browser permission to read and save local files</li>
                <li>Browser permission for notifications (optional)</li>
                <li>Ability to read/write to storage devices selected</li>
                <li>Optional: 2FA for enhanced security</li>
              </ul>
            </li>
            <li>
              <strong>File Compatibility</strong>
              <ul>
                <li>Documents (PDF, DOCX, XLSX)</li>
                <li>Images (PNG, JPG)</li>
                <li>Videos</li>
                <li>ZIP/RAR archives</li>
                <li>Binary and custom data formats</li>
                <li>Maximum file size depends on server configuration.</li>
              </ul>
            </li>
          </ol>
        </section>
      </div>
    </div>   
  );
}

export default HomePage;
