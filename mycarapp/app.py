from flask import Flask, render_template, request, redirect, url_for, send_from_directory, flash, session, abort, jsonify
import sqlite3
import os
import time
import hashlib
import secrets
from functools import wraps
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from urllib.parse import urlparse

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
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Create uploads directory if it doesn't exist
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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
        # Create users table
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
        # Add hours column for boats
        try:
            c.execute("ALTER TABLE cars ADD COLUMN hours REAL")
        except sqlite3.OperationalError:
            pass  # Column already exists
        # Add miles column for cars
        try:
            c.execute("ALTER TABLE cars ADD COLUMN miles REAL")
        except sqlite3.OperationalError:
            pass  # Column already exists

init_db()

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
            
        # Verify password
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
    
    # Basic validation
    if not email or not password or not first_name:
        return jsonify({'success': False, 'error': 'Please fill in all required fields'})
    
    # Email validation
    if '@' not in email or '.' not in email:
        return jsonify({'success': False, 'error': 'Please enter a valid email address'})
    
    if password != confirm_password:
        return jsonify({'success': False, 'error': 'Passwords do not match'})
    
    # Password requirements
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
    
    # Check if email already exists
    existing_user = conn.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()
    if existing_user:
        conn.close()
        return jsonify({'success': False, 'error': 'An account with this email already exists'})
    
    # Create new user
    print(f"Attempting to insert: first_name={first_name}, last_name={request.form.get('last_name', '').strip()}, email={email}")
    try:
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        import secrets
        salt = secrets.token_hex(16)  # Generate a random salt
        conn.execute('INSERT INTO users (first_name, last_name, email, username, password_hash, salt) VALUES (?, ?, ?, ?, ?, ?)', 
            (first_name, request.form.get('last_name', '').strip(), email, email, hashed_password, salt))
        conn.commit()
        
        # Get the new user's ID
        new_user = conn.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()
        user_id = new_user['id']
        
        # Auto-login the user
        session['user_id'] = user_id
        session['email'] = email
        session['first_name'] = first_name
        
        conn.close()
        return jsonify({'success': True, 'redirect': url_for('home')})
        
    except sqlite3.Error as e:
        conn.rollback()
        conn.close()
        print(f"Database error: {e}")  # Debug print
        return jsonify({'success': False, 'error': f'Database error: {str(e)}'})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('landing'))

# Login required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

# Home page
@app.route("/")
def home():
    # If user is not logged in, redirect to landing page
    if 'user_id' not in session:
        return redirect(url_for('landing'))
    
    # If user is logged in, show their personalized dashboard
    conn = get_db_connection()
    cars_list = conn.execute("SELECT * FROM cars WHERE user_id = ?", (session['user_id'],)).fetchall()
    conn.close()
    return render_template("index.html", cars=cars_list)

