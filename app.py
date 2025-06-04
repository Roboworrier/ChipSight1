"""
ChipSight - Digital Twin for Manufacturing
Copyright (c) 2025 Diwakar Singh. All rights reserved.
See COMPANY_LICENSE.md for license terms.

This software and its source code are the exclusive intellectual property of Diwakar Singh.
Unauthorized copying, modification, distribution, or use is strictly prohibited.
"""

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, session, make_response
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta, timezone
import os
import pandas as pd
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import relationship, joinedload
from jinja2 import FileSystemLoader
import sys
from markupsafe import Markup
from sqlalchemy import case
from io import BytesIO
import logging
from logging.handlers import RotatingFileHandler
import traceback
import shutil
import random

sys.setrecursionlimit(3000)  # Increase recursion limit if needed

# Disable .env file loading
os.environ['FLASK_SKIP_DOTENV'] = '1'

# Initialize Flask app
app = Flask(__name__)

# Configure logging
if not os.path.exists('logs'):
    os.makedirs('logs')

file_handler = RotatingFileHandler('logs/chipsight.log', maxBytes=1024 * 1024, backupCount=10)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
))
file_handler.setLevel(logging.INFO)
app.logger.addHandler(file_handler)
app.logger.setLevel(logging.INFO)
app.logger.info('ChipSight startup')

# Configure backup directory
BACKUP_DIR = 'backups'
if not os.path.exists(BACKUP_DIR):
    os.makedirs(BACKUP_DIR)

def backup_database():
    """Create a backup of the database file"""
    try:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = os.path.join(BACKUP_DIR, f'digital_twin_{timestamp}.db')
        
        # Only backup if the database file exists
        if os.path.exists('digital_twin.db'):
            shutil.copy2('digital_twin.db', backup_path)
            
            # Keep only last 7 days of backups
            for backup_file in os.listdir(BACKUP_DIR):
                backup_file_path = os.path.join(BACKUP_DIR, backup_file)
                if os.path.getctime(backup_file_path) < (datetime.now() - timedelta(days=7)).timestamp():
                    os.remove(backup_file_path)
            
            app.logger.info(f'Database backed up to {backup_path}')
            return True
    except Exception as e:
        app.logger.error(f'Database backup failed: {str(e)}')
        return False

def log_error(error_type, message, stack_trace=None):
    """Log error to database and file"""
    try:
        error_log = SystemLog(
            level='ERROR',
            source=error_type,
            message=message,
            stack_trace=stack_trace
        )
        db.session.add(error_log)
        db.session.commit()
        app.logger.error(f'{error_type}: {message}')
        if stack_trace:
            app.logger.error(f'Stack trace: {stack_trace}')
    except Exception as e:
        app.logger.error(f'Error logging failed: {str(e)}')

@app.before_request
def before_request():
    """Perform actions before each request"""
    # Create a backup every 6 hours
    try:
        last_backup_file = max([f for f in os.listdir(BACKUP_DIR) if f.startswith('digital_twin_')], 
                             key=lambda x: os.path.getctime(os.path.join(BACKUP_DIR, x)), 
                             default=None)
        if last_backup_file:
            last_backup_time = datetime.fromtimestamp(os.path.getctime(os.path.join(BACKUP_DIR, last_backup_file)))
            if datetime.now() - last_backup_time > timedelta(hours=6):
                backup_database()
        else:
            backup_database()
    except Exception as e:
        app.logger.error(f'Backup check failed: {str(e)}')

@app.errorhandler(404)
def not_found_error(error):
    """Handle 404 errors"""
    log_error('NotFound', f'Page not found: {request.url}')
    return render_template('errors/404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors"""
    db.session.rollback()
    stack_trace = traceback.format_exc()
    log_error('InternalServer', str(error), stack_trace)
    return render_template('errors/500.html'), 500

@app.errorhandler(SQLAlchemyError)
def database_error(error):
    """Handle database errors"""
    db.session.rollback()
    stack_trace = traceback.format_exc()
    log_error('Database', str(error), stack_trace)
    return render_template('errors/500.html'), 500

# Custom Jinja2 filter for nl2br
def nl2br_filter(value):
    if not value:
        return ""
    # Convert newlines to <br> tags
    return Markup(str(value).replace('\n', '<br>\n'))

# Register the filter with Jinja2
app.jinja_env.filters['nl2br'] = nl2br_filter

# Basic configuration
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-here')  # Change this to a secure random key
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///digital_twin.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['ALLOWED_EXTENSIONS'] = {'xlsx'}  # Only allow Excel files

# Session configuration (for cross-device login)
app.config['SESSION_COOKIE_DOMAIN'] = None
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False

# Encoding configuration
app.config['JSON_AS_ASCII'] = False
app.jinja_env.charset = 'utf-8'
app.jinja_env.auto_reload = True
app.config['TEMPLATES_AUTO_RELOAD'] = True

# Configure Jinja2 template loader with explicit encoding
template_loader = FileSystemLoader(
    searchpath='templates',
    encoding='utf-8-sig'  # Handle UTF-8 with BOM
)
app.jinja_loader = template_loader

# Initialize database
db = SQLAlchemy(app)

# Initialize Flask-Migrate
from flask_migrate import Migrate
migrate = Migrate(app, db)

# --- Models ---

class Project(db.Model):
    __tablename__ = 'project'
    id = db.Column(db.Integer, primary_key=True)
    project_code = db.Column(db.String(50), unique=True, nullable=False)
    project_name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    route = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    is_deleted = db.Column(db.Boolean, default=False)
    deleted_at = db.Column(db.DateTime, nullable=True)

    end_products = relationship("EndProduct", back_populates="project_rel", cascade="all, delete-orphan")

class EndProduct(db.Model):
    __tablename__ = 'end_product'
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)  # End product name
    sap_id = db.Column(db.String(50), nullable=False, unique=True)
    quantity = db.Column(db.Integer, nullable=False) # Planned quantity for this SAP ID
    completion_date = db.Column(db.Date, nullable=False)
    setup_time_std = db.Column(db.Float, nullable=False)  # Standard Setup Time in minutes
    cycle_time_std = db.Column(db.Float, nullable=False)  # Standard Cycle Time per unit in minutes
    is_first_piece_fpi_required = db.Column(db.Boolean, nullable=False, default=True)
    is_last_piece_lpi_required = db.Column(db.Boolean, nullable=False, default=True)
    
    project_rel = relationship("Project", back_populates="end_products")
    machine_drawings = relationship("MachineDrawing", back_populates="end_product_rel", cascade="all, delete-orphan")
    # Link to OperatorLogs to track overall progress for this SAP ID
    operator_logs_for_sap = relationship("OperatorLog", foreign_keys='OperatorLog.end_product_sap_id', back_populates="end_product_sap_id_rel")


class MachineDrawing(db.Model):
    __tablename__ = 'machine_drawing'
    id = db.Column(db.Integer, primary_key=True)
    drawing_number = db.Column(db.String(100), unique=True, nullable=False)
    sap_id = db.Column(db.String(50), db.ForeignKey('end_product.sap_id'), nullable=False)
    
    end_product_rel = relationship("EndProduct", back_populates="machine_drawings")
    operator_logs = relationship("OperatorLog", foreign_keys='OperatorLog.drawing_id', back_populates="drawing_rel", cascade="all, delete-orphan")
    rework_items = relationship("ReworkQueue", foreign_keys='ReworkQueue.drawing_id', back_populates="drawing_rel")
    scrapped_items = relationship("ScrapLog", foreign_keys='ScrapLog.drawing_id', back_populates="drawing_rel")


class Machine(db.Model):
    __tablename__ = 'machine'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    status = db.Column(db.String(20), default='available')  # available, in_use, breakdown
    
    operator_sessions = relationship("OperatorSession", back_populates="machine_rel", cascade="all, delete-orphan")
    # The 'breakdown_logs' relationship is now defined after MachineBreakdownLog

class OperatorSession(db.Model):
    __tablename__ = 'operator_session'
    id = db.Column(db.Integer, primary_key=True)
    operator_name = db.Column(db.String(100), nullable=False)
    machine_id = db.Column(db.Integer, db.ForeignKey('machine.id'), nullable=False)
    shift = db.Column(db.String(20), nullable=False)
    login_time = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    logout_time = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    
    machine_rel = relationship("Machine", back_populates="operator_sessions")
    operator_logs = db.relationship('OperatorLog', backref='operator_session', 
                                  foreign_keys='OperatorLog.operator_session_id')
    # The 'reported_breakdowns' relationship is now defined after MachineBreakdownLog

class OperatorLog(db.Model):
    __tablename__ = 'operator_log'
    id = db.Column(db.Integer, primary_key=True)
    drawing_number = db.Column(db.String(100))
    drawing_id = db.Column(db.Integer, db.ForeignKey('machine_drawing.id'), nullable=True)
    setup_start_time = db.Column(db.DateTime)  # Renamed from setup_start
    setup_end_time = db.Column(db.DateTime)    # Renamed from setup_done
    first_cycle_start_time = db.Column(db.DateTime)  # Renamed from cycle_start
    last_cycle_end_time = db.Column(db.DateTime)     # Renamed from cycle_done
    current_status = db.Column(db.String(50))  # Setup Started, Setup Done, Cycle Started, Cycle Completed, etc.
    setup_time = db.Column(db.Float)  # Time taken for setup in minutes
    cycle_time = db.Column(db.Float)  # Time taken for cycle in minutes
    abort_reason = db.Column(db.Text)
    notes = db.Column(db.Text)  # Add notes column for tracking log history
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    batch_number = db.Column(db.String(50))  # Track production batches
    run_planned_quantity = db.Column(db.Integer)  # Renamed from planned_quantity
    run_completed_quantity = db.Column(db.Integer, default=0)  # Renamed from completed_quantity
    run_rejected_quantity_fpi = db.Column(db.Integer, default=0)  # Split from rejected_quantity
    run_rejected_quantity_lpi = db.Column(db.Integer, default=0)  # Split from rejected_quantity
    run_rework_quantity_fpi = db.Column(db.Integer, default=0)  # Split from rework_quantity
    run_rework_quantity_lpi = db.Column(db.Integer, default=0)  # Split from rework_quantity
    quality_status = db.Column(db.String(20))  # Pending QC, QC Pass, QC Fail, In Rework
    quality_checks = db.relationship('QualityCheck', backref='operator_log', lazy=True)
    operator_id = db.Column(db.String(50))  # Track operator responsible
    machine_id = db.Column(db.String(50))  # Track machine used
    shift = db.Column(db.String(20))  # Track shift
    # New columns for enhanced FPI/LPI control
    fpi_status = db.Column(db.String(20), default='Pending')  # Pending, Pass, Fail
    fpi_timestamp = db.Column(db.DateTime)  # When FPI was performed
    fpi_inspector = db.Column(db.String(50))  # Inspector who performed FPI
    lpi_status = db.Column(db.String(20))  # Pending, Pass, Fail
    lpi_timestamp = db.Column(db.DateTime)  # When LPI was performed
    lpi_inspector = db.Column(db.String(50))  # Inspector who performed LPI
    production_hold_fpi = db.Column(db.Boolean, default=True)  # Renamed from production_hold
    drawing_revision = db.Column(db.String(20))  # Track drawing revision
    sap_id = db.Column(db.String(100))  # Link to SAP order
    end_product_sap_id = db.Column(db.String(50), db.ForeignKey('end_product.sap_id'), nullable=True)
    operator_session_id = db.Column(db.Integer, db.ForeignKey('operator_session.id'))

    # Relationships
    end_product_sap_id_rel = relationship("EndProduct", back_populates="operator_logs_for_sap")
    drawing_rel = relationship("MachineDrawing", back_populates="operator_logs")
    
    # Add missing relationships
    rework_items_sourced = relationship(
        "ReworkQueue", 
        foreign_keys='ReworkQueue.source_operator_log_id',
        back_populates="source_operator_log_rel"
    )
    
    rework_attempt_for_queue = relationship(
        "ReworkQueue",
        foreign_keys='ReworkQueue.assigned_operator_log_id',
        back_populates="assigned_operator_log_rel",
        uselist=False
    )
    
    # Add relationship for scrapped_items if missing
    scrapped_items = relationship(
        "ScrapLog",
        foreign_keys='ScrapLog.operator_log_id',
        back_populates="operator_log_rel"
    )

