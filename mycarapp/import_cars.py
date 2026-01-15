import sqlite3
import csv
from pathlib import Path

# Paths
db_path = 'cars.db'
csv_path = 'cars_export.csv'

# Connect to the database
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Read the CSV file
with open(csv_path, 'r') as f:
    reader = csv.reader(f)
    # Skip header if exists
    next(reader, None)
    
    # Insert each car with the new user_id
    for row in reader:
        # Assuming the columns are: id, make, model, year, image_path
        cursor.execute('''
            INSERT INTO cars (make, model, year, image_path, user_id)
            VALUES (?, ?, ?, ?, 1)
        ''', (row[1], row[2], row[3], row[4] if len(row) > 4 else None))

# Commit changes and close
conn.commit()
conn.close()