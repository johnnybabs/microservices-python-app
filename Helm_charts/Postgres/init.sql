CREATE TABLE IF NOT EXISTS auth_user (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email VARCHAR (255) NOT NULL UNIQUE,
    password VARCHAR (255) NOT NULL,
    role VARCHAR (32) NOT NULL DEFAULT 'user',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- SECURITY: the password column stores a bcrypt hash (NOT plaintext). The auth
-- service verifies logins with bcrypt.checkpw (constant-time) and hashes new
-- sign-ups with bcrypt.hashpw. Never commit real hashes or plaintext to a public
-- repo. Before applying, replace the placeholders below with your own admin email
-- and a freshly generated hash:
--   python3 -c "import bcrypt; print(bcrypt.hashpw(b'<your-password>', bcrypt.gensalt(rounds=12)).decode())"
--
-- RBAC: every row has a role. 'admin' unlocks Dashboard/Architecture/Users in the
-- frontend and any admin-gated backend endpoint; 'user' is the default for sign-ups.

-- Seed admin accounts. ON CONFLICT makes this re-runnable on cluster rebuilds:
-- re-applying init.sql resets the seeded admins' role + password hash without
-- erroring on the UNIQUE(email) constraint.
INSERT INTO auth_user (email, password, role)
VALUES ('admin@example.com', '<BCRYPT_HASH_HERE>', 'admin')
ON CONFLICT (email) DO UPDATE SET role = EXCLUDED.role, password = EXCLUDED.password;