class QualityCheck(db.Model):
    __tablename__ = 'quality_check'
    id = db.Column(db.Integer, primary_key=True)
    operator_log_id = db.Column(db.Integer, db.ForeignKey('operator_log.id'), nullable=False)
    inspector_name = db.Column(db.String(100), nullable=False)
    check_type = db.Column(db.String(20), nullable=False)  # FPI, LPI
    result = db.Column(db.String(10), nullable=False)      # pass, reject, rework
    
    lpi_quantity_inspected = db.Column(db.Integer, nullable=True) # For LPI: how many in batch inspected
    lpi_quantity_rejected = db.Column(db.Integer, nullable=True)  # For LPI: how many of inspected are rejected
    lpi_quantity_to_rework = db.Column(db.Integer, nullable=True) # For LPI: how many of inspected go to rework

    rejection_reason = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    
    operator_log_rel = relationship("OperatorLog", back_populates="quality_checks", overlaps="operator_log")
    # If this QC sends items to rework
    rework_items_generated = relationship("ReworkQueue", foreign_keys='ReworkQueue.originating_quality_check_id', back_populates="originating_quality_check_rel")
    # If this QC results in scrap
    scrapped_items_generated = relationship(
        "ScrapLog", 
        foreign_keys='ScrapLog.originating_quality_check_id',
        back_populates="originating_quality_check_rel"
    )

class ReworkQueue(db.Model):
    __tablename__ = 'rework_queue'
    id = db.Column(db.Integer, primary_key=True)
    source_operator_log_id = db.Column(db.Integer, db.ForeignKey('operator_log.id'), nullable=True)
    originating_quality_check_id = db.Column(db.Integer, db.ForeignKey('quality_check.id'), nullable=False)
    drawing_id = db.Column(db.Integer, db.ForeignKey('machine_drawing.id'), nullable=False)
    
    quantity_to_rework = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(30), default='pending_manager_approval')
    rejection_reason = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    
    # Manager approval fields
    manager_approved_by = db.Column(db.String(100), nullable=True)
    manager_approval_time = db.Column(db.DateTime, nullable=True)
    manager_notes = db.Column(db.Text, nullable=True)
    
    # Log for the rework attempt itself
    assigned_operator_log_id = db.Column(db.Integer, db.ForeignKey('operator_log.id'), nullable=True, unique=True) 

    # Fix relationships
    source_operator_log_rel = relationship(
        "OperatorLog", 
        foreign_keys=[source_operator_log_id],
        back_populates="rework_items_sourced"
    )
    
    originating_quality_check_rel = relationship(
        "QualityCheck", 
        foreign_keys=[originating_quality_check_id],
        back_populates="rework_items_generated"
    )
    
    drawing_rel = relationship(
        "MachineDrawing", 
        foreign_keys=[drawing_id],
        back_populates="rework_items"
    )
    
    assigned_operator_log_rel = relationship(
        "OperatorLog", 
        foreign_keys=[assigned_operator_log_id],
        back_populates="rework_attempt_for_queue",
        uselist=False
    )

class ScrapLog(db.Model):
    __tablename__ = 'scrap_log'
    id = db.Column(db.Integer, primary_key=True)
    originating_quality_check_id = db.Column(db.Integer, db.ForeignKey('quality_check.id'), nullable=False)
    drawing_id = db.Column(db.Integer, db.ForeignKey('machine_drawing.id'), nullable=False)
    quantity_scrapped = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.Text, nullable=True)
    scrapped_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    scrapped_by = db.Column(db.String(100), nullable=True)  # Added missing column
    operator_log_id = db.Column(db.Integer, db.ForeignKey('operator_log.id'), nullable=True)  # Added missing column

    originating_quality_check_rel = relationship(
        "QualityCheck", 
        foreign_keys=[originating_quality_check_id], 
        back_populates="scrapped_items_generated"
    )
    
    drawing_rel = relationship(
        "MachineDrawing", 
        foreign_keys=[drawing_id], 
        back_populates="scrapped_items"
    )
    
    operator_log_rel = relationship(
        "OperatorLog", 
        foreign_keys=[operator_log_id], 
        back_populates="scrapped_items"
    )

class MachineBreakdownLog(db.Model):
    __tablename__ = 'machine_breakdown_log'
    id = db.Column(db.Integer, primary_key=True)
    machine_id = db.Column(db.Integer, db.ForeignKey('machine.id'), nullable=False)
    breakdown_start_time = db.Column(db.DateTime, nullable=False, default=datetime.now(timezone.utc))
    breakdown_end_time = db.Column(db.DateTime, nullable=True)
    reported_by_operator_session_id = db.Column(db.Integer, db.ForeignKey('operator_session.id'), nullable=True)
    notes = db.Column(db.Text, nullable=True) # For operator to add a reason for breakdown

    machine_rel = relationship("Machine", back_populates="breakdown_logs")
    operator_session_rel = relationship("OperatorSession", back_populates="reported_breakdowns")

# Define relationships after all relevant models are defined
Machine.breakdown_logs = relationship("MachineBreakdownLog", order_by=MachineBreakdownLog.breakdown_start_time, back_populates="machine_rel")
OperatorSession.reported_breakdowns = relationship("MachineBreakdownLog", back_populates="operator_session_rel")

class SystemLog(db.Model):
    __tablename__ = 'system_log'
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    level = db.Column(db.String(20), nullable=False)  # ERROR, WARNING, INFO
    source = db.Column(db.String(100), nullable=False)  # Component/module that generated the log
    message = db.Column(db.Text, nullable=False)
    stack_trace = db.Column(db.Text, nullable=True)
    resolved = db.Column(db.Boolean, default=False)
    resolved_by = db.Column(db.String(100), nullable=True)
    resolved_at = db.Column(db.DateTime, nullable=True)

# --- Helper Functions ---

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def get_machine_choices():
    """Returns list of available machines"""
    return [
        ("Leadwell-1", "Leadwell-1"), 
        ("Leadwell-2", "Leadwell-2"),
        ("VMC1", "VMC1"),
        ("VMC2", "VMC2"),
        ("VMC3", "VMC3"), 
        ("VMC4", "VMC4"),
        ("HAAS-1", "HAAS-1"),
        ("HAAS-2", "HAAS-2")
    ]

def clear_user_session():
    """Clears all session variables related to user authentication"""
    keys = [
        'active_role', 'username', 'user_role',
        'operator_session_id', 'operator_name',
        'machine_name', 'current_drawing_id',
        'current_operator_log_id', 'quality_inspector_name'
    ]
    for key in keys:
        session.pop(key, None)

def ensure_utc_aware(dt):
    """Ensures datetime objects are timezone-aware"""
    if dt and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt

@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    if 'text/html' in response.headers.get('Content-Type', ''):
        response.headers['Content-Type'] = 'text/html; charset=utf-8'
    return response

# --- ROUTES ---

@app.route('/')
def home():
    return redirect(url_for('login_general'))

# --- ADMIN ---
@app.route('/admin')
def admin_dashboard():
    if session.get('active_role') != 'admin':
        flash('Access denied. Please login as Admin.', 'danger')
        return redirect(url_for('login_general'))

    # Add this block to calculate or fetch performance_metrics
    performance_metrics = {
        'database_size': os.path.getsize('digital_twin.db') if os.path.exists('digital_twin.db') else 0
    }

    # System statistics
    stats = {
        'total_users': OperatorSession.query.distinct(OperatorSession.operator_name).count(),
        'active_sessions': OperatorSession.query.filter_by(is_active=True).count(),
        'total_projects': Project.query.count(),
        'active_projects': Project.query.filter_by(is_deleted=False).count(),
        'total_machines': Machine.query.count(),
        'active_machines': Machine.query.filter_by(status='in_use').count(),
        'total_drawings': MachineDrawing.query.count(),
        'total_quality_checks': QualityCheck.query.count(),
        'pending_quality_checks': OperatorLog.query.filter(
            OperatorLog.current_status.in_(['cycle_completed_pending_fpi', 'cycle_completed_pending_lpi'])
        ).count(),
        'total_rework_items': ReworkQueue.query.count(),
        'pending_rework': ReworkQueue.query.filter_by(status='pending_manager_approval').count()
    }

    # Error logs
    error_logs = SystemLog.query.filter_by(resolved=False).order_by(SystemLog.timestamp.desc()).limit(10).all()

    # Backup status
    backups = sorted([f for f in os.listdir(BACKUP_DIR) if f.startswith('digital_twin_')],
                    key=lambda x: os.path.getctime(os.path.join(BACKUP_DIR, x)),
                    reverse=True)[:5]

    return render_template('admin.html',
                         stats=stats,
                         error_logs=error_logs,
                         backups=backups,
                         performance_metrics=performance_metrics)  # Pass the new variable

@app.route('/admin/export_logs', methods=['POST'])
def admin_export_logs():
    if session.get('active_role') != 'admin':
        flash('Access denied. Please login as Admin.', 'danger')
        return redirect(url_for('login_general'))

    logs = SystemLog.query.order_by(SystemLog.timestamp.desc()).all()
    
    # Create pandas DataFrame
    df = pd.DataFrame([{
        'Timestamp': log.timestamp,
        'Level': log.level,
        'Source': log.source,
        'Message': log.message,
        'Resolved': 'Yes' if log.resolved else 'No'
    } for log in logs])

    # Save to BytesIO
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name='System Logs', index=False)
    
    output.seek(0)
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'system_logs_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    )

@app.route('/admin/resolve_log', methods=['POST'])
def admin_resolve_log():
    if session.get('active_role') != 'admin':
        flash('Access denied. Please login as Admin.', 'danger')
        return redirect(url_for('login_general'))

    log_id = request.form.get('log_id')
    if log_id:
        log = SystemLog.query.get(log_id)
        if log:
            log.resolved = True
            log.resolved_by = session.get('username')
            log.resolved_at = datetime.now(timezone.utc)
            db.session.commit()
            flash('Log marked as resolved.', 'success')
        else:
            flash('Log not found.', 'danger')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/create_backup', methods=['POST'])
def admin_create_backup():
    if session.get('active_role') != 'admin':
        flash('Access denied. Please login as Admin.', 'danger')
        return redirect(url_for('login_general'))

    if backup_database():
        flash('Database backup created successfully.', 'success')
    else:
        flash('Backup failed. Check logs for details.', 'danger')
    return redirect(url_for('admin_dashboard'))

# --- AUTHENTICATION & ROLE MANAGEMENT ---
@app.route('/login', methods=['GET', 'POST'])
def login_general():
    if request.method == 'POST':
        clear_user_session()
        username = request.form.get('username')
        password = request.form.get('password') 
        # Add this block for admin
        if username == 'admin' and password == 'adminpass':  # Change this password!
            session['active_role'] = 'admin'
            session['username'] = username
            print("Logged in as", username, "with role", session.get('active_role'))
            print("Session contents:", dict(session))
            flash('Admin login successful!', 'success')
            return redirect(url_for('admin_dashboard'))
        elif username == 'planthead' and password == 'ph123':
            session['active_role'] = 'plant_head'
            session['username'] = username
            print("Logged in as", username, "with role", session.get('active_role'))
            print("Session contents:", dict(session))
            flash('Plant Head login successful!', 'success')
            return redirect(url_for('plant_head_dashboard'))
        elif username == 'planner' and password == 'plannerpass':
            session['active_role'] = 'planner'
            session['username'] = username
            print("Logged in as", username, "with role", session.get('active_role'))
            print("Session contents:", dict(session))
            flash('Planner login successful!', 'success')
            return redirect(url_for('planner_dashboard'))
        elif username == 'manager' and password == 'managerpass':
            session['active_role'] = 'manager'
            session['username'] = username
            print("Logged in as", username, "with role", session.get('active_role'))
            print("Session contents:", dict(session))
            flash('Manager login successful!', 'success')
            return redirect(url_for('manager_dashboard'))
        elif username == 'quality' and password == 'qualitypass':
            session['active_role'] = 'quality'
            session['username'] = username 
            print("Logged in as", username, "with role", session.get('active_role'))
            print("Session contents:", dict(session))
            flash('Quality login successful!', 'success')
            return redirect(url_for('quality_dashboard'))
        elif username == 'plant_head' and password == 'plantpass':
            session['active_role'] = 'plant_head'
            session['username'] = username
            print("Logged in as", username, "with role", session.get('active_role'))
            print("Session contents:", dict(session))
            flash('Plant Head login successful!', 'success')
            return redirect(url_for('plant_head_dashboard'))
        else:
            flash('Invalid credentials.', 'danger')
    return render_template('login_general.html')