@app.route('/adv_garage')
@login_required
def adv_garage():
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    
    # Get all cars data
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
    
    # Get maintenance data from maintenance_records table
    maintenance_data = conn.execute('''
        SELECT c.id, c.make, c.model, c.year, mr.date, mr.service_type, mr.cost, mr.description, mr.shop_name
        FROM cars c
        LEFT JOIN maintenance_records mr ON c.id = mr.car_id
        WHERE c.user_id = ?
        ORDER BY c.make, c.model, mr.date DESC
    ''', (session['user_id'],)).fetchall()
    
    # Get parts data from aftermarket_parts table
    parts_data = conn.execute('''
        SELECT c.id, c.make, c.model, c.year, ap.part_name, ap.brand, ap.cost, ap.install_date, ap.notes
        FROM cars c
        LEFT JOIN aftermarket_parts ap ON c.id = ap.car_id
        WHERE c.user_id = ?
        ORDER BY c.make, c.model, ap.install_date DESC
    ''', (session['user_id'],)).fetchall()
    
    # Calculate statistics
    total_maintenance_cost = sum(m['cost'] or 0 for m in maintenance_data)
    total_parts_cost = sum(p['cost'] or 0 for p in parts_data)
    total_cost = total_maintenance_cost + total_parts_cost
    
    maintenance_count = len([m for m in maintenance_data if m['service_type']])
    parts_count = len([p for p in parts_data if p['part_name']])
    
    # Group data by car for detailed views
    cars_with_data = {}
    for car in active_cars + past_cars:
        car_id = str(car['id'])  # Convert to string to ensure consistent key type
        
        # Get maintenance and parts for this car
        car_maintenance = [dict(m) for m in maintenance_data if str(m['id']) == car_id]
        car_parts = [dict(p) for p in parts_data if str(p['id']) == car_id]
        
        # Calculate costs
        maintenance_cost = sum(m['cost'] or 0 for m in car_maintenance)
        parts_cost = sum(p['cost'] or 0 for p in car_parts)
        total_cost = maintenance_cost + parts_cost
        
        # Assign to dictionary (safe approach)
        cars_with_data[car_id] = {
            'car': dict(car),
            'maintenance': car_maintenance,
            'parts': car_parts,
            'maintenance_cost': maintenance_cost,
            'parts_cost': parts_cost,
            'total_cost': total_cost
        }
    
    # Group cars by vehicle type
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
    
    # Get vehicle type statistics
    vehicle_type_stats = {}
    for vehicle_type in set(active_cars_by_type.keys()) | set(past_cars_by_type.keys()):
        active_count = len(active_cars_by_type.get(vehicle_type, []))
        past_count = len(past_cars_by_type.get(vehicle_type, []))
        
        # Use string keys consistently
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
        # Get form data
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        email = request.form.get('email', '').strip()
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        # Basic validation
        if not all([first_name, last_name]):
            flash('First and last name are required', 'error')
            return redirect(url_for('profile'))
        
        # Get current user data
        user = conn.execute(
            "SELECT * FROM users WHERE id = ?",
            (session['user_id'],)
        ).fetchone()
        
        if user is None:
            conn.close()
            abort(404)
        
        # Handle password change if provided
        if new_password:
            if not current_password:
                flash('Current password is required to change password', 'error')
                return redirect(url_for('profile'))
            
            if new_password != confirm_password:
                flash('New passwords do not match', 'error')
                return redirect(url_for('profile'))
            
            # Verify current password
            salt = user['salt']
            hashed_current = hashlib.pbkdf2_hmac('sha256', current_password.encode('utf-8'), salt.encode('utf-8'), 100000).hex()
            
            if hashed_current != user['password_hash']:
                flash('Current password is incorrect', 'error')
                return redirect(url_for('profile'))
            
            # Generate new password hash
            new_hashed_password = hashlib.pbkdf2_hmac('sha256', new_password.encode('utf-8'), salt.encode('utf-8'), 100000).hex()
            
            # Update password
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (new_hashed_password, session['user_id'])
            )
        
        # Update profile information
        try:
            conn.execute(
                "UPDATE users SET first_name = ?, last_name = ?, email = ? WHERE id = ?",
                (first_name, last_name, email, session['user_id'])
            )
            conn.commit()
            
            # Update session with new first name
            session['first_name'] = first_name
            
            flash('Profile updated successfully!', 'success')
        except sqlite3.IntegrityError:
            flash('Email already exists', 'error')
        finally:
            conn.close()
        
        return redirect(url_for('profile'))
    
    # GET request - show profile form
    user = conn.execute(
        "SELECT * FROM users WHERE id = ?",
        (session['user_id'],)
    ).fetchone()
    conn.close()
    
    if user is None:
        abort(404)
    
    return render_template('profile.html', user=user)

# List all cars
@app.route("/cars")
@login_required
def cars():
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    
    # Get active cars grouped by vehicle type
    active_cars = conn.execute(
        'SELECT * FROM cars WHERE user_id = ? AND status = "active" ORDER BY vehicle_type, make, model',
        (session['user_id'],)
    ).fetchall()
    
    # Get past cars grouped by vehicle type
    past_cars = conn.execute(
        'SELECT * FROM cars WHERE user_id = ? AND status = "past" ORDER BY vehicle_type, make, model',
        (session['user_id'],)
    ).fetchall()
    
    # Group cars by vehicle type
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
        active_cars_grouped=active_cars_grouped, 
        past_cars_grouped=past_cars_grouped)

