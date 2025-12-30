import React from "react";
import "../styles/ContactUs.css";

function ContactUs() {
  return (
    <div className="contactus-container">
      <h2>Contact Us</h2>
      <div className="contactus-content card">
        <div className="contactus-form-section">
          <form
            className="contactus-form"
            action="https://formspree.io/f/xjgvdyro"
            method="POST"
          >
            <div className="form-group">
              <label htmlFor="contact-name">Name</label>
              <input id="contact-name" type="text" name="name" placeholder="Your name" required />
            </div>
            <div className="form-group">
              <label htmlFor="contact-email">Email</label>
              <input id="contact-email" type="email" name="email" placeholder="Your email" required />
            </div>
            <div className="form-group">
              <label htmlFor="contact-message">Message</label>
              <textarea id="contact-message" name="message" rows="4" placeholder="How can we help you?" required />
            </div>
            <button className="contactus-btn" type="submit">Send Message</button>
          </form>

          <div className="contactus-details">
            <h3>Our Address</h3>
            <div>
              SIM Headquarters<br />
              461 Clementi Road<br />
              Singapore 599491
            </div>
            <div>
              <strong>Email:</strong> <a href="mailto:shardteam@gmail.com" className="cu-link">shardteam@gmail.com</a>
            </div>
            <div>
              <strong>Phone:</strong> <a href="tel:+6566554433" className="cu-link">+65 6655 4433</a>
            </div>
            <div className="contactus-hours">
              <strong>Hours:</strong> Mon–Fri: 9am – 6pm
            </div>
          </div>
        </div>
        <div className="contactus-map-section">
          <iframe
            className="contactus-map"
            src="https://maps.google.com/maps?q=Singapore%20Institute%20of%20Management%2C%20461%20Clementi%20Road%2C%20599491&t=&z=15&ie=UTF8&iwloc=&output=embed"
            allowFullScreen=""
            loading="lazy"
            referrerPolicy="no-referrer-when-downgrade"
            title="SIM Location"
            aria-label="Map"
          ></iframe>
        </div>
      </div>
    </div>
  );
}

export default ContactUs;
