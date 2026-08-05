from flask import Flask, render_template, request, redirect, url_for, send_from_directory, flash, session, abort, jsonify
import sqlite3
import os
import time
import hashlib
import secrets
import string
import random
from functools import wraps
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from urllib.parse import urlparse
from PIL import Image
import io

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'  # Change this to a secure secret key

@app.template_filter('currency')
def currency(value):
    try:
        return f"${float(value):,.2f}"
    except (ValueError, TypeError):
        return "$0.00"


DATABASE = 'cars.db'
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'pdf'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Create uploads directory if it doesn't exist
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_user_upload_folder(user_id):
    """Get or create upload folder for a specific user"""
    user_folder = os.path.join(UPLOAD_FOLDER, str(user_id))
    if not os.path.exists(user_folder):
        os.makedirs(user_folder)
    return user_folder

def generate_friend_code():
    """Generate a unique friend code in format GRG-XXXXXX"""
    while True:
        # Generate 6 random alphanumeric characters
        chars = string.ascii_uppercase + string.digits
        random_part = ''.join(random.choices(chars, k=6))
        friend_code = f"GRG-{random_part}"
        return friend_code

def compress_image(file_stream, max_size=(1200, 1200), quality=85):
    """
    Compress an image to reduce file size while maintaining quality
    Args:
        file_stream: The uploaded file stream
        max_size: Maximum dimensions (width, height)
        quality: JPEG quality (1-100)
    Returns:
        Compressed image bytes
    """
    try:
        # Open the image
        img = Image.open(file_stream)
        
        # Convert RGBA to RGB if necessary
        if img.mode in ('RGBA', 'LA'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = background
        elif img.mode == 'P':
            img = img.convert('RGB')
        
        # Resize if larger than max_size
        if img.size[0] > max_size[0] or img.size[1] > max_size[1]:
            img.thumbnail(max_size, Image.Resampling.LANCZOS)
        
        # Compress and save to bytes
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='JPEG', quality=quality, optimize=True)
        img_byte_arr.seek(0)
        
        return img_byte_arr.getvalue()
    except Exception as e:
        print(f"Error compressing image: {e}")
        # Return original file if compression fails
        file_stream.seek(0)
        return file_stream.read()

def url_parse(url):
    return urlparse(url)