# Add a new car
@app.route("/add_car", methods=["GET", "POST"])
@login_required
def add_car():
    if request.method == "POST":
        # Get form data
        vehicle_type = request.form.get('vehicle_type', 'Car')  # Default to 'Car' if not provided
        make = request.form.get('make', '').strip()
        model = request.form.get('model', '').strip()
        year = request.form.get('year')
        purchase_date = request.form.get('purchase_date')
        sell_date = request.form.get('sell_date')
        hours = request.form.get('hours')
        miles = request.form.get('miles')
        
        if vehicle_type == 'Boat':
            if hours:
                try:
                    hours = float(hours)
                except ValueError:
                    flash('Please enter a valid number for hours', 'error')
                    return redirect(url_for('add_car'))
            else:
                hours = None
            miles = None
        else:
            # For cars, trucks, etc. - handle miles
            if miles:
                try:
                    miles = float(miles)
                except ValueError:
                    flash('Please enter a valid number for miles', 'error')
                    return redirect(url_for('add_car'))
            else:
                miles = None
            hours = None

            # Basic validation
            if not all([make, model, year]):
                flash('Please fill in all required fields', 'error')
                return redirect(url_for('add_car'))
                
            try:
                year = int(year)  # Convert year to integer
            except ValueError:
                flash('Please enter a valid year', 'error')
                return redirect(url_for('add_car'))
                
            # Handle file upload
            image_path = None
            if 'image' in request.files:
                file = request.files['image']
                if file.filename != '' and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    # Add timestamp to make filename unique
                    filename = f"{int(time.time())}_{filename}"
                    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(file_path)
                    image_path = filename
                elif file.filename != '':
                    flash('Invalid file type. Please upload an image file (PNG, JPG, JPEG, GIF, WEBP)', 'error')
                    return redirect(url_for('add_car'))
            
            # Save to database
            conn = get_db_connection()
            try:
                conn.execute(
                    "INSERT INTO cars (user_id, vehicle_type, make, model, year, purchase_date, sell_date, image_path, hours, miles) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (session['user_id'], vehicle_type, make, model, year, purchase_date, sell_date, image_path, hours, miles)
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
            
        return render_template("add_car.html")

# Car detail page
@app.route("/car/<int:car_id>")
@login_required
def car_detail(car_id):
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row  # This makes rows accessible by column name
    
    # Get car data
    car = conn.execute('''
        SELECT * FROM cars 
        WHERE id = ? AND user_id = ?
    ''', (car_id, session['user_id'])).fetchone()
    
    if car is None:
        conn.close()
        abort(404)
    
    # Get maintenance records
    maintenance = conn.execute('''
        SELECT * FROM maintenance_records 
        WHERE car_id = ? 
        ORDER BY date DESC
    ''', (car_id,)).fetchall()
    
    # Get aftermarket parts
    parts = conn.execute('''
        SELECT * FROM aftermarket_parts 
        WHERE car_id = ? 
        ORDER BY install_date DESC
    ''', (car_id,)).fetchall()
    
    # Get scheduled maintenance
    scheduled = conn.execute('''
        SELECT * FROM scheduled_maintenance 
        WHERE car_id = ? 
        ORDER BY due_date ASC
    ''', (car_id,)).fetchall()
    
    conn.close()
    
    return render_template("car_detail.html", car=car, maintenance=maintenance, parts=parts, scheduled=scheduled)

# Edit car details
@app.route("/car/<int:car_id>/edit", methods=["GET", "POST"])
@login_required
def edit_car(car_id):
    conn = get_db_connection()
    
    if request.method == "POST":
        # Get form data
        vehicle_type = request.form.get('vehicle_type', 'Car')
        make = request.form.get('make', '').strip()
        model = request.form.get('model', '').strip()
        year = request.form.get('year')
        purchase_date = request.form.get('purchase_date')
        sell_date = request.form.get('sell_date')
        hours = request.form.get('hours')
        miles = request.form.get('miles')
        
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
            # For cars, trucks, etc. - handle miles
            if miles:
                try:
                    miles = float(miles)
                except ValueError:
                    flash('Please enter a valid number for miles', 'error')
                    return redirect(url_for('edit_car', car_id=car_id))
            else:
                miles = None  # Only set to None if miles is empty
            hours = None
        
        # Basic validation
        if not all([make, model, year]):
            flash('Please fill in all required fields', 'error')
            return redirect(url_for('edit_car', car_id=car_id))
            
        try:
            year = int(year)  # Convert year to integer
        except ValueError:
            flash('Please enter a valid year', 'error')
            return redirect(url_for('edit_car', car_id=car_id))
        
        # Get current car data
        car = conn.execute(
            "SELECT * FROM cars WHERE id = ? AND user_id = ?",
            (car_id, session['user_id'])
        ).fetchone()
        
        if car is None:
            conn.close()
            abort(404)
        
        # Handle file upload if a new image is provided
        image_path = car['image_path']  # Keep existing image by default
        if 'image' in request.files:
            file = request.files['image']
            if file.filename != '':
                if allowed_file(file.filename):
                    # Delete old image if it exists
                    if car['image_path']:
                        try:
                            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], car['image_path']))
                        except OSError:
                            pass  # If file doesn't exist, continue
                    
                    # Save new image
                    filename = secure_filename(file.filename)
                    filename = f"{int(time.time())}_{filename}"
                    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(file_path)
                    image_path = filename
                else:
                    flash('Invalid file type. Please upload an image file (PNG, JPG, JPEG, GIF, WEBP)', 'error')
                    return redirect(url_for('edit_car', car_id=car_id))
        
        # Update the car in the database
        try:
            conn.execute(
                "UPDATE cars SET vehicle_type = ?, make = ?, model = ?, year = ?, purchase_date = ?, sell_date = ?, image_path = ?, hours = ?, miles = ? WHERE id = ? AND user_id = ?",
                (vehicle_type, make, model, year, purchase_date, sell_date, image_path, hours, miles, car_id, session['user_id'])
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
    
    # GET request - redirect to car detail page (since we use modal)
    conn.close()
    return redirect(url_for('car_detail', car_id=car_id))

# Add maintenance record
@app.route("/car/<int:car_id>/add_maintenance", methods=["POST"])
def add_maintenance(car_id):
    date = request.form["date"]
    mileage = request.form.get("mileage") or None
    service_type = request.form["service_type"]
    description = request.form.get("description") or None
    cost = request.form.get("cost") or None
    shop_name = request.form.get("shop_name") or None
    
    with sqlite3.connect(DATABASE) as conn:
        c = conn.cursor()
        c.execute("""INSERT INTO maintenance_records 
                    (car_id, date, mileage, service_type, description, cost, shop_name) 
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (car_id, date, mileage, service_type, description, cost, shop_name))
        conn.commit()
    return redirect(url_for("car_detail", car_id=car_id))

# Edit maintenance record
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
    
    with sqlite3.connect(DATABASE) as conn:
        c = conn.cursor()
        # First get the current record to preserve any fields not in the form
        c.execute("SELECT * FROM maintenance_records WHERE id = ? AND car_id = ?", (record_id, car_id))
        current = c.fetchone()
        if not current:
            return redirect(url_for("car_detail", car_id=car_id))
            
        # Update only the provided fields
        update_data = {
            'date': date if date is not None else current[1],
            'mileage': mileage if mileage is not None else current[2],
            'service_type': service_type if service_type is not None else current[3],
            'description': description if description is not None else current[4],
            'cost': cost if cost is not None else current[5],
            'shop_name': shop_name if shop_name is not None else current[6]
        }
        
        c.execute("""UPDATE maintenance_records 
                    SET date = ?, mileage = ?, service_type = ?, 
                        description = ?, cost = ?, shop_name = ?
                    WHERE id = ? AND car_id = ?""",
                (update_data['date'], update_data['mileage'], update_data['service_type'],
                update_data['description'], update_data['cost'], update_data['shop_name'],
                record_id, car_id))
        conn.commit()
    return redirect(url_for("car_detail", car_id=car_id))

# Delete maintenance record
@app.route("/car/<int:car_id>/delete_maintenance/<int:record_id>")
def delete_maintenance(car_id, record_id):
    with sqlite3.connect(DATABASE) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM maintenance_records WHERE id = ? AND car_id = ?", (record_id, car_id))
        conn.commit()
    return redirect(url_for("car_detail", car_id=car_id))

# Add aftermarket part
@app.route("/car/<int:car_id>/add_part", methods=["POST"])
def add_part(car_id):
    part_name = request.form["part_name"]
    brand = request.form.get("brand") or None
    install_date = request.form.get("install_date") or None
    cost = request.form.get("cost") or None
    notes = request.form.get("notes") or None
    
    with sqlite3.connect(DATABASE) as conn:
        c = conn.cursor()
        c.execute("""INSERT INTO aftermarket_parts 
                    (car_id, part_name, brand, install_date, cost, notes) 
                    VALUES (?, ?, ?, ?, ?, ?)""",
                (car_id, part_name, brand, install_date, cost, notes))
        conn.commit()
    return redirect(url_for("car_detail", car_id=car_id))

# Edit aftermarket part
@app.route("/car/<int:car_id>/edit_part/<int:part_id>", methods=["POST"])
def edit_part(car_id, part_id):
    part_name = request.form["part_name"]
    brand = request.form.get("brand") or None
    install_date = request.form.get("install_date") or None
    cost = request.form.get("cost") or None
    notes = request.form.get("notes") or None
    
    with sqlite3.connect(DATABASE) as conn:
        c = conn.cursor()
        c.execute("""UPDATE aftermarket_parts 
                    SET part_name = ?, brand = ?, install_date = ?, cost = ?, notes = ?
                    WHERE id = ? AND car_id = ?""",
                (part_name, brand, install_date, cost, notes, part_id, car_id))
        conn.commit()
    return redirect(url_for("car_detail", car_id=car_id))

# Delete aftermarket part
@app.route("/car/<int:car_id>/delete_part/<int:part_id>")
def delete_part(car_id, part_id):
    with sqlite3.connect(DATABASE) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM aftermarket_parts WHERE id = ? AND car_id = ?", (part_id, car_id))
        conn.commit()
    return redirect(url_for("car_detail", car_id=car_id))

# Add scheduled maintenance
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

# Mark scheduled maintenance as completed
@app.route("/car/<int:car_id>/complete_scheduled/<int:scheduled_id>")
def complete_scheduled(car_id, scheduled_id):
    with sqlite3.connect(DATABASE) as conn:
        c = conn.cursor()
        c.execute("UPDATE scheduled_maintenance SET completed = 1 WHERE id = ? AND car_id = ?", 
                (scheduled_id, car_id))
        conn.commit()
    return redirect(url_for("car_detail", car_id=car_id))

# Edit scheduled maintenance
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

# Delete scheduled maintenance
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
    
    conn = get_db_connection()
    conn.execute(
        'UPDATE cars SET status = ?, reason = ? WHERE id = ? AND user_id = ?',
        ('past', reason, car_id, session['user_id'])
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
    
    # Verify user owns this car
    car = conn.execute('SELECT * FROM cars WHERE id = ? AND user_id = ?', 
        (car_id, session['user_id'])).fetchone()
    
    if not car:
        conn.close()
        flash('Vehicle not found', 'error')
        return redirect(url_for('cars'))
    
    # Delete the car (this will also delete related maintenance records due to CASCADE)
    conn.execute('DELETE FROM cars WHERE id = ?', (car_id,))
    conn.commit()
    conn.close()
    
    flash(f'{car["year"]} {car["make"]} {car["model"]} has been deleted', 'success')
    return redirect(url_for('cars'))

# Serve uploaded files
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == "__main__":
    app.run(debug=True)