@app.route('/logout_general', methods=['POST'])
def logout_general():
    clear_user_session()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login_general'))


# --- PLANNER ---
@app.route('/planner', methods=['GET', 'POST'])
def planner_dashboard():
    print(f"DEBUG: Session at start of /planner: {dict(session)}") 
    if session.get('active_role') != 'planner':
        flash('Access denied. Please login as Planner.', 'danger')
        return redirect(url_for('login_general'))

    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'delete_project':
            project_id = request.form.get('project_id')
            if project_id:
                project = Project.query.get(project_id)
                if project:
                    project.is_deleted = True
                    project.deleted_at = datetime.now(timezone.utc)
                    db.session.commit()
                    flash('Project deleted successfully.', 'success')
                else:
                    flash('Project not found.', 'danger')
            return redirect(url_for('planner_dashboard'))
            
        elif action == 'delete_end_product':
            end_product_id = request.form.get('end_product_id')
            if end_product_id:
                end_product = EndProduct.query.get(end_product_id)
                if end_product:
                    db.session.delete(end_product)
                    db.session.commit()
                    flash('End product deleted successfully.', 'success')
                else:
                    flash('End product not found.', 'danger')
            return redirect(url_for('planner_dashboard'))
            
        elif 'production_plan_file' in request.files:
            file = request.files['production_plan_file']
        if file and allowed_file(file.filename):
            try:
                    # Read the Excel file
                df = pd.read_excel(file, dtype={
                    'project_code': str,
                    'sap_id': str, 
                    'end_product': str, 
                    'discription': str, 
                    'route': str
                })
                print(f"DEBUG: Columns found in Excel (raw): {df.columns.tolist()}")

                # Normalize column names from the DataFrame: convert to lowercase and strip spaces
                normalized_df_columns = [str(col).lower().strip() for col in df.columns]
                df.columns = normalized_df_columns
                print(f"DEBUG: Columns found in Excel (normalized): {normalized_df_columns}")

                # Define required columns in lowercase, matching the user's Excel file
                required_cols = ['project_code', 'project_name', 'end_product',
                               'sap_id', 'discription', 'qty', 'route',
                               'completion_date', 'st', 'ct']

                # Check if all required columns are present
                missing_cols = [col for col in required_cols if col not in normalized_df_columns]

                if missing_cols:
                    flash(f'Excel file missing required columns. Missing: {", ".join(missing_cols)}. Found: {", ".join(normalized_df_columns)}', 'danger')
                else:
                    for index, row in df.iterrows():
                        project_code = str(row['project_code']).strip()
                        sap_id_val = row['sap_id']
                        if isinstance(sap_id_val, bytes):
                            sap_id_val = sap_id_val.decode('utf-8', errors='ignore').strip()
                        else:
                            sap_id_val = str(sap_id_val).strip()

                        project = Project.query.filter_by(project_code=project_code).first()
                        if not project:
                            project = Project(
                                project_code=project_code,
                                project_name=str(row['project_name']).strip(),
                                description=str(row.get('discription', '')).strip(),
                                route=str(row.get('route', '')).strip()
                            )
                            db.session.add(project)
                            db.session.flush()

                        end_product = EndProduct.query.filter_by(sap_id=sap_id_val).first()
                        if not end_product:
                            end_product = EndProduct(
                                project_id=project.id,
                                name=str(row['end_product']).strip(),
                                sap_id=sap_id_val,
                                quantity=int(row['qty']),
                                completion_date=pd.to_datetime(row['completion_date']).date(),
                                setup_time_std=float(row['st']),
                                cycle_time_std=float(row['ct'])
                            )
                            db.session.add(end_product)
                        else:
                            end_product.project_id = project.id 
                            end_product.name = str(row['end_product']).strip()
                            end_product.quantity = int(row['qty'])
                            end_product.completion_date = pd.to_datetime(row['completion_date']).date()
                            end_product.setup_time_std = float(row['st'])
                            end_product.cycle_time_std = float(row['ct'])
                        
                    db.session.commit()
                    flash('Production plan uploaded successfully!', 'success')
            except Exception as e:
                db.session.rollback()
                flash(f'Error uploading plan: {str(e)}', 'danger')
        else:
            flash('Invalid file type or no file selected. Please upload an .xlsx file.', 'warning')
        return redirect(url_for('planner_dashboard'))
            
    # Get only active (non-deleted) projects for planner view
    projects = Project.query.filter_by(is_deleted=False).order_by(Project.project_code).all()

    # --- Digital Twin Summary Data ---
    # Production summary by end product
    production_summary = db.session.query(
        EndProduct.name,
        EndProduct.sap_id,
        EndProduct.quantity,
        db.func.sum(OperatorLog.run_completed_quantity).label('completed'),
        db.func.sum(OperatorLog.run_rejected_quantity_fpi + OperatorLog.run_rejected_quantity_lpi).label('rejected'),
        db.func.sum(OperatorLog.run_rework_quantity_fpi + OperatorLog.run_rework_quantity_lpi).label('rework')
    ).join(OperatorLog, OperatorLog.end_product_sap_id == EndProduct.sap_id, isouter=True)
    production_summary = production_summary.group_by(EndProduct.id).all()

    # Recent/completed end products (FIXED: use .having for aggregate)
    completed_end_products = (
        db.session.query(EndProduct)
        .outerjoin(OperatorLog, OperatorLog.end_product_sap_id == EndProduct.sap_id)
        .group_by(EndProduct.id)
        .having(db.func.coalesce(db.func.sum(OperatorLog.run_completed_quantity), 0) >= EndProduct.quantity)
        .all()
    )

    # Recent quality checks
    recent_quality_checks = QualityCheck.query.order_by(QualityCheck.timestamp.desc()).limit(10).all()

    # Recent/pending rework
    recent_rework = ReworkQueue.query.order_by(ReworkQueue.created_at.desc()).limit(10).all()

    # Recent scrap/rejects
    recent_scrap = ScrapLog.query.order_by(ScrapLog.scrapped_at.desc()).limit(10).all()

    digital_twin_url = url_for('digital_twin_dashboard')

    return render_template('planner.html', projects=projects,
        production_summary=production_summary,
        completed_end_products=completed_end_products,
        recent_quality_checks=recent_quality_checks,
        recent_rework=recent_rework,
        recent_scrap=recent_scrap,
        digital_twin_url=digital_twin_url
    )

# --- MANAGER ---
@app.route('/manager', methods=['GET', 'POST'])
def manager_dashboard():
    if session.get('active_role') != 'manager':
        flash('Access denied. Please login as Manager.', 'danger')
        return redirect(url_for('login_general'))

    if request.method == 'POST':
        action = request.form.get('action')
        
        # Handle drawing-SAP mapping upload
        if 'drawing_mapping_file' in request.files:
            file = request.files['drawing_mapping_file']
            if file and allowed_file(file.filename):
                try:
                    df = pd.read_excel(file)
                    
                    # Validate required columns
                    if not all(col in df.columns for col in ['drawing_number', 'sap_id']):
                        flash('File must contain "drawing_number" and "sap_id" columns', 'danger')
                        return redirect(url_for('manager_dashboard'))
                    
                    # Process each row
                    for _, row in df.iterrows():
                        drawing_number = str(row['drawing_number']).strip()
                        sap_id = str(row['sap_id']).strip()
                        
                        # Validate SAP ID exists
                        if not EndProduct.query.filter_by(sap_id=sap_id).first():
                            flash(f'SAP ID {sap_id} not found - skipping drawing {drawing_number}', 'warning')
                            continue
                            
                        # Update or create drawing
                        drawing = MachineDrawing.query.filter_by(drawing_number=drawing_number).first()
                        if drawing:
                            drawing.sap_id = sap_id
                        else:
                            drawing = MachineDrawing(
                                drawing_number=drawing_number,
                                sap_id=sap_id
                            )
                            db.session.add(drawing)
                    
                    db.session.commit()
                    flash('Drawing-SAP mapping updated successfully!', 'success')
                    
                except Exception as e:
                    db.session.rollback()
                    flash(f'Error processing file: {str(e)}', 'danger')
            
            return redirect(url_for('manager_dashboard'))

        # Handle rework approvals/rejections
        elif action in ['approve_rework', 'reject_rework']:
            rework_id = request.form.get('rework_id')
            manager_notes = request.form.get('manager_notes', '').strip()
            
            if not rework_id:
                flash('Rework ID is required for approval.', 'danger')
            else:
                rework_item = ReworkQueue.query.get(rework_id)
                if not rework_item:
                    flash('Rework item not found.', 'danger')
                else:
                    rework_item.status = 'manager_approved' if action == 'approve_rework' else 'manager_rejected'
                    rework_item.manager_approved_by = session.get('username')
                    rework_item.manager_approval_time = datetime.now(timezone.utc)
                    rework_item.manager_notes = manager_notes
                    db.session.commit()
                    flash('Rework request approved successfully.', 'success')
            
            return redirect(url_for('manager_dashboard'))

    # Get data for template
    rework_queue = ReworkQueue.query.order_by(ReworkQueue.created_at.desc()).all()
    drawings = MachineDrawing.query.order_by(MachineDrawing.drawing_number).all()
    
    # --- Digital Twin Summary Data ---
    production_summary = db.session.query(
        EndProduct.name,
        EndProduct.sap_id,
        EndProduct.quantity,
        db.func.sum(OperatorLog.run_completed_quantity).label('completed'),
        db.func.sum(OperatorLog.run_rejected_quantity_fpi + OperatorLog.run_rejected_quantity_lpi).label('rejected'),
        db.func.sum(OperatorLog.run_rework_quantity_fpi + OperatorLog.run_rework_quantity_lpi).label('rework')
    ).join(OperatorLog, OperatorLog.end_product_sap_id == EndProduct.sap_id, isouter=True)
    production_summary = production_summary.group_by(EndProduct.id).all()

    completed_end_products = (
        db.session.query(EndProduct)
        .outerjoin(OperatorLog, OperatorLog.end_product_sap_id == EndProduct.sap_id)
        .group_by(EndProduct.id)
        .having(db.func.coalesce(db.func.sum(OperatorLog.run_completed_quantity), 0) >= EndProduct.quantity)
        .all()
    )

    recent_quality_checks = QualityCheck.query.order_by(QualityCheck.timestamp.desc()).limit(10).all()
    recent_rework = ReworkQueue.query.order_by(ReworkQueue.created_at.desc()).limit(10).all()
    recent_scrap = ScrapLog.query.order_by(ScrapLog.scrapped_at.desc()).limit(10).all()
    digital_twin_url = url_for('digital_twin_dashboard')
    
    return render_template('manager.html',
        rework_queue=rework_queue,
        drawings=drawings,
        production_summary=production_summary,
        completed_end_products=completed_end_products,
        recent_quality_checks=recent_quality_checks,
        recent_rework=recent_rework,
        recent_scrap=recent_scrap,
        digital_twin_url=digital_twin_url
    )

