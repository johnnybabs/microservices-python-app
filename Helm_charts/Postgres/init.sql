CREATE TABLE auth_user (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email VARCHAR (255) NOT NULL,
    password VARCHAR (255) NOT NULL
);

-- SECURITY: the password column stores plaintext, and the auth service compares
-- it in plaintext. This is acceptable only for a learning/demo deployment. For
-- production: store a bcrypt/argon2 hash here and verify it with a constant-time
-- comparison in auth-service/server.py. Do not commit real credentials.
--Add Username and Password for Admin User
-- INSERT INTO auth_user (email, password) VALUES ('thomasfookins007helby@gmail.com', 'YourPassword123');
INSERT INTO auth_user (email, password) VALUES ('johnbsignups@gmail.com', 'YourPassword123');