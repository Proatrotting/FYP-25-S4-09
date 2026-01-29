import React, { useState } from "react";
import '../styles/Testimonials.css';

const testimonialsData = [
  {
    id: 1,
    name: "CipherNerd",
    role: "Security Engineer, Startup",
    mood: "Mind-blown 🤯",
    title: "Finally, sharing secrets without anxiety",
    text: "Shard lets me split sensitive documents into secret shares so no single leak can expose the full file. I actually sleep better before production releases now.",
    highlight: "Zero-knowledge style sharing, no single point of failure.",
    rating: 5,
    usage: "Shares deployment keys and audit reports with the team.",
  },
  {
    id: 2,
    name: "CloudKoala",
    role: "DevOps Lead",
    mood: "Relieved 😌",
    title: "Perfect for ops and incident drills",
    text: "We use Shard to share credentials during incident drills. Even if someone screenshots a link, they still don’t have all the pieces.",
    highlight: "Secret sharing that still feels like normal file sharing.",
    rating: 5,
    usage: "Rotation of incident runbooks and access tokens.",
  },
  {
    id: 3,
    name: "PixelPenguin",
    role: "Freelance Designer",
    mood: "Impressed ✨",
    title: "Clients think I built a private vault",
    text: "I send design contracts and high-res assets via Shard. Clients love that their files are protected by a secret sharing scheme instead of just a password.",
    highlight: "Looks friendly, hides serious crypto under the hood.",
    rating: 4,
    usage: "Project contracts, invoices, and asset bundles.",
  },
  {
    id: 4,
    name: "RootAccess",
    role: "CTO, Fintech",
    mood: "Confident 🔐",
    title: "Exactly how sensitive files should be shared",
    text: "We deal with financial statements and internal risk models. Shard’s approach means no single storage node ever sees the entire file in the clear.",
    highlight: "Reduces the blast radius of any single compromise.",
    rating: 5,
    usage: "Board packs, risk models, internal financials.",
  },
];

const reasonsToUseShard = [
  "Files are split into cryptographic shards, so no single location has the full secret.",
  "Even if one shard is leaked, attackers get nothing useful without the others.",
  "Share links feel familiar, but under the hood a secret sharing scheme is protecting every file.",
  "You control how many shards are needed to reconstruct a file, balancing convenience and security.",
  "Great for teams that handle credentials, financial reports, or any \"please don’t leak this\" document.",
];

export default function Testimonials() {
  const [activeIndex, setActiveIndex] = useState(0);
  const [hoveredReason, setHoveredReason] = useState(null);

  const activeTestimonial = testimonialsData[activeIndex];

  const handleDotClick = (index) => {
    setActiveIndex(index);
  };

  const handleNext = () => {
    setActiveIndex((prev) => (prev + 1) % testimonialsData.length);
  };

  const handlePrev = () => {
    setActiveIndex((prev) =>
      prev === 0 ? testimonialsData.length - 1 : prev - 1
    );
  };

  return (
    <div className="home-container testimonials-page">
      <main className="main-content">
        <section className="card testimonials-hero">
          <div className="testimonials-hero-top">
            <h2>What people say about Shard</h2>
            <p className="testimonials-tagline">
              Real humans. Real secrets.{" "}
              <span className="tagline-highlight">Less panic when sharing files.</span>
            </p>
          </div>

          <div className="testimonials-carousel">
            <button
              className="carousel-arrow left"
              onClick={handlePrev}
              aria-label="Previous testimonial"
            >
              ‹
            </button>

            <div className="testimonial-card">
              <div className="testimonial-header">
                <div className="avatar-bubble">
                  {activeTestimonial.name.charAt(0)}
                </div>
                <div className="testimonial-header-text">
                  <div className="testimonial-name-row">
                    <h3>{activeTestimonial.name}</h3>
                    <span className="testimonial-mood">
                      {activeTestimonial.mood}
                    </span>
                  </div>
                  <p className="testimonial-role">{activeTestimonial.role}</p>
                </div>
              </div>

              <div className="testimonial-rating">
                {Array.from({ length: 5 }).map((_, i) => (
                  <span
                    key={i}
                    className={
                      i < activeTestimonial.rating ? "star star-full" : "star"
                    }
                  >
                    ★
                  </span>
                ))}
              </div>

              <h4 className="testimonial-title">{activeTestimonial.title}</h4>
              <p className="testimonial-text">{activeTestimonial.text}</p>

              <div className="testimonial-highlight">
                <span className="highlight-label">Why they love Shard</span>
                <p>{activeTestimonial.highlight}</p>
              </div>

              <p className="testimonial-usage">
                <span className="usage-label">What they share: </span>
                {activeTestimonial.usage}
              </p>
            </div>

            <button
              className="carousel-arrow right"
              onClick={handleNext}
              aria-label="Next testimonial"
            >
              ›
            </button>
          </div>

          <div className="carousel-dots">
            {testimonialsData.map((t, index) => (
              <button
                key={t.id}
                className={
                  index === activeIndex
                    ? "carousel-dot active"
                    : "carousel-dot"
                }
                onClick={() => handleDotClick(index)}
                aria-label={`Show testimonial ${index + 1}`}
              />
            ))}
          </div>
        </section>

        <section className="card why-shard-card">
          <h2>Why Shard is secretly your new favorite file sharing tool</h2>
          <p className="why-intro">
            Under the friendly UI, Shard uses a secret sharing scheme to protect
            your files so a single leak does not reveal the entire secret.
          </p>

          <div className="reasons-grid">
            {reasonsToUseShard.map((reason, idx) => (
              <button
                key={idx}
                className={
                  hoveredReason === idx
                    ? "reason-chip reason-chip-active"
                    : "reason-chip"
                }
                onMouseEnter={() => setHoveredReason(idx)}
                onMouseLeave={() => setHoveredReason(null)}
              >
                <span className="reason-index">{idx + 1}</span>
                <span className="reason-text">{reason}</span>
              </button>
            ))}
          </div>

          <div className="cta-row">
            <p className="cta-text">
              Ready to share files the way your future self will thank you for?
            </p>
            <button
              className="register-btn testimonials-cta-btn"
              onClick={() => {
                window.location.href = "/RegisterForm";
              }}
            >
              Start sharing with Shard
            </button>
          </div>
        </section>
      </main>
    </div>
  );
}