# --- OPERATOR ---
@app.route('/operator_login', methods=['GET', 'POST'])
def operator_login():
    if request.method == 'POST':
        clear_user_session()

        operator_name = request.form.get('operator_name', '').strip()
        machine_name = request.form.get('machine_name')
        shift = request.form.get('shift')

        if not operator_name or not machine_name or not shift:
            flash('All fields are required for login.', 'danger')
        else:
            machine = Machine.query.filter_by(name=machine_name).first()
            if not machine:
                flash(f'Machine {machine_name} not found.', 'danger')
            else:
                # End any previous active sessions
                old_sessions = OperatorSession.query.filter(
                    db.or_(
                        OperatorSession.operator_name == operator_name,
                        OperatorSession.machine_id == machine.id
                    ),
                    OperatorSession.is_active == True
                ).all()
                
                for old_session in old_sessions:
                    old_session.is_active = False
                    old_session.logout_time = datetime.now(timezone.utc)
                    
                    # Close any hanging logs
                    hanging_logs = OperatorLog.query.filter(
                        OperatorLog.operator_session_id == old_session.id,
                        OperatorLog.current_status.notin_(['lpi_completed', 'admin_closed'])
                    ).all()
                    
                    for log in hanging_logs:
                        log.current_status = 'admin_closed'
                        log.notes = (log.notes or "") + f"\nLog auto-closed due to new operator login at {datetime.now(timezone.utc)}."
                
                db.session.commit()

                # Create new session
                new_op_session = OperatorSession(operator_name=operator_name, machine_id=machine.id, shift=shift)
                db.session.add(new_op_session)
                db.session.commit()

                session['active_role'] = 'operator' 
                session['operator_session_id'] = new_op_session.id
                session['operator_name'] = operator_name
                session['machine_name'] = machine_name 
                session['shift'] = shift  # Add shift to session

                # Restore previous session state
                previous_state = restore_operator_session(operator_name, machine_name)
                if previous_state:
                    session['current_drawing_id'] = previous_state['drawing_id']
                    flash(f'Previous session state restored. Last drawing had {previous_state["completed_quantity"]}/{previous_state["planned_quantity"]} parts completed.', 'info')
                
                flash(f'Welcome {operator_name}! Logged in on {machine_name}, Shift {shift}.', 'success')
                
                if machine_name == 'Leadwell-1':
                    return redirect(url_for('operator_panel_leadwell1'))
                elif machine_name == 'Leadwell-2':
                    return redirect(url_for('operator_panel_leadwell2'))
                else:
                    flash('Currently only Leadwell-1 and Leadwell-2 machines are supported.', 'warning')
                    return redirect(url_for('operator_login'))
    
    return render_template('operator_login.html', machine_choices=get_machine_choices())

@app.route('/operator_logout', methods=['POST'])
def operator_logout():
    # The OperatorSession DB update is still important
    operator_session_id = session.get('operator_session_id')
    if operator_session_id:
        op_session_db = db.session.get(OperatorSession, operator_session_id) # Corrected from query.get
        if op_session_db and op_session_db.is_active:
            op_session_db.is_active = False
            op_session_db.logout_time = datetime.now(timezone.utc)
            db.session.commit()

    clear_user_session() # Unified session clearing

    flash('You have been logged out from Operator station.', 'info')
    return redirect(url_for('operator_login'))

@app.route('/operator/leadwell1', methods=['GET', 'POST'])
def operator_panel_leadwell1():
    if session.get('active_role') != 'operator' or session.get('machine_name') != 'Leadwell-1':
        flash('Access denied. Please login as operator for Leadwell-1', 'danger')
        return redirect(url_for('operator_login'))
    return operator_panel_common('Leadwell-1', 'operator_leadwell1.html')

@app.route('/operator/leadwell2', methods=['GET', 'POST'])
def operator_panel_leadwell2():
    if session.get('active_role') != 'operator' or session.get('machine_name') != 'Leadwell-2':
        flash('Access denied. Please login as operator for Leadwell-2', 'danger')
        return redirect(url_for('operator_login'))
    return operator_panel_common('Leadwell-2', 'operator_leadwell2.html')

def get_redirect_url(machine_name):
    if machine_name == 'Leadwell-1':
        return url_for('operator_panel_leadwell1')
    elif machine_name == 'Leadwell-2':
        return url_for('operator_panel_leadwell2')
    else:
        # For now, redirect to login if it's not a Leadwell machine
        flash('Invalid machine type. Please login again.', 'danger')
        return url_for('operator_login')

def operator_panel_common(machine_name, template_name):
    """Shared logic for both operator panels"""
    current_log = OperatorLog.query.get(session.get('current_operator_log_id'))
    active_drawing = MachineDrawing.query.get(session.get('current_drawing_id'))
    operator_session = OperatorSession.query.get(session.get('operator_session_id'))
    approved_rework = ReworkQueue.query.filter_by(status='manager_approved').all()
    current_machine_obj = Machine.query.filter_by(name=machine_name).first()  # <-- Add this
    
    # Get active logs for the current operator session
    active_logs = OperatorLog.query.filter_by(
        operator_session_id=operator_session.id
    ).filter(
        OperatorLog.current_status.in_(['setup_started', 'setup_done', 'cycle_started', 'cycle_paused', 'fpi_passed_ready_for_cycle'])
    ).all() if operator_session else []
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'select_drawing_and_start_session':
            drawing_number = request.form.get('drawing_number_input')
            if not drawing_number:
                flash('Please enter a drawing number', 'warning')
                return redirect(url_for(f'operator_panel_{machine_name.lower().replace("-","")}'))
            
            drawing = MachineDrawing.query.filter_by(drawing_number=drawing_number).first()
            if not drawing:
                flash(f'Drawing number {drawing_number} not found', 'danger')
                return redirect(url_for(f'operator_panel_{machine_name.lower().replace("-","")}'))
            
            # Check if there's an active log for this drawing
            active_log = OperatorLog.query.filter_by(
                drawing_id=drawing.id,
                operator_session_id=operator_session.id
            ).filter(
                OperatorLog.current_status.in_(['setup_started', 'setup_done', 'cycle_started', 'cycle_paused', 'fpi_passed_ready_for_cycle'])
            ).first()
            
            if active_log:
                session['current_operator_log_id'] = active_log.id
                session['current_drawing_id'] = drawing.id
                flash(f'Resumed active session for drawing {drawing_number}', 'info')
            else:
                session['current_operator_log_id'] = None  # Allow setup for new drawing
                session['current_drawing_id'] = drawing.id
                flash(f'Selected drawing {drawing_number}', 'success')
            
            return redirect(url_for(f'operator_panel_{machine_name.lower().replace("-","")}'))
            
        elif action == 'start_setup' and active_drawing:
            # Get the end product to get planned quantity
            end_product = active_drawing.end_product_rel
            if not end_product:
                flash('No end product found for this drawing', 'danger')
                return redirect(url_for(f'operator_panel_{machine_name.lower().replace("-","")}'))

            new_log = OperatorLog(
                operator_session_id=operator_session.id,
                drawing_id=active_drawing.id,
                end_product_sap_id=active_drawing.sap_id,
                current_status='setup_started',
                setup_start_time=datetime.now(timezone.utc),
                run_planned_quantity=end_product.quantity,  # Set planned quantity from end product
                run_completed_quantity=0,  # Initialize completed quantity
                fpi_status='pending',  # Initialize FPI status
                production_hold_fpi=True  # Hold production until FPI
            )
            db.session.add(new_log)
            db.session.commit()
            session['current_operator_log_id'] = new_log.id
            flash('Setup started successfully', 'success')
            return redirect(url_for(f'operator_panel_{machine_name.lower().replace("-","")}'))
            
        elif action == 'setup_done' and current_log:
            current_log.setup_end_time = datetime.now(timezone.utc)
            current_log.current_status = 'setup_done'
            db.session.commit()
            flash('Setup completed', 'success')
            return redirect(url_for(f'operator_panel_{machine_name.lower().replace("-","")}'))
            
        elif action == 'cycle_start' and current_log:
            # Only allow cycle start if:
            # 1. Setup is done and no FPI required yet (first cycle)
            # 2. Setup is done and FPI is passed
            # 3. Cycle was paused
            if current_log.current_status in ['setup_done', 'fpi_passed_ready_for_cycle', 'cycle_paused']:
                current_log.current_status = 'cycle_started'
                if not current_log.first_cycle_start_time:
                    current_log.first_cycle_start_time = datetime.now(timezone.utc)
                db.session.commit()
                flash('Cycle started', 'success')
            else:
                flash('Cannot start cycle in current state', 'warning')
            return redirect(url_for(f'operator_panel_{machine_name.lower().replace("-","")}'))

        elif action == 'cycle_complete' and current_log:
            if current_log.current_status == 'cycle_started':
                # Increment completed quantity
                current_log.run_completed_quantity = (current_log.run_completed_quantity or 0) + 1
                current_log.last_cycle_end_time = datetime.now(timezone.utc)
                
                # Determine next status based on conditions
                if current_log.run_completed_quantity == 1:
                    # First piece needs FPI
                    current_log.current_status = 'cycle_completed_pending_fpi'
                    current_log.fpi_status = 'pending'
                    current_log.production_hold_fpi = True
                elif current_log.run_planned_quantity and current_log.run_completed_quantity >= current_log.run_planned_quantity:
                    # Reached planned quantity, needs LPI
                    current_log.current_status = 'cycle_completed_pending_lpi'
                    current_log.lpi_status = 'pending'
                else:
                    # Normal cycle completion, pause for next cycle
                    current_log.current_status = 'cycle_paused'
                
                db.session.commit()
                flash('Cycle completed.', 'success')
            else:
                flash('Cycle must be started first.', 'warning')
            return redirect(url_for(f'operator_panel_{machine_name.lower().replace("-","")}'))

        elif action == 'cycle_pause' and current_log:
            if current_log.current_status == 'cycle_started':
                current_log.current_status = 'cycle_paused'
                db.session.commit()
                flash('Cycle paused.', 'info')
            else:
                flash('No active cycle to pause.', 'warning')
            return redirect(url_for(f'operator_panel_{machine_name.lower().replace("-","")}'))

        elif action == 'cancel_current_drawing_log' and current_log:
            current_log.current_status = 'admin_closed'
            db.session.commit()
            session.pop('current_operator_log_id', None)  # Ensure session state is cleared
            flash('Current log cancelled.', 'info')
            return redirect(url_for(f'operator_panel_{machine_name.lower().replace("-","")}'))
    
    return render_template(template_name,
        operator_name=session.get('operator_name'),
        machine_name=machine_name,
        current_log=current_log,
        active_drawing=active_drawing,
        approved_rework=approved_rework,
        active_logs=active_logs,  # Add active_logs to template context
        now=datetime.now(timezone.utc),
        current_machine_obj=current_machine_obj  # Pass machine object to template
    )

