CREATE DATABASE IF NOT EXISTS college_event_db;
USE college_event_db;

CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    email VARCHAR(120) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role ENUM('student', 'organizer', 'hod', 'admin') NOT NULL DEFAULT 'student',
    is_class_incharge BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS events (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(150) NOT NULL,
    description TEXT,
    venue VARCHAR(150) NOT NULL,
    event_date DATETIME NOT NULL,
    registration_deadline DATETIME NOT NULL,
    max_participants INT NOT NULL,
    is_intercollege BOOLEAN NOT NULL DEFAULT FALSE,
    ticket_fee DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    organizer_id INT NOT NULL,
    status ENUM('pending_hod', 'hod_approved', 'approved', 'rejected', 'completed') NOT NULL DEFAULT 'pending_hod',
    CONSTRAINT fk_events_organizer FOREIGN KEY (organizer_id) REFERENCES users(id),
    CONSTRAINT max_participants_positive CHECK (max_participants > 0),
    CONSTRAINT ticket_fee_non_negative CHECK (ticket_fee >= 0)
);

CREATE TABLE IF NOT EXISTS registrations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    event_id INT NOT NULL,
    registered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, event_id),
    CONSTRAINT fk_registrations_user FOREIGN KEY (user_id) REFERENCES users(id),
    CONSTRAINT fk_registrations_event FOREIGN KEY (event_id) REFERENCES events(id)
);

CREATE TABLE IF NOT EXISTS feedback (
    id INT AUTO_INCREMENT PRIMARY KEY,
    event_id INT NOT NULL,
    user_id INT NOT NULL,
    rating INT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comments TEXT,
    submitted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (event_id, user_id),
    CONSTRAINT fk_feedback_event FOREIGN KEY (event_id) REFERENCES events(id),
    CONSTRAINT fk_feedback_user FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS pa_points (
    id INT AUTO_INCREMENT PRIMARY KEY,
    event_id INT NOT NULL UNIQUE,
    base_points INT DEFAULT 10,
    bonus_participants INT DEFAULT 0,
    bonus_feedback INT DEFAULT 0,
    bonus_intercollege INT DEFAULT 0,
    total_points INT NOT NULL,
    CONSTRAINT fk_pa_points_event FOREIGN KEY (event_id) REFERENCES events(id)
);

CREATE TABLE IF NOT EXISTS reports (
    id INT AUTO_INCREMENT PRIMARY KEY,
    generated_by INT NOT NULL,
    academic_year VARCHAR(20) NOT NULL,
    generated_on DATETIME DEFAULT CURRENT_TIMESTAMP,
    file_path VARCHAR(255) NOT NULL,
    CONSTRAINT fk_reports_user FOREIGN KEY (generated_by) REFERENCES users(id)
);
