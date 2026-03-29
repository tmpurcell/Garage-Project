#!/usr/bin/env python3
"""
Setup script to create initial database with Flask-Migrate
"""

import os
from app import app, db

def setup_database():
    """Create the database tables"""
    with app.app_context():
        # Create all tables
        db.create_all()
        print("Database tables created successfully!")
        
        # Stamp the database with the latest migration
        from flask_migrate import stamp
        stamp()
        print("Database stamped with latest migration!")

if __name__ == '__main__':
    setup_database()