# --- QUALITY ---
@app.route('/quality', methods=['GET', 'POST'])
def quality_dashboard():
    if session.get('active_role') != 'quality':
        flash('Access denied. Please login as Quality Inspector.', 'danger')
        return redirect(url_for('login_general'))

    # Configure session to be permanent and set a long expiry
    session.permanent = True
    app.permanent_session_lifetime = timedelta(days=30)  # Set session to last 30 days

    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'set_inspector_name':
            inspector_name = request.form.get('inspector_name', '').strip()
            if inspector_name:
                session['quality_inspector_name'] = inspector_name
                # Restore previous quality session state
                previous_state = restore_quality_session(inspector_name)
                if previous_state and previous_state['recent_checks']:
                    recent_checks_info = previous_state['recent_checks']
                    flash(f'Welcome back! You have performed {len(recent_checks_info)} recent quality checks.', 'info')
                flash('Inspector name set successfully.', 'success')
            else:
                flash('Inspector name cannot be empty.', 'warning')
            return redirect(url_for('quality_dashboard'))

        if action == 'update_inspector_name':
            inspector_name = request.form.get('inspector_name', '').strip()
            if inspector_name:
                session['quality_inspector_name'] = inspector_name
                flash('Inspector name updated successfully.', 'success')
            else:
                flash('Inspector name cannot be empty.', 'warning')
            return redirect(url_for('quality_dashboard'))

        # For all other actions, ensure inspector name is set
        if not session.get('quality_inspector_name'):
            flash('Please set your inspector name first.', 'warning')
            return redirect(url_for('quality_dashboard'))
        
        # Handle the new simplified quality check form
        if action == 'simple_quality_check':
            drawing_number = request.form.get('drawing_number', '').strip()
            check_type = request.form.get('check_type')  # FPI or LPI
            result = request.form.get('result')  # pass, rework, or reject
            rejection_reason = request.form.get('rejection_reason', '').strip()
            log_id = request.form.get('log_id')  # May be provided if clicked from table
            
            # Validate inputs
            if not drawing_number:
                flash('Drawing number is required.', 'danger')
                return redirect(url_for('quality_dashboard'))
                
            if not check_type or check_type not in ['FPI', 'LPI']:
                flash('Valid check type (FPI or LPI) is required.', 'danger')
                return redirect(url_for('quality_dashboard'))
                
            if not result or result not in ['pass', 'rework', 'reject']:
                flash('Valid result (pass, rework, or reject) is required.', 'danger')
                return redirect(url_for('quality_dashboard'))
            
            # If log_id is provided, use that specific log
            if log_id:
                op_log_to_inspect = OperatorLog.query.get(log_id)
                if not op_log_to_inspect:
                    flash('Operator log not found.', 'danger')
                    return redirect(url_for('quality_dashboard'))
                    
                # Verify the drawing number matches
                if op_log_to_inspect.drawing_rel and op_log_to_inspect.drawing_rel.drawing_number != drawing_number:
                    flash(f'Drawing number mismatch. Expected {op_log_to_inspect.drawing_rel.drawing_number}, got {drawing_number}.', 'danger')
                    return redirect(url_for('quality_dashboard'))
                    
                # Verify the log is in the correct state for the check type
                if check_type == 'FPI' and op_log_to_inspect.current_status != 'cycle_completed_pending_fpi':
                    flash('This log is not pending FPI.', 'warning')
                    return redirect(url_for('quality_dashboard'))
                elif check_type == 'LPI' and op_log_to_inspect.current_status != 'cycle_completed_pending_lpi':
                    flash('This log is not pending LPI.', 'warning')
                    return redirect(url_for('quality_dashboard'))
            else:
                # No log_id provided, find a matching log based on drawing number and check type
                drawing = MachineDrawing.query.filter_by(drawing_number=drawing_number).first()
                if not drawing:
                    flash(f'Drawing number {drawing_number} not found.', 'danger')
                    return redirect(url_for('quality_dashboard'))
                
                if check_type == 'FPI':
                    op_log_to_inspect = OperatorLog.query.filter_by(
                        drawing_id=drawing.id,
                        current_status='cycle_completed_pending_fpi'
                    ).order_by(OperatorLog.created_at.desc()).first()
                else:  # LPI
                    op_log_to_inspect = OperatorLog.query.filter_by(
                        drawing_id=drawing.id,
                        current_status='cycle_completed_pending_lpi'
                    ).order_by(OperatorLog.created_at.desc()).first()
                
                if not op_log_to_inspect:
                    flash(f'No pending {check_type} found for drawing {drawing_number}.', 'warning')
                    return redirect(url_for('quality_dashboard'))
            
            # Process based on check type
            if check_type == 'FPI':
                # Create quality check record
                new_qc_record = QualityCheck(
                    operator_log_id=op_log_to_inspect.id,
                    inspector_name=session.get('quality_inspector_name'),
                    check_type='FPI',
                    result=result,
                    rejection_reason=rejection_reason if result in ['reject', 'rework'] else None
                )
                db.session.add(new_qc_record)
                db.session.flush()

                if result == 'pass':
                    op_log_to_inspect.fpi_status = 'pass'
                    op_log_to_inspect.production_hold_fpi = False
                    op_log_to_inspect.current_status = 'fpi_passed_ready_for_cycle'
                    flash('FPI passed. Operator can continue production.', 'success')

                elif result == 'reject':
                    op_log_to_inspect.fpi_status = 'fail'
                    op_log_to_inspect.production_hold_fpi = True
                    op_log_to_inspect.current_status = 'fpi_failed_setup_pending'
                    op_log_to_inspect.run_rejected_quantity_fpi = (op_log_to_inspect.run_rejected_quantity_fpi or 0) + 1

                    # Create scrap record for rejected FPI
                    scrap_record = ScrapLog(
                        drawing_id=op_log_to_inspect.drawing_id,
                        quantity_scrapped=1,
                        reason=f"FPI Rejected: {rejection_reason}",
                        scrapped_at=datetime.now(timezone.utc),
                        scrapped_by=session.get('quality_inspector_name'),
                        operator_log_id=op_log_to_inspect.id,
                        originating_quality_check_id=new_qc_record.id
                    )
                    db.session.add(scrap_record)
                    flash('FPI failed. Parts marked as scrap.', 'warning')

                elif result == 'rework':
                    op_log_to_inspect.fpi_status = 'rework'
                    op_log_to_inspect.production_hold_fpi = True
                    op_log_to_inspect.current_status = 'fpi_failed_setup_pending'
                    op_log_to_inspect.run_rework_quantity_fpi = (op_log_to_inspect.run_rework_quantity_fpi or 0) + 1
                    db.session.flush()

                    # Create rework queue item
                    rework_item = ReworkQueue(
                        source_operator_log_id=op_log_to_inspect.id,
                        originating_quality_check_id=new_qc_record.id,
                        drawing_id=op_log_to_inspect.drawing_id,
                        quantity_to_rework=1,
                        rejection_reason=rejection_reason,
                        status='pending_manager_approval'  # Explicitly set status
                    )
                    db.session.add(rework_item)
                    flash('FPI failed. Parts sent for rework approval.', 'warning')
                
            else:  # LPI
                # Get quantities for LPI
                quantity_inspected = request.form.get('quantity_inspected', type=int, default=1)
                quantity_rejected = request.form.get('quantity_rejected', type=int, default=0)
                quantity_to_rework = request.form.get('quantity_to_rework', type=int, default=0)
                
                # Validate quantities
                if quantity_inspected > op_log_to_inspect.run_completed_quantity:
                    flash('Cannot inspect more parts than were produced.', 'warning')
                    return redirect(url_for('quality_dashboard'))

                if quantity_rejected and quantity_rejected > quantity_inspected:
                    flash('Cannot reject more parts than were inspected.', 'warning')
                    return redirect(url_for('quality_dashboard'))

                if quantity_to_rework and quantity_to_rework > quantity_inspected:
                    flash('Cannot rework more parts than were inspected.', 'warning')
                    return redirect(url_for('quality_dashboard'))

                if quantity_rejected and quantity_to_rework and (quantity_rejected + quantity_to_rework) > quantity_inspected:
                    flash('Total of rejected and rework parts cannot exceed inspected quantity.', 'warning')
                    return redirect(url_for('quality_dashboard'))
                
                # Create quality check record
                new_qc_record = QualityCheck(
                    operator_log_id=op_log_to_inspect.id,
                    inspector_name=session.get('quality_inspector_name'),
                    check_type='LPI',
                    result=result,
                    rejection_reason=rejection_reason if result in ['reject', 'rework'] else None,
                    lpi_quantity_inspected=quantity_inspected,
                    lpi_quantity_rejected=quantity_rejected,
                    lpi_quantity_to_rework=quantity_to_rework
                )
                db.session.add(new_qc_record)
                db.session.flush()

                if result == 'pass':
                    op_log_to_inspect.lpi_status = 'pass'
                    op_log_to_inspect.current_status = 'lpi_completed'
                    flash('LPI passed. Production cycle complete.', 'success')

                elif result == 'reject':
                    op_log_to_inspect.lpi_status = 'fail'
                    op_log_to_inspect.current_status = 'lpi_completed'  # Still complete, just with rejects
                    op_log_to_inspect.run_rejected_quantity_lpi = quantity_rejected

                    if quantity_rejected > 0:
                        # Create scrap record for rejected parts
                        scrap_record = ScrapLog(
                            drawing_id=op_log_to_inspect.drawing_id,
                            quantity_scrapped=quantity_rejected,
                            reason=f"LPI Rejected: {rejection_reason}",
                            scrapped_at=datetime.now(timezone.utc),
                            scrapped_by=session.get('quality_inspector_name'),
                            operator_log_id=op_log_to_inspect.id,
                            originating_quality_check_id=new_qc_record.id
                        )
                        db.session.add(scrap_record)

                    flash(f'LPI completed. {quantity_rejected} parts marked as scrap.', 'warning')

                elif result == 'rework':
                    op_log_to_inspect.lpi_status = 'rework'
                    op_log_to_inspect.current_status = 'lpi_completed'  # Still complete, parts going to rework
                    op_log_to_inspect.run_rework_quantity_lpi = quantity_to_rework

                    if quantity_rejected > 0:
                        # Create scrap record for rejected parts
                        scrap_record = ScrapLog(
                            drawing_id=op_log_to_inspect.drawing_id,
                            quantity_scrapped=quantity_rejected,
                            reason=f"LPI Rejected: {rejection_reason}",
                            scrapped_at=datetime.now(timezone.utc),
                            scrapped_by=session.get('quality_inspector_name'),
                            operator_log_id=op_log_to_inspect.id,
                            originating_quality_check_id=new_qc_record.id
                        )
                        db.session.add(scrap_record)

                    if quantity_to_rework > 0:
                        # Create rework queue item
                        rework_item = ReworkQueue(
                            source_operator_log_id=op_log_to_inspect.id,
                            originating_quality_check_id=new_qc_record.id,
                            drawing_id=op_log_to_inspect.drawing_id,
                            quantity_to_rework=quantity_to_rework,
                            rejection_reason=rejection_reason,
                            status='pending_manager_approval'  # Explicitly set status
                        )
                        db.session.add(rework_item)

                    flash(f'LPI completed. {quantity_rejected} parts scrapped, {quantity_to_rework} parts sent for rework approval.', 'warning')
            
            db.session.commit()
            return redirect(url_for('quality_dashboard'))
        
        if action == 'submit_fpi':
            log_id = request.form.get('log_id')
            result = request.form.get('result')
            rejection_reason = request.form.get('rejection_reason', '').strip()
            
            if not log_id or not result:
                flash('Log ID and result are required.', 'danger')
                return redirect(url_for('quality_dashboard'))
            
            op_log_to_inspect = OperatorLog.query.get(log_id)
            if not op_log_to_inspect:
                flash('Operator log not found.', 'danger')
                return redirect(url_for('quality_dashboard'))

            if op_log_to_inspect.current_status != 'cycle_completed_pending_fpi':
                flash('This log is not pending FPI.', 'warning')
                return redirect(url_for('quality_dashboard'))

            # Create quality check record
            new_qc_record = QualityCheck(
                operator_log_id=op_log_to_inspect.id,
                inspector_name=session.get('quality_inspector_name'),
                check_type='FPI',
                result=result,
                rejection_reason=rejection_reason if result in ['reject', 'rework'] else None
            )
            db.session.add(new_qc_record)
            db.session.flush()

            if result == 'pass':
                op_log_to_inspect.fpi_status = 'pass'
                op_log_to_inspect.production_hold_fpi = False
                op_log_to_inspect.current_status = 'fpi_passed_ready_for_cycle'
                flash('FPI passed. Operator can continue production.', 'success')

            elif result == 'reject':
                op_log_to_inspect.fpi_status = 'fail'
                op_log_to_inspect.production_hold_fpi = True
                op_log_to_inspect.current_status = 'fpi_failed_setup_pending'
                op_log_to_inspect.run_rejected_quantity_fpi = (op_log_to_inspect.run_rejected_quantity_fpi or 0) + 1

                # Create scrap record for rejected FPI
                scrap_record = ScrapLog(
                    drawing_id=op_log_to_inspect.drawing_id,
                    quantity_scrapped=1,
                    reason=f"FPI Rejected: {rejection_reason}",
                    scrapped_at=datetime.now(timezone.utc),
                    scrapped_by=session.get('quality_inspector_name'),
                    operator_log_id=op_log_to_inspect.id,
                    originating_quality_check_id=new_qc_record.id
                )
                db.session.add(scrap_record)
                flash('FPI failed. Parts marked as scrap.', 'warning')

            elif result == 'rework':
                op_log_to_inspect.fpi_status = 'rework'
                op_log_to_inspect.production_hold_fpi = True
                op_log_to_inspect.current_status = 'fpi_failed_setup_pending'
                op_log_to_inspect.run_rework_quantity_fpi = (op_log_to_inspect.run_rework_quantity_fpi or 0) + 1
                db.session.flush()

                # Create rework queue item
                rework_item = ReworkQueue(
                    source_operator_log_id=op_log_to_inspect.id,
                    originating_quality_check_id=new_qc_record.id,
                    drawing_id=op_log_to_inspect.drawing_id,
                    quantity_to_rework=1,
                    rejection_reason=rejection_reason,
                    status='pending_manager_approval'  # Explicitly set status
                )
                db.session.add(rework_item)
                flash('FPI failed. Parts sent for rework approval.', 'warning')

            db.session.commit()
            return redirect(url_for('quality_dashboard'))

        elif action == 'submit_lpi':
            # Similar structure to submit_fpi but for LPI
            log_id = request.form.get('log_id')
            result = request.form.get('result')
            rejection_reason = request.form.get('rejection_reason', '').strip()
            quantity_inspected = request.form.get('quantity_inspected', type=int)
            quantity_rejected = request.form.get('quantity_rejected', type=int, default=0)
            quantity_to_rework = request.form.get('quantity_to_rework', type=int, default=0)
            
            if not all([log_id, result, quantity_inspected]):
                flash('Log ID, result, and quantity inspected are required.', 'danger')
                return redirect(url_for('quality_dashboard'))
            
            op_log_to_inspect = OperatorLog.query.get(log_id)
            if not op_log_to_inspect:
                flash('Operator log not found.', 'danger')
                return redirect(url_for('quality_dashboard'))

            if op_log_to_inspect.current_status != 'cycle_completed_pending_lpi':
                flash('This log is not pending LPI.', 'warning')
                return redirect(url_for('quality_dashboard'))

            # Validate quantities
            if quantity_inspected > op_log_to_inspect.run_completed_quantity:
                flash('Cannot inspect more parts than were produced.', 'warning')
                return redirect(url_for('quality_dashboard'))

            if quantity_rejected and quantity_rejected > quantity_inspected:
                flash('Cannot reject more parts than were inspected.', 'warning')
                return redirect(url_for('quality_dashboard'))

            if quantity_to_rework and quantity_to_rework > quantity_inspected:
                flash('Cannot rework more parts than were inspected.', 'warning')
                return redirect(url_for('quality_dashboard'))

            if quantity_rejected and quantity_to_rework and (quantity_rejected + quantity_to_rework) > quantity_inspected:
                flash('Total of rejected and rework parts cannot exceed inspected quantity.', 'warning')
                return redirect(url_for('quality_dashboard'))

            # Create quality check record
            new_qc_record = QualityCheck(
                operator_log_id=op_log_to_inspect.id,
                inspector_name=session.get('quality_inspector_name'),
                check_type='LPI',
                result=result,
                rejection_reason=rejection_reason if result in ['reject', 'rework'] else None,
                lpi_quantity_inspected=quantity_inspected,
                lpi_quantity_rejected=quantity_rejected,
                lpi_quantity_to_rework=quantity_to_rework
            )
            db.session.add(new_qc_record)
            db.session.flush()

            if result == 'pass':
                op_log_to_inspect.lpi_status = 'pass'
                op_log_to_inspect.current_status = 'lpi_completed'
                flash('LPI passed. Production cycle complete.', 'success')

            elif result == 'reject':
                op_log_to_inspect.lpi_status = 'fail'
                op_log_to_inspect.current_status = 'lpi_completed'  # Still complete, just with rejects
                op_log_to_inspect.run_rejected_quantity_lpi = quantity_rejected

                if quantity_rejected > 0:
                    # Create scrap record for rejected parts
                    scrap_record = ScrapLog(
                        drawing_id=op_log_to_inspect.drawing_id,
                        quantity_scrapped=quantity_rejected,
                        reason=f"LPI Rejected: {rejection_reason}",
                        scrapped_at=datetime.now(timezone.utc),
                        scrapped_by=session.get('quality_inspector_name'),
                        operator_log_id=op_log_to_inspect.id,
                        originating_quality_check_id=new_qc_record.id
                    )
                    db.session.add(scrap_record)

                flash(f'LPI completed. {quantity_rejected} parts marked as scrap.', 'warning')

            elif result == 'rework':
                op_log_to_inspect.lpi_status = 'rework'
                op_log_to_inspect.current_status = 'lpi_completed'  # Still complete, parts going to rework
                op_log_to_inspect.run_rework_quantity_lpi = quantity_to_rework

                if quantity_rejected > 0:
                    # Create scrap record for rejected parts
                    scrap_record = ScrapLog(
                        drawing_id=op_log_to_inspect.drawing_id,
                        quantity_scrapped=quantity_rejected,
                        reason=f"LPI Rejected: {rejection_reason}",
                        scrapped_at=datetime.now(timezone.utc),
                        scrapped_by=session.get('quality_inspector_name'),
                        operator_log_id=op_log_to_inspect.id,
                        originating_quality_check_id=new_qc_record.id
                    )
                    db.session.add(scrap_record)

                if quantity_to_rework > 0:
                    # Create rework queue item
                    rework_item = ReworkQueue(
                        source_operator_log_id=op_log_to_inspect.id,
                        originating_quality_check_id=new_qc_record.id,
                        drawing_id=op_log_to_inspect.drawing_id,
                        quantity_to_rework=quantity_to_rework,
                        rejection_reason=rejection_reason,
                        status='pending_manager_approval'  # Explicitly set status
                    )
                    db.session.add(rework_item)

                flash(f'LPI completed. {quantity_rejected} parts scrapped, {quantity_to_rework} parts sent for rework approval.', 'warning')

            db.session.commit()
            return redirect(url_for('quality_dashboard'))

    # GET request - prepare data for template
    inspector_name = session.get('quality_inspector_name')
    
    # If no inspector name in session, try to restore from previous quality checks
    if not inspector_name:
        # Get the most recent quality check to find the last inspector
        last_check = QualityCheck.query.order_by(QualityCheck.timestamp.desc()).first()
        if last_check:
            inspector_name = last_check.inspector_name
            session['quality_inspector_name'] = inspector_name
            flash(f'Welcome back {inspector_name}! Your previous inspector name has been restored.', 'info')

    def serialize_log(log):
        return {
            "id": log.id,
            "drawing_rel": {
                "drawing_number": log.drawing_rel.drawing_number if log.drawing_rel else "N/A"
            } if hasattr(log, "drawing_rel") and log.drawing_rel else None,
            "operator_session": {
                "operator_name": log.operator_session.operator_name if log.operator_session else "N/A",
                "machine_rel": {
                    "name": log.operator_session.machine_rel.name if log.operator_session and log.operator_session.machine_rel else "N/A"
                } if log.operator_session and hasattr(log.operator_session, "machine_rel") and log.operator_session.machine_rel else None
            } if hasattr(log, "operator_session") and log.operator_session else None,
            "current_status": log.current_status,
            "run_completed_quantity": log.run_completed_quantity,
            "run_planned_quantity": log.run_planned_quantity,
            "fpi_status": log.fpi_status,
            "lpi_status": log.lpi_status,
        }

    pending_fpi_logs = OperatorLog.query.join(
        OperatorSession
    ).join(
        MachineDrawing
    ).filter(
        OperatorLog.current_status == 'cycle_completed_pending_fpi'
    ).order_by(
        OperatorLog.created_at.desc()
    ).all()

    pending_lpi_logs = OperatorLog.query.join(
        OperatorSession
    ).join(
        MachineDrawing
    ).filter(
        OperatorLog.current_status == 'cycle_completed_pending_lpi'
    ).order_by(
        OperatorLog.created_at.desc()
    ).all()

    logs_for_js = [serialize_log(log) for log in pending_fpi_logs + pending_lpi_logs]

    return render_template(
        'quality.html',
        inspector_name=inspector_name,
        pending_fpi_logs=pending_fpi_logs,
        pending_lpi_logs=pending_lpi_logs,
        logs_for_js=logs_for_js
    )