def get_db_connection():
    conn = sqlite3.connect('cars.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with sqlite3.connect(DATABASE) as conn:
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS cars (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                vehicle_type TEXT NOT NULL DEFAULT 'Car',
                make TEXT NOT NULL,
                model TEXT NOT NULL,
                year INTEGER NOT NULL,
                image_path TEXT,
                status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'past')),
                reason TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                email TEXT UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS maintenance_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                car_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                mileage INTEGER,
                service_type TEXT NOT NULL,
                description TEXT,
                cost REAL,
                shop_name TEXT,
                FOREIGN KEY (car_id) REFERENCES cars (id) ON DELETE CASCADE
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS aftermarket_parts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                car_id INTEGER NOT NULL,
                part_name TEXT NOT NULL,
                brand TEXT,
                install_date TEXT,
                cost REAL,
                notes TEXT,
                FOREIGN KEY (car_id) REFERENCES cars (id) ON DELETE CASCADE
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS scheduled_maintenance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                car_id INTEGER NOT NULL,
                service_type TEXT NOT NULL,
                due_date TEXT,
                due_mileage INTEGER,
                reminder_enabled INTEGER DEFAULT 0,
                notes TEXT,
                completed INTEGER DEFAULT 0,
                FOREIGN KEY (car_id) REFERENCES cars (id) ON DELETE CASCADE
            )
        ''')

def migrate_db():
    """
    Runs schema migrations on startup. Safe to run every time —
    only applies changes that haven't been applied yet.
    Add new migrations as version < N blocks below.
    """
    with sqlite3.connect(DATABASE) as conn:
        c = conn.cursor()

        # Create version tracking table
        c.execute('''CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)''')
        conn.commit()

        row = c.execute('SELECT version FROM schema_version').fetchone()
        version = row[0] if row else 0

        if version < 1:
            # Migration 1 - original columns added via ALTER TABLE
            migrations = [
                "ALTER TABLE cars ADD COLUMN hours REAL",
                "ALTER TABLE cars ADD COLUMN miles REAL",
                "ALTER TABLE cars ADD COLUMN vin TEXT",
                "ALTER TABLE cars ADD COLUMN purchase_mileage REAL",
                "ALTER TABLE cars ADD COLUMN sold_mileage REAL",
                "ALTER TABLE cars ADD COLUMN purchase_hours REAL",
                "ALTER TABLE cars ADD COLUMN purchase_date TEXT",
                "ALTER TABLE cars ADD COLUMN sell_date TEXT",
            ]
            for sql in migrations:
                try:
                    c.execute(sql)
                except sqlite3.OperationalError:
                    pass  # Column already exists
            c.execute('DELETE FROM schema_version')
            c.execute('INSERT INTO schema_version (version) VALUES (1)')
            conn.commit()

        if version < 2:
            # Migration 2 - add receipt_image to maintenance_records and aftermarket_parts
            migrations = [
                "ALTER TABLE maintenance_records ADD COLUMN receipt_image TEXT",
                "ALTER TABLE aftermarket_parts ADD COLUMN receipt_image TEXT",
            ]
            for sql in migrations:
                try:
                    c.execute(sql)
                except sqlite3.OperationalError:
                    pass  # Column already exists
            c.execute('DELETE FROM schema_version')
            c.execute('INSERT INTO schema_version (version) VALUES (2)')
            conn.commit()

        if version < 4:
            # Migration 3 - add friends feature tables and columns
            migrations = [
                "ALTER TABLE users ADD COLUMN friend_code TEXT",
                "ALTER TABLE cars ADD COLUMN is_public_to_friends INTEGER DEFAULT 0",
                "ALTER TABLE cars ADD COLUMN public_vin INTEGER DEFAULT 1",
                "ALTER TABLE cars ADD COLUMN public_miles INTEGER DEFAULT 1",
                "ALTER TABLE cars ADD COLUMN public_purchase_info INTEGER DEFAULT 1",
                '''CREATE TABLE IF NOT EXISTS friendships (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    requester_id INTEGER NOT NULL,
                    addressee_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )''',
                "ALTER TABLE cars ADD COLUMN status TEXT DEFAULT 'active'",
                "ALTER TABLE cars ADD COLUMN reason TEXT",
                "ALTER TABLE cars ADD COLUMN sell_date TEXT",
                "ALTER TABLE cars ADD COLUMN sold_mileage REAL",
                "ALTER TABLE cars ADD COLUMN purchase_date TEXT",
                "ALTER TABLE cars ADD COLUMN purchase_mileage REAL",
                "ALTER TABLE cars ADD COLUMN purchase_hours REAL",
                "ALTER TABLE cars ADD COLUMN hours REAL",
            ]
            for sql in migrations:
                try:
                    c.execute(sql)
                except sqlite3.OperationalError:
                    pass  # Column/table already exists
            
            # Generate friend codes for existing users
            c.execute('SELECT id FROM users WHERE friend_code IS NULL')
            existing_users = c.fetchall()
            for user in existing_users:
                friend_code = generate_friend_code()
                try:
                    c.execute('UPDATE users SET friend_code = ? WHERE id = ?', (friend_code, user[0]))
                except sqlite3.IntegrityError:
                    # Handle collision by generating a new code
                    while True:
                        friend_code = generate_friend_code()
                        try:
                            c.execute('UPDATE users SET friend_code = ? WHERE id = ?', (friend_code, user[0]))
                            break
                        except sqlite3.IntegrityError:
                            continue
            
            c.execute('DELETE FROM schema_version')
            c.execute('INSERT INTO schema_version (version) VALUES (3)')
            conn.commit()

        if version < 4:
            # Migration 4 - add car_photos table for gallery feature
            migrations = [
                '''CREATE TABLE IF NOT EXISTS car_photos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    car_id INTEGER NOT NULL,
                    image_path TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (car_id) REFERENCES cars (id) ON DELETE CASCADE
                )''',
            ]
            for sql in migrations:
                try:
                    c.execute(sql)
                except sqlite3.OperationalError:
                    pass  # Table already exists
            c.execute('DELETE FROM schema_version')
            c.execute('INSERT INTO schema_version (version) VALUES (4)')
            conn.commit()

init_db()
migrate_db()

# Login logic
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['username']
        password = request.form['password']
        
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        conn.close()
        
        if user is None:
            return jsonify({'success': False, 'error': 'Invalid username or password'})
            
        if not check_password_hash(user['password_hash'], password):
            return jsonify({'success': False, 'error': 'Invalid username or password'})        
            
        session.clear()
        session['user_id'] = user['id']
        session['email'] = user['email']
        session['first_name'] = user['first_name']
        
        next_page = request.args.get('next')
        if not next_page or url_parse(next_page).netloc != '':
            next_page = url_for('home')
            
        return jsonify({'success': True, 'redirect': next_page})
        
    return redirect(url_for('landing'))

@app.route('/api/register', methods=['POST'])
def api_register():
    email = request.form.get('email', '').strip()
    password = request.form.get('password', '')
    confirm_password = request.form.get('confirm_password', '')
    first_name = request.form.get('first_name', '').strip()
    
    if not email or not password or not first_name:
        return jsonify({'success': False, 'error': 'Please fill in all required fields'})
    
    if '@' not in email or '.' not in email:
        return jsonify({'success': False, 'error': 'Please enter a valid email address'})
    
    if password != confirm_password:
        return jsonify({'success': False, 'error': 'Passwords do not match'})
    
    if len(password) < 8:
        return jsonify({'success': False, 'error': 'Password must be at least 8 characters long'})
    
    if not any(c.isupper() for c in password):
        return jsonify({'success': False, 'error': 'Password must contain at least one uppercase letter'})
    
    if not any(c.islower() for c in password):
        return jsonify({'success': False, 'error': 'Password must contain at least one lowercase letter'})
    
    if not any(c.isdigit() for c in password):
        return jsonify({'success': False, 'error': 'Password must contain at least one number'})
    
    special_chars = "!@#$%^&*()_+-=[]{}|;:,.<>?"
    if not any(c in special_chars for c in password):
        return jsonify({'success': False, 'error': 'Password must contain at least one special character'})
    
    conn = get_db_connection()
    
    existing_user = conn.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()
    if existing_user:
        conn.close()
        return jsonify({'success': False, 'error': 'An account with this email already exists'})
    
    print(f"Attempting to insert: first_name={first_name}, last_name={request.form.get('last_name', '').strip()}, email={email}")
    try:
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        salt = secrets.token_hex(16)
        friend_code = generate_friend_code()
        
        # Ensure friend code is unique
        while conn.execute('SELECT id FROM users WHERE friend_code = ?', (friend_code,)).fetchone():
            friend_code = generate_friend_code()
        
        conn.execute('INSERT INTO users (first_name, last_name, email, username, password_hash, salt, friend_code) VALUES (?, ?, ?, ?, ?, ?, ?)', 
            (first_name, request.form.get('last_name', '').strip(), email, email, hashed_password, salt, friend_code))
        conn.commit()
        
        new_user = conn.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()
        user_id = new_user['id']
        
        session['user_id'] = user_id
        session['email'] = email
        session['first_name'] = first_name
        
        conn.close()
        return jsonify({'success': True, 'redirect': url_for('home')})
        
    except sqlite3.Error as e:
        conn.rollback()
        conn.close()
        print(f"Database error: {e}")
        return jsonify({'success': False, 'error': f'Database error: {str(e)}'})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('landing'))

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

@app.route("/")
def home():
    if 'user_id' not in session:
        return redirect(url_for('landing'))
    
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    
    # Get all cars (both active and past) for the carousel and stats
    cars_list = conn.execute(
        'SELECT * FROM cars WHERE user_id = ? ORDER BY status DESC, make, model',
        (session['user_id'],)
    ).fetchall()
    
    conn.close()
    return render_template("index.html", cars=cars_list)

@app.route('/adv_garage')
@login_required
def adv_garage():
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    
    active_cars = conn.execute('''
        SELECT * FROM cars 
        WHERE user_id = ? AND status = 'active'
        ORDER BY vehicle_type, make, model, year DESC
    ''', (session['user_id'],)).fetchall()
    
    past_cars = conn.execute('''
        SELECT * FROM cars 
        WHERE user_id = ? AND status = 'past'
        ORDER BY vehicle_type, make, model, year DESC
    ''', (session['user_id'],)).fetchall()
    
    maintenance_data = conn.execute('''
        SELECT c.id, c.make, c.model, c.year, mr.date, mr.service_type, mr.cost, mr.description, mr.shop_name
        FROM cars c
        LEFT JOIN maintenance_records mr ON c.id = mr.car_id
        WHERE c.user_id = ?
        ORDER BY c.make, c.model, mr.date DESC
    ''', (session['user_id'],)).fetchall()
    
    parts_data = conn.execute('''
        SELECT c.id, c.make, c.model, c.year, ap.part_name, ap.brand, ap.cost, ap.install_date, ap.notes
        FROM cars c
        LEFT JOIN aftermarket_parts ap ON c.id = ap.car_id
        WHERE c.user_id = ?
        ORDER BY c.make, c.model, ap.install_date DESC
    ''', (session['user_id'],)).fetchall()
    
    total_maintenance_cost = sum(m['cost'] or 0 for m in maintenance_data)
    total_parts_cost = sum(p['cost'] or 0 for p in parts_data)
    total_cost = total_maintenance_cost + total_parts_cost
    
    maintenance_count = len([m for m in maintenance_data if m['service_type']])
    parts_count = len([p for p in parts_data if p['part_name']])
    
    cars_with_data = {}
    for car in active_cars + past_cars:
        car_id = str(car['id'])
        car_maintenance = [dict(m) for m in maintenance_data if str(m['id']) == car_id]
        car_parts = [dict(p) for p in parts_data if str(p['id']) == car_id]
        maintenance_cost = sum(m['cost'] or 0 for m in car_maintenance)
        parts_cost = sum(p['cost'] or 0 for p in car_parts)
        car_total_cost = maintenance_cost + parts_cost
        cars_with_data[car_id] = {
            'car': dict(car),
            'maintenance': car_maintenance,
            'parts': car_parts,
            'maintenance_cost': maintenance_cost,
            'parts_cost': parts_cost,
            'total_cost': car_total_cost
        }
    
    def group_by_vehicle_type(cars_list):
        grouped = {}
        for car in cars_list:
            vehicle_type = car['vehicle_type'] or 'Other'
            if vehicle_type not in grouped:
                grouped[vehicle_type] = []
            grouped[vehicle_type].append(car)
        return grouped
    
    active_cars_by_type = group_by_vehicle_type(active_cars)
    past_cars_by_type = group_by_vehicle_type(past_cars)
    
    vehicle_type_stats = {}
    for vehicle_type in set(active_cars_by_type.keys()) | set(past_cars_by_type.keys()):
        active_count = len(active_cars_by_type.get(vehicle_type, []))
        past_count = len(past_cars_by_type.get(vehicle_type, []))
        active_cost = sum(cars_with_data[str(car['id'])]['total_cost'] for car in active_cars_by_type.get(vehicle_type, []))
        past_cost = sum(cars_with_data[str(car['id'])]['total_cost'] for car in past_cars_by_type.get(vehicle_type, []))
        vehicle_type_stats[vehicle_type] = {
            'active_count': active_count,
            'past_count': past_count,
            'total_count': active_count + past_count,
            'active_cost': active_cost,
            'past_cost': past_cost,
            'total_cost': active_cost + past_cost
        }
    
    conn.close()
    
    return render_template('adv_garage.html', 
        active_cars=active_cars,
        past_cars=past_cars,
        active_cars_by_type=active_cars_by_type,
        past_cars_by_type=past_cars_by_type,
        vehicle_type_stats=vehicle_type_stats,
        maintenance_data=maintenance_data,
        parts_data=parts_data,
        cars_with_data=cars_with_data,
        total_maintenance_cost=total_maintenance_cost,
        total_parts_cost=total_parts_cost,
        total_cost=total_cost,
        maintenance_count=maintenance_count,
        parts_count=parts_count)

@app.route('/landing')
def landing():
    return render_template('landing.html')

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    conn = get_db_connection()
    
    if request.method == 'POST':
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        email = request.form.get('email', '').strip()
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        if not all([first_name, last_name]):
            flash('First and last name are required', 'error')
            return redirect(url_for('profile'))
        
        user = conn.execute("SELECT * FROM users WHERE id = ?", (session['user_id'],)).fetchone()
        
        if user is None:
            conn.close()
            abort(404)
        
        if new_password:
            if not current_password:
                flash('Current password is required to change password', 'error')
                return redirect(url_for('profile'))
            
            if new_password != confirm_password:
                flash('New passwords do not match', 'error')
                return redirect(url_for('profile'))
            
            if not check_password_hash(user['password_hash'], current_password):
                flash('Current password is incorrect', 'error')
                return redirect(url_for('profile'))
            
            new_hashed_password = generate_password_hash(new_password, method='pbkdf2:sha256')
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hashed_password, session['user_id']))
        
        try:
            conn.execute(
                "UPDATE users SET first_name = ?, last_name = ?, email = ? WHERE id = ?",
                (first_name, last_name, email, session['user_id'])
            )
            conn.commit()
            session['first_name'] = first_name
            flash('Profile updated successfully!', 'success')
        except sqlite3.IntegrityError:
            flash('Email already exists', 'error')
        finally:
            conn.close()
        
        return redirect(url_for('profile'))
    
    user = conn.execute("SELECT * FROM users WHERE id = ?", (session['user_id'],)).fetchone()
    conn.close()
    
    if user is None:
        abort(404)
    
    return render_template('profile.html', user=user)

@app.route("/manage_cars")
@login_required
def manage_cars():
    """Comprehensive car management page with privacy controls"""
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    
    # Get all user's cars with privacy settings
    cars = conn.execute('''
        SELECT id, make, model, year, vehicle_type, image_path, miles, hours, vin, 
               status, reason, purchase_date, purchase_mileage, purchase_hours,
               is_public_to_friends, public_vin, public_miles, public_purchase_info
        FROM cars 
        WHERE user_id = ?
        ORDER BY year DESC, make, model
    ''', (session['user_id'],)).fetchall()
    
    conn.close()
    return render_template('manage_cars.html', cars=cars)

@app.route("/cars")
@login_required
def cars():
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    
    active_cars = conn.execute(
        'SELECT * FROM cars WHERE user_id = ? AND status = "active" ORDER BY vehicle_type, make, model',
        (session['user_id'],)
    ).fetchall()
    
    past_cars = conn.execute(
        'SELECT * FROM cars WHERE user_id = ? AND status = "past" ORDER BY vehicle_type, make, model',
        (session['user_id'],)
    ).fetchall()
    
    def group_cars_by_type(cars):
        grouped = {}
        for car in cars:
            vehicle_type = car['vehicle_type'] or 'Other'
            if vehicle_type not in grouped:
                grouped[vehicle_type] = []
            grouped[vehicle_type].append(car)
        return grouped
    
    active_cars_grouped = group_cars_by_type(active_cars)
    past_cars_grouped = group_cars_by_type(past_cars)
    
    conn.close()
    return render_template("cars.html", 
        active_cars=active_cars,
        past_cars=past_cars,
        active_cars_grouped=active_cars_grouped, 
        past_cars_grouped=past_cars_grouped)

# Add a new car
@app.route("/add_car", methods=["GET", "POST"])
@login_required
def add_car():
    if request.method == "POST":
        vehicle_type = request.form.get('vehicle_type', 'Car')
        make = request.form.get('make', '').strip()
        model = request.form.get('model', '').strip()
        year = request.form.get('year')
        purchase_date = request.form.get('purchase_date')
        sell_date = request.form.get('sell_date')
        hours = request.form.get('hours')
        miles = request.form.get('miles')
        vin = request.form.get('vin', '').strip()
        purchase_mileage = request.form.get('purchase_mileage')
        purchase_hours = request.form.get('purchase_hours')

        # Basic validation (applies to all vehicle types)
        if not all([make, model, year]):
            flash('Please fill in all required fields', 'error')
            return redirect(url_for('add_car'))

        try:
            year = int(year)
        except ValueError:
            flash('Please enter a valid year', 'error')
            return redirect(url_for('add_car'))

        if vehicle_type == 'Boat':
            if hours:
                try:
                    hours = float(hours)
                except ValueError:
                    flash('Please enter a valid number for current hours', 'error')
                    return redirect(url_for('add_car'))
            else:
                hours = None

            if purchase_hours:
                try:
                    purchase_hours = float(purchase_hours)
                except ValueError:
                    flash('Please enter a valid number for purchase hours', 'error')
                    return redirect(url_for('add_car'))
            else:
                purchase_hours = None

            miles = None
            purchase_mileage = None

        else:
            if purchase_mileage:
                try:
                    purchase_mileage = float(purchase_mileage)
                except ValueError:
                    flash('Please enter a valid number for purchase mileage', 'error')
                    return redirect(url_for('add_car'))
            else:
                purchase_mileage = None

            if miles:
                try:
                    miles = float(miles)
                except ValueError:
                    flash('Please enter a valid number for current miles', 'error')
                    return redirect(url_for('add_car'))
            else:
                miles = None

            hours = None
            purchase_hours = None

        # Handle file upload
        image_path = None
        if 'image' in request.files:
            file = request.files['image']
            if file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filename = f"{int(time.time())}_{filename}"
                user_folder = get_user_upload_folder(session['user_id'])
                file_path = os.path.join(user_folder, filename)
                
                # Compress image if it's an image file (not PDF)
                if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                    compressed_data = compress_image(file.stream)
                    with open(file_path, 'wb') as f:
                        f.write(compressed_data)
                else:
                    # Save PDF as-is
                    file.save(file_path)
                
                image_path = filename
            elif file.filename != '':
                flash('Invalid file type. Please upload an image file (PNG, JPG, JPEG, GIF, WEBP, PDF)', 'error')
                return redirect(url_for('add_car'))

        # Save to database
        conn = get_db_connection()
        try:
            conn.execute(
                "INSERT INTO cars (user_id, vehicle_type, make, model, year, purchase_date, sell_date, image_path, hours, miles, vin, purchase_mileage, purchase_hours) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (session['user_id'], vehicle_type, make, model, year, purchase_date, sell_date, image_path, hours, miles, vin, purchase_mileage, purchase_hours)
            )
            conn.commit()
            flash('Car added successfully!', 'success')
            return redirect(url_for('cars'))
        except sqlite3.Error as e:
            conn.rollback()
            flash('An error occurred while saving the car. Please try again.', 'error')
            return redirect(url_for('add_car'))
        finally:
            conn.close()

    # GET request - render the form
    return render_template("add_car.html")

@app.route("/car/<int:car_id>")
@login_required
def car_detail(car_id):
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    
    car = conn.execute('SELECT * FROM cars WHERE id = ? AND user_id = ?', (car_id, session['user_id'])).fetchone()
    
    if car is None:
        conn.close()
        abort(404)
    
    maintenance = conn.execute('SELECT * FROM maintenance_records WHERE car_id = ? ORDER BY date DESC', (car_id,)).fetchall()
    parts = conn.execute('SELECT * FROM aftermarket_parts WHERE car_id = ? ORDER BY install_date DESC', (car_id,)).fetchall()
    scheduled = conn.execute('SELECT * FROM scheduled_maintenance WHERE car_id = ? ORDER BY due_date ASC', (car_id,)).fetchall()
    photos = conn.execute('SELECT * FROM car_photos WHERE car_id = ? ORDER BY created_at ASC', (car_id,)).fetchall()
    
    conn.close()
    return render_template("car_detail.html", car=car, maintenance=maintenance, parts=parts, scheduled=scheduled, photos=photos)

@app.route("/car/<int:car_id>/edit", methods=["GET", "POST"])
@login_required
def edit_car(car_id):
    conn = get_db_connection()
    
    if request.method == "POST":
        vehicle_type = request.form.get('vehicle_type', 'Car')
        make = request.form.get('make', '').strip()
        model = request.form.get('model', '').strip()
        year = request.form.get('year')
        purchase_date = request.form.get('purchase_date')
        sell_date = request.form.get('sell_date')
        hours = request.form.get('hours')
        miles = request.form.get('miles')
        vin = request.form.get('vin', '').strip()
        purchase_mileage = request.form.get('purchase_mileage')
        
        if vehicle_type == 'Boat':
            if hours:
                try:
                    hours = float(hours)
                except ValueError:
                    flash('Please enter a valid number for hours', 'error')
                    return redirect(url_for('edit_car', car_id=car_id))
            else:
                hours = None
            miles = None
        else:
            if purchase_mileage:
                try:
                    purchase_mileage = float(purchase_mileage)
                except ValueError:
                    flash('Please enter a valid number for purchase mileage', 'error')
                    return redirect(url_for('edit_car', car_id=car_id))
            else:
                purchase_mileage = None
            
            if miles:
                try:
                    miles = float(miles)
                except ValueError:
                    flash('Please enter a valid number for current miles', 'error')
                    return redirect(url_for('edit_car', car_id=car_id))
            else:
                miles = None
            hours = None
        
        if not all([make, model, year]):
            flash('Please fill in all required fields', 'error')
            return redirect(url_for('edit_car', car_id=car_id))
            
        try:
            year = int(year)
        except ValueError:
            flash('Please enter a valid year', 'error')
            return redirect(url_for('edit_car', car_id=car_id))
        
        car = conn.execute("SELECT * FROM cars WHERE id = ? AND user_id = ?", (car_id, session['user_id'])).fetchone()
        
        if car is None:
            conn.close()
            abort(404)
        
        image_path = car['image_path']
        # Handle image upload
        if 'image' in request.files and request.files['image'].filename != '':
            file = request.files['image']
            if file.filename != '':
                if allowed_file(file.filename):
                    # Use existing filename if available, otherwise create new one
                    if car['image_path']:
                        filename = car['image_path']
                        # Remove old file to ensure clean overwrite
                        try:
                            old_folder = get_user_upload_folder(session['user_id'])
                            os.remove(os.path.join(old_folder, filename))
                        except OSError:
                            pass
                    else:
                        filename = secure_filename(file.filename)
                        filename = f"{int(time.time())}_{filename}"
                    
                    user_folder = get_user_upload_folder(session['user_id'])
                    file_path = os.path.join(user_folder, filename)
                    
                    # Compress image if it's an image file (not PDF)
                    if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                        compressed_data = compress_image(file.stream)
                        with open(file_path, 'wb') as f:
                            f.write(compressed_data)
                    else:
                        # Save PDF as-is
                        file.save(file_path)
                    
                    image_path = filename
                else:
                    flash('Invalid file type. Please upload an image file (PNG, JPG, JPEG, GIF, WEBP, PDF)', 'error')
                    return redirect(url_for('edit_car', car_id=car_id))
        
        try:
            conn.execute(
                "UPDATE cars SET vehicle_type = ?, make = ?, model = ?, year = ?, purchase_date = ?, sell_date = ?, image_path = ?, hours = ?, miles = ?, vin = ?, purchase_mileage = ? WHERE id = ? AND user_id = ?",
                (vehicle_type, make, model, year, purchase_date, sell_date, image_path, hours, miles, vin, purchase_mileage, car_id, session['user_id'])
            )
            conn.commit()
            flash('Car updated successfully!', 'success')
            return redirect(url_for('car_detail', car_id=car_id))
        except sqlite3.Error as e:
            conn.rollback()
            flash('An error occurred while updating the car. Please try again.', 'error')
            return redirect(url_for('edit_car', car_id=car_id))
        finally:
            conn.close()
    
    conn.close()
    return redirect(url_for('car_detail', car_id=car_id))

@app.route("/car/<int:car_id>/quick_edit", methods=["POST"])
@login_required
def quick_edit_car(car_id):
    conn = get_db_connection()
    
    try:
        vin = request.form.get('vin', '').strip()
        miles = float(request.form.get('miles', 0)) if request.form.get('miles') else None
        hours = float(request.form.get('hours', 0)) if request.form.get('hours') else None
        
        # Validate input
        if miles is not None and miles < 0:
            flash('Miles cannot be negative', 'error')
            return redirect(url_for('cars'))
        if hours is not None and hours < 0:
            flash('Hours cannot be negative', 'error')
            return redirect(url_for('cars'))
        
        # Update the car with the new values
        update_fields = []
        update_params = []
        
        if vin:
            update_fields.append("vin = ?")
            update_params.append(vin)
        
        if miles is not None:
            update_fields.append("miles = ?")
            update_params.append(miles)
        
        if hours is not None:
            update_fields.append("hours = ?")
            update_params.append(hours)
        
        if update_fields:
            update_query = f"UPDATE cars SET {', '.join(update_fields)} WHERE id = ? AND user_id = ?"
            update_params.extend([car_id, session['user_id']])
            
            conn.execute(update_query, update_params)
            conn.commit()
            flash('Vehicle updated successfully!', 'success')
        else:
            flash('No changes to update', 'info')
            
    except sqlite3.Error as e:
        conn.rollback()
        flash(f'Database error: {str(e)}', 'error')
    except Exception as e:
        conn.rollback()
        flash(f'Error updating vehicle: {str(e)}', 'error')
    finally:
        conn.close()
    
    return redirect(url_for('cars'))

@app.route("/car/<int:car_id>/add_maintenance", methods=["POST"])
def add_maintenance(car_id):
    date = request.form["date"]
    mileage = request.form.get("mileage") or None
    service_type = request.form["service_type"]
    description = request.form.get("description") or None
    cost = request.form.get("cost") or None
    shop_name = request.form.get("shop_name") or None
    
    receipt_image = None
    if 'receipt_image' in request.files:
        file = request.files['receipt_image']
        if file.filename != '' and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filename = f"{int(time.time())}_{filename}"
            user_folder = get_user_upload_folder(session['user_id'])
            file_path = os.path.join(user_folder, filename)
            
            # Compress image if it's an image file (not PDF)
            if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                compressed_data = compress_image(file.stream)
                with open(file_path, 'wb') as f:
                    f.write(compressed_data)
            else:
                # Save PDF as-is
                file.save(file_path)
            
            receipt_image = filename
    
    with sqlite3.connect(DATABASE) as conn:
        c = conn.cursor()
        c.execute("""INSERT INTO maintenance_records 
                    (car_id, date, mileage, service_type, description, cost, shop_name, receipt_image) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (car_id, date, mileage, service_type, description, cost, shop_name, receipt_image))
        conn.commit()
    return redirect(url_for("car_detail", car_id=car_id))

@app.route("/car/<int:car_id>/edit_maintenance/<int:record_id>", methods=["POST"])
def edit_maintenance(car_id, record_id):
    date = request.form.get("date")
    mileage_val = request.form.get("mileage")
    mileage = int(mileage_val) if mileage_val and mileage_val.strip() else None
    service_type = request.form.get("service_type")
    description = request.form.get("description") or None
    cost_val = request.form.get("cost")
    cost = float(cost_val) if cost_val and cost_val.strip() else None
    shop_name = request.form.get("shop_name") or None
    
    receipt_image = None
    if 'receipt_image' in request.files:
        file = request.files['receipt_image']
        if file.filename != '' and allowed_file(file.filename):
            with sqlite3.connect(DATABASE) as conn:
                c = conn.cursor()
                current = c.execute("SELECT receipt_image FROM maintenance_records WHERE id = ? AND car_id = ?", 
                                   (record_id, car_id)).fetchone()
                
                # Use existing filename if available, otherwise create new one
                if current and current[0]:
                    filename = current[0]
                    # Remove old file to ensure clean overwrite
                    try:
                        old_folder = get_user_upload_folder(session['user_id'])
                        os.remove(os.path.join(old_folder, filename))
                    except OSError:
                        pass
                else:
                    filename = secure_filename(file.filename)
                    filename = f"{int(time.time())}_{filename}"
                
                user_folder = get_user_upload_folder(session['user_id'])
                file_path = os.path.join(user_folder, filename)
                
                # Compress image if it's an image file (not PDF)
                if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                    compressed_data = compress_image(file.stream)
                    with open(file_path, 'wb') as f:
                        f.write(compressed_data)
                else:
                    # Save PDF as-is
                    file.save(file_path)
                
                receipt_image = filename
    
    with sqlite3.connect(DATABASE) as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM maintenance_records WHERE id = ? AND car_id = ?", (record_id, car_id))
        current = c.fetchone()
        if not current:
            return redirect(url_for("car_detail", car_id=car_id))
            
        update_data = {
            'date': date if date is not None else current[1],
            'mileage': mileage if mileage is not None else current[2],
            'service_type': service_type if service_type is not None else current[3],
            'description': description if description is not None else current[4],
            'cost': cost if cost is not None else current[5],
            'shop_name': shop_name if shop_name is not None else current[6],
            'receipt_image': receipt_image if receipt_image is not None else current[7]
        }
        
        c.execute("""UPDATE maintenance_records 
                    SET date = ?, mileage = ?, service_type = ?, 
                        description = ?, cost = ?, shop_name = ?, receipt_image = ?
                    WHERE id = ? AND car_id = ?""",
                (update_data['date'], update_data['mileage'], update_data['service_type'],
                update_data['description'], update_data['cost'], update_data['shop_name'],
                update_data['receipt_image'], record_id, car_id))
        conn.commit()
    return redirect(url_for("car_detail", car_id=car_id))

@app.route("/car/<int:car_id>/delete_maintenance/<int:record_id>")
def delete_maintenance(car_id, record_id):
    with sqlite3.connect(DATABASE) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM maintenance_records WHERE id = ? AND car_id = ?", (record_id, car_id))
        conn.commit()
    return redirect(url_for("car_detail", car_id=car_id))

@app.route("/car/<int:car_id>/add_part", methods=["POST"])
def add_part(car_id):
    part_name = request.form["part_name"]
    brand = request.form.get("brand") or None
    install_date = request.form.get("install_date") or None
    cost = request.form.get("cost") or None
    notes = request.form.get("notes") or None
    
    receipt_image = None
    if 'receipt_image' in request.files:
        file = request.files['receipt_image']
        if file.filename != '' and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filename = f"{int(time.time())}_{filename}"
            user_folder = get_user_upload_folder(session['user_id'])
            file_path = os.path.join(user_folder, filename)
            
            # Compress image if it's an image file (not PDF)
            if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                compressed_data = compress_image(file.stream)
                with open(file_path, 'wb') as f:
                    f.write(compressed_data)
            else:
                # Save PDF as-is
                file.save(file_path)
            
            receipt_image = filename
    
    with sqlite3.connect(DATABASE) as conn:
        c = conn.cursor()
        c.execute("""INSERT INTO aftermarket_parts 
                    (car_id, part_name, brand, install_date, cost, notes, receipt_image) 
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (car_id, part_name, brand, install_date, cost, notes, receipt_image))
        conn.commit()
    return redirect(url_for("car_detail", car_id=car_id))

@app.route("/car/<int:car_id>/edit_part/<int:part_id>", methods=["POST"])
def edit_part(car_id, part_id):
    part_name = request.form["part_name"]
    brand = request.form.get("brand") or None
    install_date = request.form.get("install_date") or None
    cost = request.form.get("cost") or None
    notes = request.form.get("notes") or None
    
    # Handle receipt image upload
    receipt_image = None
    if 'receipt_image' in request.files:
        file = request.files['receipt_image']
        if file.filename != '' and allowed_file(file.filename):
            with sqlite3.connect(DATABASE) as conn:
                c = conn.cursor()
                current_part = c.execute("SELECT receipt_image FROM aftermarket_parts WHERE id = ? AND car_id = ?", 
                    (part_id, car_id)).fetchone()
                
                # Use existing filename if available, otherwise create new one
                if current_part and current_part[0]:
                    filename = current_part[0]
                    # Remove old file to ensure clean overwrite
                    try:
                        old_folder = get_user_upload_folder(session['user_id'])
                        os.remove(os.path.join(old_folder, filename))
                    except OSError:
                        pass
                else:
                    filename = secure_filename(file.filename)
                    filename = f"{int(time.time())}_{filename}"
                
                user_folder = get_user_upload_folder(session['user_id'])
                file_path = os.path.join(user_folder, filename)
                
                # Compress image if it's an image file (not PDF)
                if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                    compressed_data = compress_image(file.stream)
                    with open(file_path, 'wb') as f:
                        f.write(compressed_data)
                else:
                    # Save PDF as-is
                    file.save(file_path)
                
                receipt_image = filename
    
    with sqlite3.connect(DATABASE) as conn:
        c = conn.cursor()
        
        # Get current receipt image if no new one is uploaded
        if not receipt_image:
            current_receipt = c.execute("SELECT receipt_image FROM aftermarket_parts WHERE id = ? AND car_id = ?", 
                                      (part_id, car_id)).fetchone()
            receipt_image = current_receipt[0] if current_receipt and current_receipt[0] else None
        
        c.execute("""UPDATE aftermarket_parts 
                    SET part_name = ?, brand = ?, install_date = ?, cost = ?, notes = ?, receipt_image = ?
                    WHERE id = ? AND car_id = ?""",
                (part_name, brand, install_date, cost, notes, receipt_image, part_id, car_id))
        conn.commit()
    return redirect(url_for("car_detail", car_id=car_id))

@app.route("/car/<int:car_id>/delete_part/<int:part_id>")
def delete_part(car_id, part_id):
    with sqlite3.connect(DATABASE) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM aftermarket_parts WHERE id = ? AND car_id = ?", (part_id, car_id))
        conn.commit()
    return redirect(url_for("car_detail", car_id=car_id))

@app.route("/car/<int:car_id>/add_scheduled", methods=["POST"])
def add_scheduled(car_id):
    service_type = request.form["service_type"]
    due_date = request.form.get("due_date") or None
    due_mileage = request.form.get("due_mileage") or None
    reminder_enabled = 1 if request.form.get("reminder_enabled") else 0
    notes = request.form.get("notes") or None
    
    with sqlite3.connect(DATABASE) as conn:
        c = conn.cursor()
        c.execute("""INSERT INTO scheduled_maintenance 
                    (car_id, service_type, due_date, due_mileage, reminder_enabled, notes) 
                    VALUES (?, ?, ?, ?, ?, ?)""",
                (car_id, service_type, due_date, due_mileage, reminder_enabled, notes))
        conn.commit()
    return redirect(url_for("car_detail", car_id=car_id))

@app.route("/car/<int:car_id>/complete_scheduled/<int:scheduled_id>")
def complete_scheduled(car_id, scheduled_id):
    with sqlite3.connect(DATABASE) as conn:
        c = conn.cursor()
        c.execute("UPDATE scheduled_maintenance SET completed = 1 WHERE id = ? AND car_id = ?", 
                (scheduled_id, car_id))
        conn.commit()
    return redirect(url_for("car_detail", car_id=car_id))

@app.route("/car/<int:car_id>/edit_scheduled/<int:scheduled_id>", methods=["POST"])
def edit_scheduled(car_id, scheduled_id):
    service_type = request.form["service_type"]
    due_date = request.form.get("due_date") or None
    due_mileage = request.form.get("due_mileage") or None
    reminder_enabled = 1 if request.form.get("reminder_enabled") else 0
    notes = request.form.get("notes") or None
    
    with sqlite3.connect(DATABASE) as conn:
        c = conn.cursor()
        c.execute("""UPDATE scheduled_maintenance 
                SET service_type = ?, due_date = ?, due_mileage = ?, reminder_enabled = ?, notes = ?
                WHERE id = ? AND car_id = ?""",
            (service_type, due_date, due_mileage, reminder_enabled, notes, scheduled_id, car_id))
        conn.commit()
    return redirect(url_for("car_detail", car_id=car_id))

@app.route("/car/<int:car_id>/delete_scheduled/<int:scheduled_id>")
def delete_scheduled(car_id, scheduled_id):
    with sqlite3.connect(DATABASE) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM scheduled_maintenance WHERE id = ? AND car_id = ?", (scheduled_id, car_id))
        conn.commit()
    return redirect(url_for("car_detail", car_id=car_id))

@app.route('/car/<int:car_id>/update_status', methods=['POST'])
@login_required
def update_car_status(car_id):
    reason = request.form.get('reason', '')
    custom_reason = request.form.get('custom_reason', '')
    sold_mileage = request.form.get('sold_mileage')
    
    # Use custom reason if "Other" was selected
    if reason == 'Other' and custom_reason:
        final_reason = custom_reason
    else:
        final_reason = reason
    
    if sold_mileage:
        try:
            sold_mileage = float(sold_mileage)
        except ValueError:
            flash('Please enter a valid number for sold mileage', 'error')
            return redirect(url_for('car_detail', car_id=car_id))
    else:
        sold_mileage = None
    
    conn = get_db_connection()
    conn.execute(
        'UPDATE cars SET status = ?, reason = ?, sold_mileage = ? WHERE id = ? AND user_id = ?',
        ('past', final_reason, sold_mileage, car_id, session['user_id'])
    )
    conn.commit()
    conn.close()
    flash('Car moved to Past Vehicles', 'success')
    return redirect(url_for('cars'))

@app.route('/car/<int:car_id>/restore', methods=['POST'])
@login_required
def restore_car(car_id):
    conn = get_db_connection()
    conn.execute(
        'UPDATE cars SET status = ?, reason = ? WHERE id = ? AND user_id = ?',
        ('active', None, car_id, session['user_id'])
    )
    conn.commit()
    conn.close()
    flash('Car restored to your garage!', 'success')
    return redirect(url_for('cars'))

@app.route("/car/<int:car_id>/delete", methods=["POST"])
@login_required
def delete_car(car_id):
    conn = get_db_connection()
    
    car = conn.execute('SELECT * FROM cars WHERE id = ? AND user_id = ?', (car_id, session['user_id'])).fetchone()
    
    if not car:
        conn.close()
        flash('Vehicle not found', 'error')
        return redirect(url_for('cars'))
    
    conn.execute('DELETE FROM cars WHERE id = ?', (car_id,))
    conn.commit()
    conn.close()
    
    flash(f'{car["year"]} {car["make"]} {car["model"]} has been deleted', 'success')
    return redirect(url_for('cars'))

@app.route('/update_car_privacy/<int:car_id>', methods=['POST'])
@login_required
def update_car_privacy(car_id):
    """Update privacy settings for a specific car field"""
    conn = get_db_connection()
    
    # Verify car ownership
    car = conn.execute('SELECT user_id FROM cars WHERE id = ?', (car_id,)).fetchone()
    if not car or car['user_id'] != session['user_id']:
        conn.close()
        return jsonify({'success': False, 'error': 'Unauthorized'})
    
    try:
        data = request.get_json()
        field = data.get('field')
        value = data.get('value')
        
        # Validate field
        valid_fields = ['public_to_friends', 'public_vin', 'public_miles', 'public_purchase_info']
        if field not in valid_fields:
            conn.close()
            return jsonify({'success': False, 'error': 'Invalid field'})
        
        # Update the specific field
        if field == 'public_to_friends':
            conn.execute('UPDATE cars SET is_public_to_friends = ? WHERE id = ?', (value, car_id))
        elif field == 'public_vin':
            conn.execute('UPDATE cars SET public_vin = ? WHERE id = ?', (value, car_id))
        elif field == 'public_miles':
            conn.execute('UPDATE cars SET public_miles = ? WHERE id = ?', (value, car_id))
        elif field == 'public_purchase_info':
            conn.execute('UPDATE cars SET public_purchase_info = ? WHERE id = ?', (value, car_id))
        conn.commit()
        conn.close()
        
        return jsonify({'success': True})
        
    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/uploads/<int:user_id>/<filename>')
def uploaded_file(user_id, filename):
    """Serve files from user-specific folders"""
    user_folder = get_user_upload_folder(user_id)
    return send_from_directory(user_folder, filename)

# Friends feature routes
@app.route('/friends')
@login_required
def friends():
    conn = get_db_connection()
    
    # Get user's friend code
    user = conn.execute('SELECT friend_code FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    
    # Get user's friends
    friends_list = conn.execute('''
        SELECT u.id, u.first_name, u.last_name, u.email, u.friend_code, f.created_at
        FROM users u
        JOIN friendships f ON u.id = f.addressee_id
        WHERE f.requester_id = ?
        ORDER BY u.first_name, u.last_name
    ''', (session['user_id'],)).fetchall()
    
    conn.close()
    return render_template('friends.html', user=user, friends=friends_list)

@app.route('/add_friend', methods=['POST'])
@login_required
def add_friend():
    friend_code = request.form.get('friend_code', '').strip().upper()
    
    if not friend_code:
        flash('Please enter a friend code', 'error')
        return redirect(url_for('friends'))
    
    if not friend_code.startswith('GRG-') or len(friend_code) != 10:
        flash('Invalid friend code format', 'error')
        return redirect(url_for('friends'))
    
    conn = get_db_connection()
    
    # Find the user with this friend code
    friend_user = conn.execute('SELECT id, first_name, last_name FROM users WHERE friend_code = ?', (friend_code,)).fetchone()
    
    if not friend_user:
        conn.close()
        flash('Friend code not found', 'error')
        return redirect(url_for('friends'))
    
    if friend_user['id'] == session['user_id']:
        conn.close()
        flash('You cannot add yourself as a friend', 'error')
        return redirect(url_for('friends'))
    
    # Check if already friends
    existing_friendship = conn.execute('''
        SELECT id FROM friendships 
        WHERE requester_id = ? AND addressee_id = ?
    ''', (session['user_id'], friend_user['id'])).fetchone()
    
    if existing_friendship:
        conn.close()
        flash('You are already friends with this person', 'error')
        return redirect(url_for('friends'))
    
    # Add friendship
    try:
        conn.execute('''
            INSERT INTO friendships (requester_id, addressee_id, status)
            VALUES (?, ?, 'active')
        ''', (session['user_id'], friend_user['id']))
        conn.commit()
        flash(f'You are now friends with {friend_user["first_name"]} {friend_user["last_name"]}!', 'success')
    except sqlite3.Error as e:
        conn.rollback()
        flash('An error occurred while adding friend', 'error')
    finally:
        conn.close()
    
    return redirect(url_for('friends'))

@app.route('/remove_friend/<int:friend_id>', methods=['POST'])
@login_required
def remove_friend(friend_id):
    conn = get_db_connection()
    
    try:
        conn.execute('''
            DELETE FROM friendships 
            WHERE requester_id = ? AND addressee_id = ?
        ''', (session['user_id'], friend_id))
        conn.commit()
        flash('Friend removed successfully', 'success')
    except sqlite3.Error as e:
        conn.rollback()
        flash('An error occurred while removing friend', 'error')
    finally:
        conn.close()
    
    return redirect(url_for('friends'))

@app.route('/friends_garage')
@login_required
def friends_garage():
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    
    # Get friends and their cars (only active shared cars)
    friends_cars = conn.execute('''
        SELECT u.id as user_id, u.first_name, u.last_name, u.friend_code,
               c.id as car_id, c.make, c.model, c.year, c.vehicle_type, c.image_path, c.miles, c.hours, c.status, c.reason,
               c.vin, c.purchase_date, c.purchase_mileage, c.purchase_hours, c.public_vin, c.public_miles, c.public_purchase_info
        FROM users u
        JOIN friendships f ON u.id = f.addressee_id
        LEFT JOIN cars c ON u.id = c.user_id AND c.is_public_to_friends = 1 AND c.status = 'active'
        WHERE f.requester_id = ?
        ORDER BY u.first_name, u.last_name, c.make, c.model
    ''', (session['user_id'],)).fetchall()
    
    # Group cars by friend
    friends_data = {}
    for row in friends_cars:
        user_id = row['user_id']
        if user_id not in friends_data:
            friends_data[user_id] = {
                'user': {
                    'id': row['user_id'],
                    'first_name': row['first_name'],
                    'last_name': row['last_name'],
                    'friend_code': row['friend_code']
                },
                'cars': []
            }
        
        if row['car_id']:  # Only add if car exists
            friends_data[user_id]['cars'].append({
                'id': row['car_id'],
                'make': row['make'],
                'model': row['model'],
                'year': row['year'],
                'vehicle_type': row['vehicle_type'],
                'image_path': row['image_path'],
                'miles': row['miles'],
                'hours': row['hours'],
                'status': row['status'],
                'reason': row['reason'],
                'vin': row['vin'],
                'purchase_date': row['purchase_date'],
                'purchase_mileage': row['purchase_mileage'],
                'purchase_hours': row['purchase_hours'],
                'public_vin': row['public_vin'],
                'public_miles': row['public_miles'],
                'public_purchase_info': row['public_purchase_info']
            })
    
    conn.close()
    return render_template('friends_garage.html', friends_data=friends_data)

@app.route('/friend_garage/<int:friend_id>')
@login_required
def friend_garage(friend_id):
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    
    # Verify friendship
    friendship = conn.execute('''
        SELECT id FROM friendships 
        WHERE requester_id = ? AND addressee_id = ?
    ''', (session['user_id'], friend_id)).fetchone()
    
    if not friendship:
        conn.close()
        abort(403)  # Not friends
    
    # Get friend info and all their public cars
    friend_info = conn.execute('''
        SELECT first_name, last_name, friend_code FROM users WHERE id = ?
    ''', (friend_id,)).fetchone()
    
    cars = conn.execute('''
        SELECT id, make, model, year, vehicle_type, image_path, miles, hours, status, reason,
               purchase_date, purchase_mileage, sell_date, sold_mileage, vin, purchase_hours,
               public_vin, public_miles, public_purchase_info
        FROM cars 
        WHERE user_id = ? AND is_public_to_friends = 1 AND status = 'active'
        ORDER BY year DESC, make, model
    ''', (friend_id,)).fetchall()
    
    conn.close()
    
    if not friend_info:
        abort(404)
    
    return render_template('friend_garage.html', friend=friend_info, cars=cars)

@app.route('/toggle_car_visibility/<int:car_id>', methods=['POST'])
@login_required
def toggle_car_visibility(car_id):
    conn = get_db_connection()
    
    # Verify car belongs to user
    car = conn.execute('SELECT is_public_to_friends FROM cars WHERE id = ? AND user_id = ?', 
                     (car_id, session['user_id'])).fetchone()
    
    if not car:
        conn.close()
        return jsonify({'success': False, 'error': 'Car not found'})
    
    try:
        new_visibility = 1 if car['is_public_to_friends'] == 0 else 0
        conn.execute('UPDATE cars SET is_public_to_friends = ? WHERE id = ?', 
                    (new_visibility, car_id))
        conn.commit()
        return jsonify({'success': True, 'is_public': new_visibility})
    except sqlite3.Error as e:
        conn.rollback()
        return jsonify({'success': False, 'error': 'Database error'})
    finally:
        conn.close()

@app.route('/car/<int:car_id>/upload_photo', methods=['POST'])
@login_required
def upload_car_photo(car_id):
    """Upload a photo to car gallery with compression and override logic"""
    conn = get_db_connection()
    
    # Verify car ownership
    car = conn.execute('SELECT user_id FROM cars WHERE id = ?', (car_id,)).fetchone()
    if not car or car['user_id'] != session['user_id']:
        conn.close()
        return jsonify({'success': False, 'error': 'Unauthorized'})
    
    # Check current photo count
    current_photos = conn.execute('SELECT COUNT(*) as count FROM car_photos WHERE car_id = ?', (car_id,)).fetchone()
    
    if current_photos['count'] >= 10:
        conn.close()
        return jsonify({'success': False, 'error': 'Maximum 10 photos allowed. Please delete a photo first.'})
    
    if 'photo' not in request.files:
        conn.close()
        return jsonify({'success': False, 'error': 'No photo provided'})
    
    file = request.files['photo']
    if file.filename == '':
        conn.close()
        return jsonify({'success': False, 'error': 'No photo selected'})
    
    if not allowed_file(file.filename):
        conn.close()
        return jsonify({'success': False, 'error': 'Invalid file type. Only images allowed.'})
    
    # Check if user wants to override an existing photo
    override_photo_id = request.form.get('override_photo_id')
    
    try:
        filename = secure_filename(file.filename)
        filename = f"gallery_{int(time.time())}_{filename}"
        user_folder = get_user_upload_folder(session['user_id'])
        file_path = os.path.join(user_folder, filename)
        
        # Compress image
        compressed_data = compress_image(file.stream)
        with open(file_path, 'wb') as f:
            f.write(compressed_data)
        
        if override_photo_id:
            # Delete the old photo
            old_photo = conn.execute('SELECT image_path FROM car_photos WHERE id = ? AND car_id = ?', 
                                    (override_photo_id, car_id)).fetchone()
            if old_photo:
                old_file_path = os.path.join(user_folder, old_photo['image_path'])
                if os.path.exists(old_file_path):
                    os.remove(old_file_path)
                conn.execute('DELETE FROM car_photos WHERE id = ?', (override_photo_id,))
        
        # Add new photo
        conn.execute('INSERT INTO car_photos (car_id, image_path) VALUES (?, ?)', (car_id, filename))
        conn.commit()
        
        conn.close()
        return jsonify({'success': True, 'message': 'Photo uploaded successfully'})
        
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'success': False, 'error': f'Error uploading photo: {str(e)}'})

@app.route('/car/<int:car_id>/delete_photo/<int:photo_id>', methods=['POST'])
@login_required
def delete_car_photo(car_id, photo_id):
    """Delete a photo from car gallery"""
    conn = get_db_connection()
    
    # Verify car ownership
    car = conn.execute('SELECT user_id FROM cars WHERE id = ?', (car_id,)).fetchone()
    if not car or car['user_id'] != session['user_id']:
        conn.close()
        return jsonify({'success': False, 'error': 'Unauthorized'})
    
    try:
        photo = conn.execute('SELECT image_path FROM car_photos WHERE id = ? AND car_id = ?', 
                            (photo_id, car_id)).fetchone()
        
        if not photo:
            conn.close()
            return jsonify({'success': False, 'error': 'Photo not found'})
        
        # Delete file from disk
        user_folder = get_user_upload_folder(session['user_id'])
        file_path = os.path.join(user_folder, photo['image_path'])
        if os.path.exists(file_path):
            os.remove(file_path)
        
        # Delete from database
        conn.execute('DELETE FROM car_photos WHERE id = ?', (photo_id,))
        conn.commit()
        
        conn.close()
        return jsonify({'success': True, 'message': 'Photo deleted successfully'})
        
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'success': False, 'error': f'Error deleting photo: {str(e)}'})

@app.route('/privacy-policy')
def privacy_policy():
    """Privacy Policy page"""
    return render_template('privacy_policy.html')

@app.route('/terms-of-service')
def terms_of_service():
    """Terms of Service page"""
    return render_template('terms_of_service.html')

if __name__ == "__main__":
    app.run(debug=True)