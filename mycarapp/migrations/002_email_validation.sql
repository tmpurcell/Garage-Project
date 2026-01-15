-- -- Update users table
-- ALTER TABLE users ADD COLUMN email TEXT UNIQUE;
-- ALTER TABLE users ADD COLUMN first_name TEXT;
-- ALTER TABLE users ADD COLUMN display_name TEXT;

-- -- Migrate existing data
-- UPDATE users SET email = username || '@example.com' WHERE email IS NULL;