# --- DIGITAL TWIN (Basic Placeholder) ---
@app.route('/digital_twin')
def digital_twin_dashboard():
    print(f"DEBUG: Session at start of /digital_twin: {dict(session)}")

    active_user_role = session.get('active_role')
    if not active_user_role:
        flash('Access denied. Please login.', 'danger')
        return redirect(url_for('login_general'))
    if active_user_role == 'operator':
        machine_name = session.get('machine_name')
        if machine_name == 'Leadwell-1':
            flash('Operators do not have access to the Digital Twin dashboard.', 'warning')
            return redirect(url_for('operator_panel_leadwell1'))
        elif machine_name == 'Leadwell-2':
            flash('Operators do not have access to the Digital Twin dashboard.', 'warning')
            return redirect(url_for('operator_panel_leadwell2'))
        else:
            flash('Invalid machine type or session. Please login again.', 'warning')
            return redirect(url_for('operator_login'))

    machines = Machine.query.order_by(Machine.name).all()
    machine_details_list = []
    now_utc_timestamp = datetime.now(timezone.utc)

    for machine in machines:
        details = {
            'name': machine.name,
            'status': machine.status,
            'operator': 'N/A',
            'drawing': 'N/A',
            'planned': 0,
            'completed': 0,
            'rejected': 0,
            'rework': 0,
            'quality_pending': 'None',
            'oee': {'availability': 0.0, 'performance': 0.0, 'quality': 0.0, 'overall': 0.0},
            'actual_setup_time_display': 'N/A', # For displaying actual ST
            'avg_actual_cycle_time_display': 'N/A', # For displaying actual CT (approx)
            'std_setup_time': 0,
            'std_cycle_time': 0
        }

        active_op_session = OperatorSession.query.filter_by(machine_id=machine.id, is_active=True).first()
        current_log_on_machine = None

        if active_op_session:
            details['operator'] = active_op_session.operator_name
            current_log_on_machine = OperatorLog.query.filter(
                OperatorLog.operator_session_id == active_op_session.id,
                OperatorLog.current_status.notin_(['lpi_completed', 'admin_closed'])
            ).order_by(OperatorLog.created_at.desc()).first()

        if current_log_on_machine:
            details['drawing'] = current_log_on_machine.drawing_rel.drawing_number if current_log_on_machine.drawing_rel else "Unknown Drawing"
            details['planned'] = current_log_on_machine.run_planned_quantity or 0
            details['completed'] = current_log_on_machine.run_completed_quantity or 0
            details['rejected'] = (current_log_on_machine.run_rejected_quantity_fpi or 0) + \
                                  (current_log_on_machine.run_rejected_quantity_lpi or 0)
            details['rework'] = (current_log_on_machine.run_rework_quantity_fpi or 0) + \
                                (current_log_on_machine.run_rework_quantity_lpi or 0)

            if current_log_on_machine.current_status == 'cycle_completed_pending_fpi':
                details['quality_pending'] = 'Awaiting FPI'
            elif current_log_on_machine.current_status == 'cycle_completed_pending_lpi':
                details['quality_pending'] = 'Awaiting LPI'
            elif current_log_on_machine.fpi_status == 'pending' and (current_log_on_machine.run_completed_quantity or 0) > 0 and current_log_on_machine.current_status != 'fpi_passed_ready_for_cycle':
                details['quality_pending'] = 'Awaiting FPI (check status)'
            elif current_log_on_machine.lpi_status == 'pending' and (current_log_on_machine.run_completed_quantity or 0) == (current_log_on_machine.run_planned_quantity or 0) and details['planned'] > 0 :
                details['quality_pending'] = 'Awaiting LPI (check status)'
            
            std_setup_time = 0
            std_cycle_time = 0
            if current_log_on_machine.drawing_rel and current_log_on_machine.drawing_rel.end_product_rel:
                std_setup_time = current_log_on_machine.drawing_rel.end_product_rel.setup_time_std or 0
                std_cycle_time = current_log_on_machine.drawing_rel.end_product_rel.cycle_time_std or 0
            
            # Add these to details dict for template access
            details['std_setup_time'] = std_setup_time
            details['std_cycle_time'] = std_cycle_time

            # --- OEE Availability ---
            if machine.status == 'in_use':
                if current_log_on_machine:
                    active_cycling_states = ['cycle_started', 'fpi_passed_ready_for_cycle']
                    setup_or_qc_states = ['setup_started', 'setup_done', 
                                          'cycle_completed_pending_fpi', 'cycle_completed_pending_lpi', 
                                          'fpi_failed_setup_pending']
                    if current_log_on_machine.current_status in active_cycling_states:
                        details['oee']['availability'] = 95.0
                    elif current_log_on_machine.current_status == 'cycle_paused':
                        details['oee']['availability'] = 80.0 
                    elif current_log_on_machine.current_status in setup_or_qc_states:
                        details['oee']['availability'] = 75.0
                    else: 
                        details['oee']['availability'] = 70.0
                else: 
                    details['oee']['availability'] = 50.0
            elif machine.status == 'available':
                details['oee']['availability'] = 100.0
            else: # breakdown
                details['oee']['availability'] = 0.0

            # --- OEE Performance ---
            actual_total_log_duration_minutes = 0
            if current_log_on_machine.setup_start_time:
                start_time_obj = ensure_utc_aware(current_log_on_machine.setup_start_time)
                effective_end_time_obj = now_utc_timestamp # This is already aware
                
                is_log_concluded = current_log_on_machine.current_status in ['lpi_completed', 'fpi_failed_setup_pending', 'admin_closed']
                if is_log_concluded:
                    log_cycle_end_time = ensure_utc_aware(current_log_on_machine.last_cycle_end_time)
                    log_setup_end_time = ensure_utc_aware(current_log_on_machine.setup_end_time)
                    if log_cycle_end_time:
                        effective_end_time_obj = log_cycle_end_time
                    elif log_setup_end_time: # Fallback if no cycle but setup ended
                        effective_end_time_obj = log_setup_end_time
                
                # Ensure start_time_obj is not None before comparison/subtraction
                if start_time_obj and effective_end_time_obj and effective_end_time_obj > start_time_obj:
                    actual_total_log_duration_minutes = (effective_end_time_obj - start_time_obj).total_seconds() / 60

            actual_setup_minutes = 0
            log_setup_start_time_aware = ensure_utc_aware(current_log_on_machine.setup_start_time)
            log_setup_end_time_aware = ensure_utc_aware(current_log_on_machine.setup_end_time)
            if log_setup_start_time_aware and log_setup_end_time_aware:
                if log_setup_end_time_aware > log_setup_start_time_aware:
                    actual_setup_minutes = (log_setup_end_time_aware - log_setup_start_time_aware).total_seconds() / 60
                    details['actual_setup_time_display'] = f"{actual_setup_minutes:.1f} min"

            # Net time presumed to be for cycling (Total log active time - actual setup time)
            net_production_run_time_minutes = actual_total_log_duration_minutes - actual_setup_minutes
            if net_production_run_time_minutes < 0: net_production_run_time_minutes = 0 # Cannot be negative

            if details['completed'] > 0 and std_cycle_time > 0:
                ideal_cycle_time_for_completed_parts = details['completed'] * std_cycle_time
                if net_production_run_time_minutes > 0:
                    performance_val = (ideal_cycle_time_for_completed_parts / net_production_run_time_minutes) * 100
                    details['oee']['performance'] = round(min(max(performance_val, 0), 100.0), 1)
                    
                    # Approx avg actual cycle time
                    avg_ct = net_production_run_time_minutes / details['completed']
                    details['avg_actual_cycle_time_display'] = f"{avg_ct:.2f} min/pc"
                else:
                    # Made parts but no net production runtime (e.g. setup not ended, or ended after cycle_end)
                    details['oee']['performance'] = 0.0 
            elif details['completed'] == 0 and net_production_run_time_minutes > 0:
                details['oee']['performance'] = 0.0 # Time spent cycling, but no good parts
            elif std_cycle_time == 0 and details['completed'] > 0:
                details['oee']['performance'] = 0.0 # Cannot meet a zero-time standard if parts produced
            else: 
                # No parts completed and no net time spent cycling OR no standard cycle time to compare against
                details['oee']['performance'] = 100.0 
            
            # --- OEE Quality ---
            total_parts_produced_by_log = details['completed'] + details['rejected'] + details['rework']
            if total_parts_produced_by_log > 0:
                good_parts = details['completed']
                details['oee']['quality'] = round((good_parts / total_parts_produced_by_log) * 100, 1)
            else:
                details['oee']['quality'] = 100.0

            # --- Overall OEE ---  <- This whole block should align with the '--- OEE Quality ---' block's indentation
            oee_a = details['oee']['availability'] / 100.0
            oee_p = details['oee']['performance'] / 100.0
            oee_q = details['oee']['quality'] / 100.0
            details['oee']['overall'] = round(oee_a * oee_p * oee_q * 100, 1)
        
        else:  # No active operator session or no current log on machine <- This 'else' must align with 'if current_log_on_machine:'
            if machine.status == 'available':
                details['oee'].update({'availability': 100.0, 'performance': 100.0, 'quality': 100.0, 'overall': 100.0})
            elif machine.status == 'breakdown':
                details['oee'].update({'availability': 0.0, 'performance': 0.0, 'quality':0.0, 'overall': 0.0}) 
            elif machine.status == 'in_use': 
                details['oee'].update({'availability': 50.0, 'performance': 0.0, 'quality': 0.0, 'overall': 0.0})

        machine_details_list.append(details)

    return render_template('digital_twin.html', 
                           machine_data=machine_details_list, 
                           last_updated_time=now_utc_timestamp)

