-- migrations/001_add_status_to_cars.sql
ALTER TABLE cars ADD COLUMN status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'past'));