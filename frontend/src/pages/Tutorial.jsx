import React from "react";
import "../styles/Tutorial.css";

function Tutorial() {
  return (
    <div className="home-container">
      <main className="main-content">
        <section className="card tutorial-intro">
          <h2>Tutorial: Getting Started with Shard</h2>
          <p>
            This tutorial walks you through how to sign up, upload files, share
            them securely, and manage your storage so you can start using
            Shard with confidence.
          </p>
          <p>
            We will cover the basic navigation of the web app, how to create
            folders, upload documents, and generate share links that you can
            send to others.
          </p>
        </section>

        <section className="card tutorial-video">
          <h2>Watch the Video Walkthrough</h2>
          <p>
            Prefer a visual guide? Watch this short video for a step-by-step
            walkthrough of the main features.
          </p>

          <div className="video-wrapper">
            <iframe
              src="https://www.youtube.com/embed/CGQBEaonNt0"
              title="Shard File Sharing and Recovery System Tutorial"
              allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
              referrerPolicy="strict-origin-when-cross-origin"
              allowFullScreen
            ></iframe>
          </div>
        </section>

        <section className="card tutorial-steps">
          <h2>Key Steps Shown in the Video</h2>
          <ol>
            <li>
              Sign up or log in using your Shard account so you can access
              your personal storage space.
            </li>
            <li>
              Navigate to your dashboard, create folders to organize your files,
              and upload documents or media from your device.
            </li>
            <li>
              Use the share options to generate secure links and configure
              access permissions before sending them to others.
            </li>
            <li>
              Manage existing files by renaming, moving, or deleting items to
              keep your storage organized and easy to browse.
            </li>
          </ol>
          <p className="tutorial-note">
            You can pause the video at any time and follow along in a separate
            browser tab while using your own Shard account.
          </p>
          <button 
            className="register-btn"
            onClick={() => navigate("/")} 
        >
            Create Your Account Now
          </button>
        </section>
      </main>
    </div>
  );
}

export default Tutorial;