@app.route('/machine_report', methods=['GET'])
def machine_report():
    if 'active_role' not in session or session['active_role'] not in ['manager', 'planner', 'plant_head']:
        flash('Access denied. Only managers, planners, and plant heads can access reports.', 'danger')
        return redirect(url_for('login_general'))

    # Get date range from query parameters or default to today
    start_date = request.args.get('start_date', datetime.now(timezone.utc).date().isoformat())
    end_date = request.args.get('end_date', start_date)
    
    # Convert string dates to datetime
    start_dt = datetime.fromisoformat(start_date)
    end_dt = datetime.fromisoformat(end_date) + timedelta(days=1)  # Include full end date

    machines = Machine.query.order_by(Machine.name).all()
    report_data = []

    for machine in machines:
        # Get all operator logs for this machine in date range
        logs = OperatorLog.query.join(OperatorSession).filter(
            OperatorSession.machine_id == machine.id,
            OperatorLog.setup_start_time >= start_dt,
            OperatorLog.setup_start_time < end_dt
        ).options(
            db.joinedload(OperatorLog.drawing_rel),
            db.joinedload(OperatorLog.operator_session),
            db.joinedload(OperatorLog.quality_checks)
        ).all()

        for log in logs:
            # Calculate times
            setup_time = None
            if log.setup_start_time and log.setup_end_time:
                setup_time = (log.setup_end_time - log.setup_start_time).total_seconds() / 60

            cycle_time = None
            total_cycle_time = 0
            if log.first_cycle_start_time and log.last_cycle_end_time and log.run_completed_quantity:
                total_cycle_time = (log.last_cycle_end_time - log.first_cycle_start_time).total_seconds() / 60
                cycle_time = total_cycle_time / log.run_completed_quantity if log.run_completed_quantity > 0 else None

            # Calculate OEE components
            availability = 0
            performance = 0
            quality = 0
            oee = 0

            if log.drawing_rel and log.drawing_rel.end_product_rel:
                std_setup_time = log.drawing_rel.end_product_rel.setup_time_std or 0
                std_cycle_time = log.drawing_rel.end_product_rel.cycle_time_std or 0
                
                # Performance calculation
                if std_cycle_time > 0 and cycle_time:
                    performance = (std_cycle_time / cycle_time) * 100
                
                # Quality calculation
                total_parts = (log.run_completed_quantity or 0) + (log.run_rejected_quantity_fpi or 0) + \
                            (log.run_rejected_quantity_lpi or 0) + (log.run_rework_quantity_fpi or 0) + \
                            (log.run_rework_quantity_lpi or 0)
                if total_parts > 0:
                    quality = ((log.run_completed_quantity or 0) / total_parts) * 100

                # Availability calculation (simplified)
                if log.current_status == 'cycle_started':
                    availability = 95.0
                elif log.current_status == 'cycle_paused':
                    availability = 80.0
                elif log.current_status in ['setup_started', 'setup_done']:
                    availability = 75.0

                # Overall OEE
                oee = (availability * performance * quality) / 10000

            # Build report row matching spreadsheet format
            row = {
                'date': log.setup_start_time.date(),
                'shift': log.operator_session.shift,
                'machine': machine.name,
                'operator': log.operator_session.operator_name,
                'drawing': log.drawing_rel.drawing_number if log.drawing_rel else 'N/A',
                'tool_change': 0,  # Add if you track this
                'inspection': 0,  # Add if you track this
                'engagement': 0,  # Add if you track this
                'rework': (log.run_rework_quantity_fpi or 0) + (log.run_rework_quantity_lpi or 0),
                'minor_stoppage': 0,  # Add if you track this
                'setup_time': round(setup_time, 2) if setup_time else 0,
                'tea_break': 0,  # Add if you track this
                'tbt': 0,  # Add if you track this
                'lunch': 0,  # Add if you track this
                '5s': 0,  # Add if you track this
                'pm': 0,  # Add if you track this
                'planned_qty': log.run_planned_quantity,
                'completed_qty': log.run_completed_quantity,
                'std_setup_time': std_setup_time,
                'std_cycle_time': std_cycle_time,
                'actual_setup_time': round(setup_time, 2) if setup_time else 0,
                'actual_cycle_time': round(cycle_time, 2) if cycle_time else 0,
                'availability': round(availability, 2),
                'performance': round(performance, 2),
                'quality': round(quality, 2),
                'oee': round(oee, 2),
                'status': log.current_status,
                'quality_status': "Pending FPI" if log.current_status == 'cycle_completed_pending_fpi' \
                                else "Pending LPI" if log.current_status == 'cycle_completed_pending_lpi' \
                                else "N/A",
                'reason': '',  # Add if you track specific reasons
                'machine_power': 'ON' if log.current_status not in ['admin_closed'] else 'OFF',
                'program_issues': ''  # Add if you track programming issues
            }
            report_data.append(row)

    return render_template('machine_report.html', 
                         report_data=report_data,
                         start_date=start_date,
                         end_date=end_date)

