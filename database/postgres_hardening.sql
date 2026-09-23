-- Run once on the production PostgreSQL database as the owner role, after the tables exist.
-- The application connects as skillsprint_app, which may read and write normally but can only
-- INSERT into audit_log. The audit trail stays append-only even if application code is wrong.

CREATE ROLE skillsprint_app LOGIN PASSWORD 'choose-a-strong-password';
GRANT CONNECT ON DATABASE skillsprint TO skillsprint_app;
GRANT USAGE ON SCHEMA public TO skillsprint_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO skillsprint_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO skillsprint_app;

REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM skillsprint_app;
