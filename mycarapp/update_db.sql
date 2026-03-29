-- Add new columns to cars table
-- VIN number column
ALTER TABLE cars ADD COLUMN vin TEXT;

-- Purchase mileage column  
ALTER TABLE cars ADD COLUMN purchase_mileage REAL;

-- Sold mileage column
ALTER TABLE cars ADD COLUMN sold_mileage REAL;

-- Purchase hours column (for boats)
ALTER TABLE cars ADD COLUMN purchase_hours REAL;