@app.route('/machine_report/download', methods=['POST'])
def download_machine_report():
    if 'active_role' not in session or session['active_role'] not in ['manager', 'planner', 'plant_head']:
        flash('Access denied. Only managers, planners, and plant heads can access reports.', 'danger')
        return redirect(url_for('login_general'))

    # Get date range from form data
    start_date = request.form.get('start_date', datetime.now(timezone.utc).date().isoformat())
    end_date = request.form.get('end_date', start_date)
    start_dt = datetime.fromisoformat(start_date)
    end_dt = datetime.fromisoformat(end_date) + timedelta(days=1)

    machines = Machine.query.order_by(Machine.name).all()
    report_data = []

    for machine in machines:
        logs = OperatorLog.query.join(OperatorSession).filter(
            OperatorSession.machine_id == machine.id,
            OperatorLog.setup_start_time >= start_dt,
            OperatorLog.setup_start_time < end_dt
        ).options(
            db.joinedload(OperatorLog.drawing_rel),
            db.joinedload(OperatorLog.operator_session),
            db.joinedload(OperatorLog.quality_checks)
        ).all()

        for log in logs:
            setup_time = None
            if log.setup_start_time and log.setup_end_time:
                setup_time = (log.setup_end_time - log.setup_start_time).total_seconds() / 60
            cycle_time = None
            total_cycle_time = 0
            if log.first_cycle_start_time and log.last_cycle_end_time and log.run_completed_quantity:
                total_cycle_time = (log.last_cycle_end_time - log.first_cycle_start_time).total_seconds() / 60
                cycle_time = total_cycle_time / log.run_completed_quantity if log.run_completed_quantity > 0 else None
            availability = 0
            performance = 0
            quality = 0
            oee = 0
            if log.drawing_rel and log.drawing_rel.end_product_rel:
                std_setup_time = log.drawing_rel.end_product_rel.setup_time_std or 0
                std_cycle_time = log.drawing_rel.end_product_rel.cycle_time_std or 0
                if std_cycle_time > 0 and cycle_time:
                    performance = (std_cycle_time / cycle_time) * 100
                total_parts = (log.run_completed_quantity or 0) + (log.run_rejected_quantity_fpi or 0) + \
                            (log.run_rejected_quantity_lpi or 0) + (log.run_rework_quantity_fpi or 0) + \
                            (log.run_rework_quantity_lpi or 0)
                if total_parts > 0:
                    quality = ((log.run_completed_quantity or 0) / total_parts) * 100
                if log.current_status == 'cycle_started':
                    availability = 95.0
                elif log.current_status == 'cycle_paused':
                    availability = 80.0
                elif log.current_status in ['setup_started', 'setup_done']:
                    availability = 75.0
                oee = (availability * performance * quality) / 10000
            row = {
                'date': log.setup_start_time.date(),
                'shift': log.operator_session.shift,
                'machine': machine.name,
                'operator': log.operator_session.operator_name,
                'drawing': log.drawing_rel.drawing_number if log.drawing_rel else 'N/A',
                'tool_change': 0,
                'inspection': 0,
                'engagement': 0,
                'rework': (log.run_rework_quantity_fpi or 0) + (log.run_rework_quantity_lpi or 0),
                'minor_stoppage': 0,
                'setup_time': round(setup_time, 2) if setup_time else 0,
                'tea_break': 0,
                'tbt': 0,
                'lunch': 0,
                '5s': 0,
                'pm': 0,
                'planned_qty': log.run_planned_quantity,
                'completed_qty': log.run_completed_quantity,
                'std_setup_time': std_setup_time,
                'std_cycle_time': std_cycle_time,
                'actual_setup_time': round(setup_time, 2) if setup_time else 0,
                'actual_cycle_time': round(cycle_time, 2) if cycle_time else 0,
                'availability': round(availability, 2),
                'performance': round(performance, 2),
                'quality': round(quality, 2),
                'oee': round(oee, 2),
                'status': log.current_status,
                'quality_status': "Pending FPI" if log.current_status == 'cycle_completed_pending_fpi' \
                                else "Pending LPI" if log.current_status == 'cycle_completed_pending_lpi' \
                                else "N/A",
                'reason': '',
                'machine_power': 'ON' if log.current_status not in ['admin_closed'] else 'OFF',
                'program_issues': ''
            }
            report_data.append(row)

    # Explicitly set column order and names
    columns = [
        'date', 'shift', 'machine', 'operator', 'drawing', 'tool_change', 'inspection', 'engagement', 'rework',
        'minor_stoppage', 'setup_time', 'tea_break', 'tbt', 'lunch', '5s', 'pm', 'planned_qty', 'completed_qty',
        'std_setup_time', 'std_cycle_time', 'actual_setup_time', 'actual_cycle_time', 'availability', 'performance',
        'quality', 'oee', 'status', 'quality_status', 'reason', 'machine_power', 'program_issues'
    ]
    import pandas as pd
    df = pd.DataFrame(report_data, columns=columns)
    if df.empty:
        df = pd.DataFrame(columns=columns)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name='Machine Report', index=False, header=True)
    output.seek(0)
    file_name = f"machine_report_{start_date}_to_{end_date}.xlsx"
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=file_name
    )

# --- DB Initialization ---
def setup_database():
    # db.drop_all() # Use with caution - for development reset only
    db.create_all()
    
    # Pre-populate machines if they don't exist
    for machine_name, _ in get_machine_choices():
        if not Machine.query.filter_by(name=machine_name).first():
            db.session.add(Machine(name=machine_name))
        db.session.commit()
        
def restore_operator_session(operator_name, machine_name):
    """Restore operator's previous session state"""
    try:
        # Get the most recent active session for this operator on this machine
        last_session = OperatorSession.query.filter_by(
            operator_name=operator_name,
            machine_id=Machine.query.filter_by(name=machine_name).first().id
        ).order_by(OperatorSession.login_time.desc()).first()

        if last_session:
            # Get the most recent active log
            last_log = OperatorLog.query.filter_by(
                operator_session_id=last_session.id
            ).order_by(OperatorLog.created_at.desc()).first()

            if last_log:
                return {
                    'drawing_id': last_log.drawing_id,
                    'current_status': last_log.current_status,
                    'completed_quantity': last_log.run_completed_quantity,
                    'planned_quantity': last_log.run_planned_quantity
                }
    except Exception as e:
        app.logger.error(f'Error restoring operator session: {str(e)}')
    return None

def restore_quality_session(inspector_name):
    """Restore quality inspector's previous session state"""
    try:
        # Get recent quality checks by this inspector
        recent_checks = QualityCheck.query.filter_by(
            inspector_name=inspector_name
        ).order_by(QualityCheck.timestamp.desc()).limit(5).all()

        return {
            'recent_checks': [
                {
                    'drawing_number': check.operator_log_rel.drawing_rel.drawing_number,
                    'check_type': check.check_type,
                    'result': check.result,
                    'timestamp': check.timestamp
                } for check in recent_checks
            ] if recent_checks else []
        }
    except Exception as e:
        app.logger.error(f'Error restoring quality session: {str(e)}')
    return None

@app.route('/plant_head')
def plant_head_dashboard():
    if session.get('active_role') != 'plant_head':
        flash('Access denied. Please login as Plant Head.', 'danger')
        return redirect(url_for('login_general'))

    try:
        # Get all machines with their active logs
        machines = Machine.query.options(
            db.joinedload(Machine.operator_sessions)
               .joinedload(OperatorSession.operator_logs)
        ).all()

        # Calculate OEE and other metrics for each machine
        machine_metrics = []
        total_oee = 0
        
        for machine in machines:
            # Find active operator session and current log
            active_session = next((s for s in machine.operator_sessions if s.is_active), None)
            current_log = None
            
            if active_session:
                current_log = next((log for log in active_session.operator_logs 
                                   if log.current_status not in ['lpi_completed', 'admin_closed']), None)
            
            # Calculate OEE for this machine
            oee_value = 0
            first_pass_yield = 0
            rework_rate = 0
            
            if current_log:
                # Simple OEE calculation based on current log status
                availability = 95.0 if current_log.current_status == 'cycle_started' else 75.0
                
                # Calculate quality metrics
                total_parts = ((current_log.run_completed_quantity or 0) + 
                              (current_log.run_rejected_quantity_fpi or 0) + 
                              (current_log.run_rejected_quantity_lpi or 0) +
                              (current_log.run_rework_quantity_fpi or 0) + 
                              (current_log.run_rework_quantity_lpi or 0))
                
                if total_parts > 0:
                    quality = ((current_log.run_completed_quantity or 0) / total_parts) * 100
                    first_pass_yield = quality  # Simplified FPY calculation
                    rework_rate = ((current_log.run_rework_quantity_fpi or 0) + 
                                  (current_log.run_rework_quantity_lpi or 0)) / total_parts * 100
                else:
                    quality = 100.0
                    first_pass_yield = 100.0
                    rework_rate = 0.0
                
                # Performance calculation (simplified)
                performance = 80.0
                
                # Overall OEE
                oee_value = (availability * performance * quality) / 10000
            
            machine_metrics.append({
                'machine': machine,
                'oee': oee_value,
                'first_pass_yield': first_pass_yield,
                'rework_rate': rework_rate
            })
            
            total_oee += oee_value
        
        # Calculate average OEE
        average_oee = total_oee / len(machines) if machines else 0
        active_machines_count = sum(1 for m in machines if m.status == 'in_use')
        machine_utilization = round((active_machines_count / len(machines)) * 100) if machines else 0

        # Get today's date (UTC)
        today = datetime.now(timezone.utc).date()
        
        # Production stats
        todays_production_count = db.session.query(OperatorLog).filter(
            OperatorLog.setup_start_time >= today
        ).count()
        
        # Quality stats
        pending_quality_checks = OperatorLog.query.filter(
            OperatorLog.current_status.in_(['cycle_completed_pending_fpi', 'cycle_completed_pending_lpi'])
        ).count()
        rework_count = ReworkQueue.query.filter_by(status='pending_manager_approval').count()

        # Prepare quality metrics for chart
        quality_metrics = {
            'labels': [m['machine'].name for m in machine_metrics],
            'fpy_data': [m['first_pass_yield'] for m in machine_metrics],
            'rework_data': [m['rework_rate'] for m in machine_metrics]
        }

        # --- Digital Twin Summary Data ---
        production_summary = db.session.query(
            EndProduct.name,
            EndProduct.sap_id,
            EndProduct.quantity,
            db.func.sum(OperatorLog.run_completed_quantity).label('completed'),
            db.func.sum(OperatorLog.run_rejected_quantity_fpi + OperatorLog.run_rejected_quantity_lpi).label('rejected'),
            db.func.sum(OperatorLog.run_rework_quantity_fpi + OperatorLog.run_rework_quantity_lpi).label('rework')
        ).join(OperatorLog, OperatorLog.end_product_sap_id == EndProduct.sap_id, isouter=True)
        production_summary = production_summary.group_by(EndProduct.id).all()

        completed_end_products = (
            db.session.query(EndProduct)
            .outerjoin(OperatorLog, OperatorLog.end_product_sap_id == EndProduct.sap_id)
            .group_by(EndProduct.id)
            .having(db.func.coalesce(db.func.sum(OperatorLog.run_completed_quantity), 0) >= EndProduct.quantity)
            .all()
        )

        recent_quality_checks = QualityCheck.query.order_by(QualityCheck.timestamp.desc()).limit(10).all()
        recent_rework = ReworkQueue.query.order_by(ReworkQueue.created_at.desc()).limit(10).all()
        recent_scrap = ScrapLog.query.order_by(ScrapLog.scrapped_at.desc()).limit(10).all()
        digital_twin_url = url_for('digital_twin_dashboard')

        return render_template('plant_head.html',
            average_oee=average_oee,
            active_machines_count=active_machines_count,
            total_machines_count=len(machines),
            machine_utilization=machine_utilization,
            todays_production_count=todays_production_count,
            todays_target=100,  # Replace with dynamic calculation
            pending_quality_checks=pending_quality_checks,
            rework_count=rework_count,
            todays_projects=[],  # Replace with actual projects query
            quality_alerts=[],   # Replace with actual alerts query
            quality_metrics=quality_metrics,
            machine_metrics=machine_metrics,
            production_summary=production_summary,
            completed_end_products=completed_end_products,
            recent_quality_checks=recent_quality_checks,
            recent_rework=recent_rework,
            recent_scrap=recent_scrap,
            digital_twin_url=digital_twin_url
        )

    except Exception as e:
        app.logger.error(f"Error in plant_head_dashboard: {str(e)}")
        flash('Error loading dashboard data', 'danger')
        return redirect(url_for('login_general'))

# Minimal test route for session debugging
@app.route('/test_login', methods=['GET', 'POST'])
def test_login():
    if request.method == 'POST':
        session['test_user'] = request.form['username']
        print("Test login: session contents:", dict(session))
        return 'Logged in as ' + session['test_user']
    return '''
        <form method="post">
            <input name="username">
            <input type="submit">
        </form>
    '''

if __name__ == '__main__':
    with app.app_context():
        setup_database()  # Initialize database and create machines
    app.run(debug=True)
