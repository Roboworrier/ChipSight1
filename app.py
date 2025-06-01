"""
ChipSight - Digital Twin for Manufacturing
Copyright (c) 2025 Diwakar Singh. All rights reserved.
See COMPANY_LICENSE.md for license terms.

This software and its source code are the exclusive intellectual property of Diwakar Singh.
Unauthorized copying, modification, distribution, or use is strictly prohibited.
"""

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, session
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

sys.setrecursionlimit(3000)  # Increase recursion limit if needed

# Disable .env file loading
os.environ['FLASK_SKIP_DOTENV'] = '1'

# Initialize Flask app
app = Flask(__name__)

# Custom Jinja2 filter for nl2br
def nl2br_filter(value):
    if not value:
        return ""
    # Convert newlines to <br> tags
    # The input 'value' is typically a string that Jinja2 would autoescape.
    # We replace literal newlines. Markup ensures the <br> isn't escaped.
    return Markup(str(value).replace('\n', '<br>\n'))

app.jinja_env.filters['nl2br'] = nl2br_filter

# Basic configuration
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-here')  # Change this to a secure random key
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///digital_twin.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['ALLOWED_EXTENSIONS'] = {'xlsx'} # For planner and manager uploads

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
    operator_logs = relationship("OperatorLog", back_populates="operator_session_rel", cascade="all, delete-orphan")
    # The 'reported_breakdowns' relationship is now defined after MachineBreakdownLog

class OperatorLog(db.Model):
    __tablename__ = 'operator_log'
    id = db.Column(db.Integer, primary_key=True)
    operator_session_id = db.Column(db.Integer, db.ForeignKey('operator_session.id'), nullable=False)
    drawing_id = db.Column(db.Integer, db.ForeignKey('machine_drawing.id'), nullable=False)
    # Store SAP ID directly for easier querying of overall EndProduct progress
    end_product_sap_id = db.Column(db.String(50), db.ForeignKey('end_product.sap_id'), nullable=False)

    setup_start_time = db.Column(db.DateTime, nullable=True)
    setup_end_time = db.Column(db.DateTime, nullable=True)
    
    first_cycle_start_time = db.Column(db.DateTime, nullable=True) # Start time of the very first cycle for this log
    last_cycle_start_time = db.Column(db.DateTime, nullable=True)  # Start time of the most recent cycle attempt
    last_cycle_end_time = db.Column(db.DateTime, nullable=True)    # End time of the most recent completed cycle

    current_status = db.Column(db.String(50), nullable=False, default='pending_setup')
    
    run_planned_quantity = db.Column(db.Integer, default=1) # Typically 1 for FPI, or batch size for LPI relevant cycles
    run_completed_quantity = db.Column(db.Integer, default=0) # Successfully made in this log's scope
    run_rejected_quantity_fpi = db.Column(db.Integer, default=0)
    run_rejected_quantity_lpi = db.Column(db.Integer, default=0)
    run_rework_quantity_fpi = db.Column(db.Integer, default=0)
    run_rework_quantity_lpi = db.Column(db.Integer, default=0)

    fpi_status = db.Column(db.String(20), default='pending')  # pending, pass, fail, rework
    lpi_status = db.Column(db.String(20), default='pending')  # pending, pass, fail, rework (applies to batch if relevant)
    
    production_hold_fpi = db.Column(db.Boolean, default=False) # True if FPI for this drawing is needed/failed
    
    is_rework_task = db.Column(db.Boolean, default=False)
    original_operator_log_id = db.Column(db.Integer, db.ForeignKey('operator_log.id'), nullable=True) # Link if this is a rework of a previous log's part
    notes = db.Column(db.Text, nullable=True) # Notes for any specific details about the log, e.g., cancellation reason

    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))

    operator_session_rel = relationship("OperatorSession", back_populates="operator_logs")
    drawing_rel = relationship("MachineDrawing", foreign_keys=[drawing_id], back_populates="operator_logs")
    end_product_sap_id_rel = relationship("EndProduct", foreign_keys=[end_product_sap_id], back_populates="operator_logs_for_sap")
    
    quality_checks = relationship("QualityCheck", back_populates="operator_log_rel", cascade="all, delete-orphan")
    # If this log produced items for rework
    rework_items_sourced = relationship("ReworkQueue", foreign_keys='ReworkQueue.source_operator_log_id', back_populates="source_operator_log_rel")
    # If this log is an attempt to rework an item
    rework_attempt_for_queue = relationship("ReworkQueue", foreign_keys='ReworkQueue.assigned_operator_log_id', back_populates="assigned_operator_log_rel")


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
    
    operator_log_rel = relationship("OperatorLog", back_populates="quality_checks")
    # If this QC sends items to rework
    rework_items_generated = relationship("ReworkQueue", foreign_keys='ReworkQueue.originating_quality_check_id', back_populates="originating_quality_check_rel")
    # If this QC results in scrap
    scrapped_items_generated = relationship("ScrapLog", back_populates="originating_quality_check_rel")

class ReworkQueue(db.Model):
    __tablename__ = 'rework_queue'
    id = db.Column(db.Integer, primary_key=True)
    source_operator_log_id = db.Column(db.Integer, db.ForeignKey('operator_log.id'), nullable=True) # Log that produced the part(s)
    originating_quality_check_id = db.Column(db.Integer, db.ForeignKey('quality_check.id'), nullable=False) # QC that sent to rework
    drawing_id = db.Column(db.Integer, db.ForeignKey('machine_drawing.id'), nullable=False)
    
    quantity_to_rework = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(30), default='pending_manager_approval')  # pending_manager_approval, manager_approved, manager_rejected, rework_assigned, rework_in_progress, rework_completed_pending_qc, rework_qc_pass, rework_qc_fail_scrapped
    rejection_reason = db.Column(db.Text, nullable=True) # From original QC
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    
    # Manager approval fields
    manager_approved_by = db.Column(db.String(100), nullable=True)
    manager_approval_time = db.Column(db.DateTime, nullable=True)
    manager_notes = db.Column(db.Text, nullable=True)
    
    # Log for the rework attempt itself
    assigned_operator_log_id = db.Column(db.Integer, db.ForeignKey('operator_log.id'), nullable=True, unique=True) 

    source_operator_log_rel = relationship("OperatorLog", foreign_keys=[source_operator_log_id], back_populates="rework_items_sourced")
    originating_quality_check_rel = relationship("QualityCheck", foreign_keys=[originating_quality_check_id], back_populates="rework_items_generated")
    drawing_rel = relationship("MachineDrawing", foreign_keys=[drawing_id], back_populates="rework_items")
    assigned_operator_log_rel = relationship("OperatorLog", foreign_keys=[assigned_operator_log_id], back_populates="rework_attempt_for_queue")


class ScrapLog(db.Model):
    __tablename__ = 'scrap_log'
    id = db.Column(db.Integer, primary_key=True)
    originating_quality_check_id = db.Column(db.Integer, db.ForeignKey('quality_check.id'), nullable=False)
    drawing_id = db.Column(db.Integer, db.ForeignKey('machine_drawing.id'), nullable=False)
    quantity_scrapped = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.Text, nullable=True)
    scrapped_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))

    originating_quality_check_rel = relationship("QualityCheck", back_populates="scrapped_items_generated")
    drawing_rel = relationship("MachineDrawing", foreign_keys=[drawing_id], back_populates="scrapped_items")

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

# --- Helper Functions ---

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def get_machine_choices():
    # Corrected HASS-2 to HAAS-2 as per user's list
    return [
        ("Leadwell-1", "Leadwell-1"), ("Leadwell-2", "Leadwell-2"),
        ("VMC1", "VMC1"), ("VMC2", "VMC2"), ("VMC3", "VMC3"), ("VMC4", "VMC4"),
        ("HAAS-1", "HAAS-1"), ("HAAS-2", "HAAS-2")
    ]

def clear_user_session():
    """Clears all session keys related to user login and roles."""
    keys_to_clear = [
        'active_role', 'username', 'user_role', # 'user_role' is old, clearing for safety
        'operator_session_id', 'operator_name', 'machine_name',
        'current_drawing_id', 'current_operator_log_id',
        'current_drawing_number_display', 'fpi_status_for_current_drawing'
    ]
    for key in keys_to_clear:
        session.pop(key, None)
    # session.clear() could also be used for a more aggressive clear if needed,
    # but targeted pop is often safer if some session keys are unrelated to auth.
    # For now, this list covers all known auth/role/workflow keys.
    print("DEBUG: All user session keys cleared.")

# Helper function to ensure datetime is UTC aware
def ensure_utc_aware(dt):
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

# --- Routes ---

@app.route('/')
def home():
    return redirect(url_for('login_general'))

# --- AUTHENTICATION & ROLE MANAGEMENT ---
@app.route('/login', methods=['GET', 'POST'])
def login_general():
    if request.method == 'POST':
        clear_user_session() # Clear any previous session first when POSTing to log in

        username = request.form.get('username')
        password = request.form.get('password') 
        
        if username == 'planner' and password == 'plannerpass':
            session['active_role'] = 'planner'
            session['username'] = username
            flash('Planner login successful!', 'success')
            print(f"DEBUG: Session after planner login: {dict(session)}")
            return redirect(url_for('planner_dashboard'))
        elif username == 'manager' and password == 'managerpass':
            session['active_role'] = 'manager'
            session['username'] = username
            flash('Manager login successful!', 'success')
            print(f"DEBUG: Session after manager login: {dict(session)}")
            return redirect(url_for('manager_dashboard'))
        elif username == 'quality' and password == 'qualitypass':
            session['active_role'] = 'quality'
            session['username'] = username 
            flash('Quality login successful!', 'success')
            print(f"DEBUG: Session after quality login: {dict(session)}")
            return redirect(url_for('quality_dashboard'))
        else:
            flash('Invalid credentials for Planner, Manager, or Quality.', 'danger')
    else: # GET request - REMOVED clear_user_session() from here
        pass

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
    if session.get('active_role') != 'planner': # Use 'active_role'
        flash('Access denied. Please login as Planner.', 'danger')
        return redirect(url_for('login_general'))

    if request.method == 'POST':
        file = request.files.get('production_plan_file')
        if file and allowed_file(file.filename):
            try:
                df = pd.read_excel(file, dtype={
                    'project_code': str,
                    'sap_id': str, 
                    'end_product': str, 
                    'discription': str, 
                    'route': str
                })
                print(f"DEBUG: Columns found in Excel (raw): {df.columns.tolist()}") # For debugging

                # Normalize column names from the DataFrame: convert to lowercase and strip spaces
                normalized_df_columns = [str(col).lower().strip() for col in df.columns]
                df.columns = normalized_df_columns # Apply normalized names back to DataFrame for consistent access
                print(f"DEBUG: Columns found in Excel (normalized): {normalized_df_columns}")


                # Define required columns in lowercase, matching the user's Excel file
                required_cols = ['project_code', 'project_name', 'end_product', # Changed from 'end_product_name'
                                 'sap_id', 'discription',       # Changed from 'description'
                                 'qty', 'route', 'completion_date', 'st', 'ct']
                
                # Check if all normalized required columns are present in the normalized DataFrame columns
                missing_cols = [col for col in required_cols if col not in normalized_df_columns]

                if missing_cols:
                    flash(f'Excel file missing required columns. Missing: {", ".join(missing_cols)}. Found: {", ".join(normalized_df_columns)}', 'danger')
                else:
                    for index, row in df.iterrows():
                        # Access row data using normalized column names
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
                                description=str(row.get('discription', '')).strip(), # Changed from 'description'
                                route=str(row.get('route', '')).strip()
                            )
                            db.session.add(project)
                            db.session.flush() # Get project.id

                        end_product = EndProduct.query.filter_by(sap_id=sap_id_val).first()
                        if not end_product:
                            end_product = EndProduct(
                                project_id=project.id,
                                name=str(row['end_product']).strip(), # Changed from 'end_product_name'
                                sap_id=sap_id_val,
                                quantity=int(row['qty']),
                                completion_date=pd.to_datetime(row['completion_date']).date(),
                                setup_time_std=float(row['st']),
                                cycle_time_std=float(row['ct'])
                            )
                            db.session.add(end_product)
                        else: # Update existing EndProduct if SAP ID matches
                            end_product.project_id = project.id 
                            end_product.name=str(row['end_product']).strip() # Changed from 'end_product_name'
                            end_product.quantity=int(row['qty'])
                            end_product.completion_date=pd.to_datetime(row['completion_date']).date()
                            end_product.setup_time_std=float(row['st'])
                            end_product.cycle_time_std=float(row['ct'])
                    db.session.commit()
                    flash('Production plan uploaded successfully!', 'success')
            except Exception as e:
                db.session.rollback()
                flash(f'Error uploading plan: {str(e)}', 'danger')
        else:
            flash('Invalid file type or no file selected. Please upload an .xlsx file.', 'warning')
        return redirect(url_for('planner_dashboard'))
            
    projects = Project.query.filter_by(is_deleted=False).order_by(Project.project_code).all()
    return render_template('planner.html', projects=projects)

# --- MANAGER ---
@app.route('/manager', methods=['GET', 'POST'])
def manager_dashboard():
    print(f"DEBUG: Session at start of /manager: {dict(session)}") 
    if session.get('active_role') != 'manager':
        flash('Access denied. Please login as Manager.', 'danger')
        return redirect(url_for('login_general'))

    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'approve_rework':
            rework_id = request.form.get('rework_id')
            manager_notes = request.form.get('manager_notes', '').strip()
            
            if not rework_id:
                flash('Rework ID is required for approval.', 'danger')
            else:
                rework_item = ReworkQueue.query.get(rework_id)
                if not rework_item:
                    flash('Rework item not found.', 'danger')
                else:
                    rework_item.status = 'manager_approved'
                    rework_item.manager_approved_by = session.get('username')
                    rework_item.manager_approval_time = datetime.now(timezone.utc)
                    rework_item.manager_notes = manager_notes
                    db.session.commit()
                    flash('Rework request approved successfully.', 'success')
            
            return redirect(url_for('manager_dashboard'))
            
        elif action == 'reject_rework':
            rework_id = request.form.get('rework_id')
            manager_notes = request.form.get('manager_notes', '').strip()
            
            if not rework_id:
                flash('Rework ID is required for rejection.', 'danger')
            else:
                rework_item = ReworkQueue.query.get(rework_id)
                if not rework_item:
                    flash('Rework item not found.', 'danger')
                else:
                    rework_item.status = 'manager_rejected'
                    rework_item.manager_approved_by = session.get('username')
                    rework_item.manager_approval_time = datetime.now(timezone.utc)
                    rework_item.manager_notes = manager_notes
                    
                    # Create scrap record for rejected rework
                    scrap_record = ScrapLog(
                        drawing_id=rework_item.drawing_id,
                        quantity_scrapped=rework_item.quantity_to_rework,
                        reason=f"Rework rejected by manager. Notes: {manager_notes}",
                        scrapped_at=datetime.now(timezone.utc),
                        scrapped_by=session.get('quality_inspector_name'),
                        operator_log_id=rework_item.source_operator_log_id,
                        quality_check_id=rework_item.originating_quality_check_id
                    )
                    db.session.add(scrap_record)
                    db.session.commit()
                    flash('Rework request rejected and items marked as scrapped.', 'warning')
        
        return redirect(url_for('manager_dashboard'))

    # Get all rework queue items
    rework_queue = ReworkQueue.query.order_by(
        case(
            (ReworkQueue.status == 'pending_manager_approval', 1),
            (ReworkQueue.status == 'manager_approved', 2),
            (ReworkQueue.status == 'rework_in_progress', 3),
            (ReworkQueue.status == 'rework_completed_pending_qc', 4),
            else_=5
        ),
        ReworkQueue.id.desc()
    ).all()

    # Get all active projects for production plan overview
    projects = Project.query.filter_by(is_deleted=False).order_by(Project.project_code).all()

    return render_template('manager.html', 
                         rework_queue=rework_queue,
                         projects=projects)

# --- OPERATOR ---
@app.route('/operator_login', methods=['GET', 'POST'])
def operator_login():
    if request.method == 'POST':
        clear_user_session() # Clear any previous session first when POSTing to log in

        operator_name = request.form.get('operator_name', '').strip()
        machine_name = request.form.get('machine_name')
        shift = request.form.get('shift')

        if not operator_name or not machine_name or not shift:
            flash('All fields are required for login.', 'danger')
        else:
            machine = Machine.query.filter_by(name=machine_name).first()
            if not machine:
                flash(f'Machine {machine_name} not found.', 'danger')
            else: # Machine is found, proceed with login
                # End any previous active session for this operator or this machine
                old_sessions = OperatorSession.query.filter(
                    db.or_(
                        OperatorSession.operator_name == operator_name,
                        OperatorSession.machine_id == machine.id
                    ),
                    OperatorSession.is_active == True
                ).all()
                
                for old_session in old_sessions:
                    # Close the session
                    old_session.is_active = False
                    old_session.logout_time = datetime.now(timezone.utc)
                    
                    # Close any hanging logs for this session
                    hanging_logs = OperatorLog.query.filter(
                        OperatorLog.operator_session_id == old_session.id,
                        OperatorLog.current_status.notin_(['lpi_completed', 'admin_closed'])
                    ).all()
                    
                    for log in hanging_logs:
                        log.current_status = 'admin_closed'
                        log.notes = (log.notes or "") + f"\nLog auto-closed due to new operator login at {datetime.now(timezone.utc)}."
                
                db.session.commit()

                new_op_session = OperatorSession(operator_name=operator_name, machine_id=machine.id, shift=shift)
                db.session.add(new_op_session)
                db.session.commit()

                session['active_role'] = 'operator' 
                session['operator_session_id'] = new_op_session.id
                session['operator_name'] = operator_name
                session['machine_name'] = machine_name 
                
                flash(f'Welcome {operator_name}! Logged in on {machine_name}, Shift {shift}.', 'success')
                print(f"DEBUG: Session after operator login: {dict(session)}") 
                
                # Redirect to specific machine panel based on machine name
                if machine_name == 'Leadwell-1':
                    return redirect(url_for('operator_panel_leadwell1'))
                elif machine_name == 'Leadwell-2':
                    return redirect(url_for('operator_panel_leadwell2'))
                else:
                    flash('Currently only Leadwell-1 and Leadwell-2 machines are supported. Please contact your administrator.', 'warning')
                    return redirect(url_for('operator_login'))
    
    # If GET request, or POST request with missing fields/machine not found, render the login page again.
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
    if 'active_role' not in session or session['active_role'] != 'operator' or session.get('machine_name') != 'Leadwell-1':
        flash('Access denied. Please login as an operator for Leadwell-1.', 'danger')
        return redirect(url_for('operator_login'))
    
    # Reuse the operator_panel logic but with machine-specific customizations
    return operator_panel_common('Leadwell-1', 'operator_leadwell1.html')

@app.route('/operator/leadwell2', methods=['GET', 'POST'])
def operator_panel_leadwell2():
    if 'active_role' not in session or session['active_role'] != 'operator' or session.get('machine_name') != 'Leadwell-2':
        flash('Access denied. Please login as an operator for Leadwell-2.', 'danger')
        return redirect(url_for('operator_login'))
    
    # Reuse the operator_panel logic but with machine-specific customizations
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
    # Initialize variables used throughout the route
    current_log_id = session.get('current_operator_log_id')
    current_op_log = db.session.get(OperatorLog, current_log_id) if current_log_id else None
    active_drawing_obj = db.session.get(MachineDrawing, session.get('current_drawing_id')) if session.get('current_drawing_id') else None
    action = request.form.get('action') if request.method == 'POST' else None
    
    # Get operator session and machine info
    operator_name = session.get('operator_name')
    machine_obj = Machine.query.filter_by(name=machine_name).first()
    operator_session_obj = db.session.get(OperatorSession, session.get('operator_session_id'))

    # Get all active logs for this operator's sessions
    active_logs = []
    if operator_session_obj:
        active_logs = OperatorLog.query.join(OperatorSession).filter(
            OperatorSession.operator_name == operator_session_obj.operator_name,
            OperatorLog.current_status.notin_(['lpi_completed', 'admin_closed'])
        ).order_by(OperatorLog.setup_start_time.desc()).all()

    # Get approved rework items for this machine
    approved_rework_items = ReworkQueue.query.filter_by(
        status='manager_approved'
    ).order_by(ReworkQueue.created_at.desc()).all()

    if request.method == 'POST':
        if action == 'select_drawing_and_start_session':
            drawing_number = request.form.get('drawing_number_input', '').strip()
            if not drawing_number:
                flash('Drawing number is required.', 'warning')
                return redirect(get_redirect_url(machine_name))

            # Find the drawing
            drawing = MachineDrawing.query.filter_by(drawing_number=drawing_number).first()
            if not drawing:
                flash(f'Drawing {drawing_number} not found.', 'warning')
                return redirect(get_redirect_url(machine_name))

            # Update session with new drawing
            session['current_drawing_id'] = drawing.id
            session['current_drawing_number_display'] = drawing.drawing_number
            flash(f'Drawing {drawing_number} selected.', 'success')
            return redirect(get_redirect_url(machine_name))

        if action == 'start_setup':
            print(f"DEBUG SETUP: Starting setup with session: {dict(session)}")
            print(f"DEBUG SETUP: active_drawing_obj = {active_drawing_obj}")
            print(f"DEBUG SETUP: current_op_log = {current_op_log}")
            print(f"DEBUG SETUP: current_op_log status = {current_op_log.current_status if current_op_log else 'No log'}")

            if not active_drawing_obj:
                flash('Please select a drawing first.', 'warning')
                return redirect(get_redirect_url(machine_name))

            if not machine_obj or machine_obj.status == 'breakdown':
                flash('Machine is not operational. Cannot start setup.', 'danger')
                return redirect(get_redirect_url(machine_name))

            # Check if there's any active production log (not waiting for quality or rework)
            active_production_log = OperatorLog.query.filter(
                OperatorLog.operator_session_id == operator_session_obj.id,
                OperatorLog.current_status.in_(['setup_started', 'setup_done', 'cycle_started', 'cycle_paused', 'fpi_passed_ready_for_cycle'])
            ).first()
            
            if active_production_log:
                flash('Cannot start setup for new drawing while another drawing is in active production. Please complete or cancel the active production first.', 'warning')
                return redirect(get_redirect_url(machine_name))

            # At this point, we can start setup because either:
            # 1. There's no current log
            # 2. Current log is in a state that allows new setup (completed, closed, or pending)
            print(f"DEBUG SETUP: Creating new log for setup")
            new_log = OperatorLog(
                operator_session_id=operator_session_obj.id,
                drawing_id=active_drawing_obj.id,
                end_product_sap_id=active_drawing_obj.sap_id,
                setup_start_time=datetime.now(timezone.utc),
                current_status='setup_started',
                run_planned_quantity=1  # Default to 1 for FPI
            )
            db.session.add(new_log)
            db.session.flush()  # Get the new log's ID
            session['current_operator_log_id'] = new_log.id
            db.session.commit()
            flash('Setup started.', 'success')

            return redirect(get_redirect_url(machine_name))

        elif action == 'start_rework':
            rework_id = request.form.get('rework_id')
            if not rework_id:
                flash('Rework ID is required.', 'danger')
                return redirect(get_redirect_url(machine_name))

            rework_item = ReworkQueue.query.get(rework_id)
            if not rework_item:
                flash('Rework item not found.', 'danger')
                return redirect(get_redirect_url(machine_name))

            if rework_item.status != 'manager_approved':
                flash('This rework item is not approved for processing.', 'warning')
                return redirect(get_redirect_url(machine_name))

            # Create a new operator log for the rework
            new_rework_log = OperatorLog(
                operator_session_id=operator_session_obj.id,
                drawing_id=rework_item.drawing_id,
                end_product_sap_id=rework_item.drawing_rel.end_product_rel.sap_id,
                run_planned_quantity=rework_item.quantity_to_rework,
                is_rework_task=True,
                current_status='pending_setup',
                notes=f"Rework task for ReworkQueue ID: {rework_item.id}. Original rejection reason: {rework_item.rejection_reason}"
            )
            db.session.add(new_rework_log)
            db.session.flush()  # Get the new log's ID

            # Update the rework queue item
            rework_item.status = 'rework_in_progress'
            rework_item.assigned_operator_log_id = new_rework_log.id

            # Update session to track the new log
            session['current_operator_log_id'] = new_rework_log.id
            session['current_drawing_id'] = rework_item.drawing_id
            session['current_drawing_number_display'] = rework_item.drawing_rel.drawing_number

            print(f"DEBUG REWORK: Created new rework log ID: {new_rework_log.id}")
            print(f"DEBUG REWORK: Session after rework start: {dict(session)}")

            db.session.commit()
            flash(f'Rework task started for drawing {rework_item.drawing_rel.drawing_number}. Please begin setup.', 'success')
            return redirect(get_redirect_url(machine_name))

        elif action == 'cycle_pause':
            if current_op_log.current_status == 'cycle_started':
                current_op_log.current_status = 'cycle_paused'
                db.session.commit()
                flash('Cycle paused.', 'info')
            else:
                flash(f'Cannot pause cycle. Current log status: {current_op_log.current_status}. Ensure cycle is started.', 'warning')
            return redirect(get_redirect_url(machine_name))

        elif action == 'close_all_active_logs':
            if not operator_session_obj:
                flash('Operator session not found. Please re-login.', 'danger')
                return redirect(get_redirect_url(machine_name))

            # Get all active logs for this operator
            logs_to_close = OperatorLog.query.join(OperatorSession).filter(
                OperatorSession.operator_name == operator_session_obj.operator_name,
                OperatorLog.current_status.notin_(['lpi_completed', 'admin_closed'])
            ).all()

            if not logs_to_close:
                flash('No active logs found to close.', 'info')
                return redirect(get_redirect_url(machine_name))

            closed_count = 0
            skipped_count = 0
            for log in logs_to_close:
                # Skip logs with pending rework or quality checks
                pending_rework = ReworkQueue.query.filter_by(
                    source_operator_log_id=log.id,
                    status='pending_manager_approval'
                ).first()
                
                if pending_rework:
                    skipped_count += 1
                    continue

                if log.current_status in ['cycle_completed_pending_fpi', 'cycle_completed_pending_lpi']:
                    skipped_count += 1
                    continue

                log.current_status = 'admin_closed'
                log.notes = (log.notes or '') + f"\nLog auto-closed by operator bulk close action at {datetime.now(timezone.utc)}."
                closed_count += 1

            if closed_count > 0:
                # Clear current log from session as it might have been closed
                session.pop('current_operator_log_id', None)
                db.session.commit()
                message = f'{closed_count} logs closed successfully.'
                if skipped_count > 0:
                    message += f' {skipped_count} logs skipped due to pending quality checks or rework.'
                flash(message, 'success')
            else:
                if skipped_count > 0:
                    flash(f'No logs closed. {skipped_count} logs skipped due to pending quality checks or rework.', 'warning')
                else:
                    flash('No logs were eligible for closing.', 'info')
            
            return redirect(get_redirect_url(machine_name))

        elif action == 'setup_done':
            if not current_op_log:
                flash('No active setup found.', 'warning')
                return redirect(get_redirect_url(machine_name))

            if current_op_log.current_status != 'setup_started':
                flash('Cannot complete setup. Current log status is not in setup.', 'warning')
                return redirect(get_redirect_url(machine_name))

            current_op_log.setup_end_time = datetime.now(timezone.utc)
            current_op_log.current_status = 'setup_done'
            db.session.commit()
            flash('Setup completed. Ready to start cycle.', 'success')
            return redirect(get_redirect_url(machine_name))

    # ----- Recalculate FPI Hold Status on every GET and after relevant POST actions -----
    session.pop('drawing_held_for_fpi', None) # Default to not held, recalculate
    calculated_fpi_status_for_template = 'no_fpi_issue' # Default for template display
    blocking_fpi_log_details_for_template = None # Initialize

    if active_drawing_obj:
        # Check if ANY log for the current drawing is actively holding production due to FPI
        any_log_for_drawing_is_holding_fpi = OperatorLog.query.filter(
            OperatorLog.drawing_id == active_drawing_obj.id,
            OperatorLog.production_hold_fpi == True,
            OperatorLog.current_status.notin_(['lpi_completed', 'admin_closed']) # Only active holds
        ).first()

        if any_log_for_drawing_is_holding_fpi:
            session['drawing_held_for_fpi'] = True
            if current_op_log and current_op_log.id == any_log_for_drawing_is_holding_fpi.id:
                calculated_fpi_status_for_template = f'CURRENT LOG HOLDING: Your current Log ID {current_op_log.id} is awaiting FPI or FPI has failed. Please resolve with Quality.'
            else:
                blocking_fpi_log_details_for_template = any_log_for_drawing_is_holding_fpi
                calculated_fpi_status_for_template = f'OTHER LOG HOLDING: Production for this drawing is on hold due to an FPI issue with Log ID {any_log_for_drawing_is_holding_fpi.id}. See details below. Please notify Quality Control.'
        
        # Additionally, if the current specific operator log is pending FPI, it implies a hold for THIS log.
        if current_op_log and current_op_log.drawing_id == active_drawing_obj.id and \
           current_op_log.current_status == 'cycle_completed_pending_fpi' and not session.get('drawing_held_for_fpi'):
            session['drawing_held_for_fpi'] = True 
            calculated_fpi_status_for_template = f'CURRENT LOG PENDING: Your current log (ID: {current_op_log.id}) requires FPI.'

    if request.method == 'POST':
        if not machine_obj:
            flash('Machine not found or not selected. Please re-login.', 'danger')
            return redirect(url_for('operator_login'))
        if not operator_session_obj:
            flash('Operator session not found. Please re-login.', 'danger')
            return redirect(url_for('operator_login'))

        # Get the machine object associated with the current operator session
        current_machine_for_action = None
        if operator_session_obj and operator_session_obj.machine_rel:
            current_machine_for_action = operator_session_obj.machine_rel
        elif machine_name:
            current_machine_for_action = Machine.query.filter_by(name=machine_name).first()

        # First check if we have a drawing selected when needed
        if action not in ['select_drawing_and_start_session', 'report_breakdown', 'mark_machine_healthy'] and not active_drawing_obj:
            flash('No drawing selected in session. Please select a drawing first.', 'warning')
            return redirect(get_redirect_url(machine_name))

        # Then check if we have an active log when needed
        if action not in ['select_drawing_and_start_session', 'start_setup', 'report_breakdown', 'mark_machine_healthy'] and not current_op_log:
            flash('No active operation log found for the selected drawing. Please start setup.', 'warning')
            return redirect(get_redirect_url(machine_name))

        # Finally check if the active log matches the selected drawing
        if current_op_log and active_drawing_obj and current_op_log.drawing_id != active_drawing_obj.id and \
           action not in ['select_drawing_and_start_session', 'report_breakdown', 'mark_machine_healthy']:
            flash('Active log does not match selected drawing. Please re-select drawing or cancel current log.', 'danger')
            return redirect(get_redirect_url(machine_name))

        # Now handle the specific actions
        if action == 'cycle_start':
            # Check global FPI hold first for the drawing type
            if session.get('drawing_held_for_fpi') and calculated_fpi_status_for_template.startswith("OTHER LOG HOLDING"):
                flash(calculated_fpi_status_for_template, 'danger')
                return redirect(get_redirect_url(machine_name))

            # Then check FPI hold specifically for this log / its FPI status
            if current_op_log.production_hold_fpi and current_op_log.current_status == 'cycle_completed_pending_fpi':
                flash(f'Cannot start cycle. Current Log (ID: {current_op_log.id}) is awaiting FPI approval.', 'danger')
            elif current_op_log.production_hold_fpi and current_op_log.current_status == 'fpi_failed_setup_pending':
                flash(f'Cannot start cycle. FPI failed for current Log (ID: {current_op_log.id}). Please address setup issues or cancel log.', 'danger')
            elif current_op_log.current_status in ['setup_done', 'fpi_passed_ready_for_cycle', 'cycle_paused']:
                current_op_log.current_status = 'cycle_started'
                if not current_op_log.first_cycle_start_time: 
                    current_op_log.first_cycle_start_time = datetime.now(timezone.utc)
                current_op_log.last_cycle_start_time = datetime.now(timezone.utc)
                db.session.commit()
                flash(f'Cycle started for part {(current_op_log.run_completed_quantity or 0) + 1}.', 'success')
            else:
                flash(f'Cannot start cycle. Current log status: {current_op_log.current_status}. Ensure setup is done and FPI (if applicable) has passed.', 'warning')
            return redirect(get_redirect_url(machine_name))

        elif action == 'cycle_complete':
            if current_op_log.current_status == 'cycle_started':
                current_op_log.run_completed_quantity = (current_op_log.run_completed_quantity or 0) + 1
                current_op_log.last_cycle_end_time = datetime.now(timezone.utc) 
                
                end_product = active_drawing_obj.end_product_rel # Should exist if setup was started
                is_fpi_req_for_drawing = end_product.is_first_piece_fpi_required if end_product else True
                # Only require LPI if quantity is more than 1
                is_lpi_req_for_drawing = (end_product.is_last_piece_lpi_required and current_op_log.run_planned_quantity > 1) if end_product else False

                print(f"DEBUG CYCLE COMPLETE: Log ID {current_op_log.id}")
                print(f"DEBUG CYCLE COMPLETE: run_completed_quantity = {current_op_log.run_completed_quantity}")
                print(f"DEBUG CYCLE COMPLETE: run_planned_quantity = {current_op_log.run_planned_quantity}")
                print(f"DEBUG CYCLE COMPLETE: is_fpi_req_for_drawing = {is_fpi_req_for_drawing}")
                print(f"DEBUG CYCLE COMPLETE: is_lpi_req_for_drawing = {is_lpi_req_for_drawing}")

                if current_op_log.run_completed_quantity == 1 and is_fpi_req_for_drawing:
                    current_op_log.current_status = 'cycle_completed_pending_fpi'
                    current_op_log.fpi_status = 'pending'
                    current_op_log.production_hold_fpi = True
                    flash(f'First part completed. FPI required. Production for THIS LOG is on hold.', 'info')
                elif current_op_log.run_completed_quantity >= current_op_log.run_planned_quantity and is_lpi_req_for_drawing:
                    current_op_log.current_status = 'cycle_completed_pending_lpi'
                    current_op_log.lpi_status = 'pending'
                    flash(f'Planned quantity ({current_op_log.run_planned_quantity}) reached. LPI required.', 'info')
                else:
                    # If quantity is 1 and FPI passed, or if LPI not required, mark as completed
                    if current_op_log.run_completed_quantity >= current_op_log.run_planned_quantity:
                        current_op_log.current_status = 'lpi_completed'
                        flash(f'All parts completed. No LPI required for single piece.', 'success')
                    else:
                        current_op_log.current_status = 'fpi_passed_ready_for_cycle'
                        flash(f'Part {current_op_log.run_completed_quantity} of {current_op_log.run_planned_quantity} completed. Ready for next cycle.', 'success')
                    
                    db.session.commit()
                return redirect(get_redirect_url(machine_name))
            else:
                flash(f'Cannot complete cycle. Current log status: {current_op_log.current_status}. Ensure cycle is started.', 'warning')
                return redirect(get_redirect_url(machine_name))

        elif action == 'cycle_pause':
            if current_op_log.current_status == 'cycle_started':
                current_op_log.current_status = 'cycle_paused'
                db.session.commit()
                flash('Cycle paused.', 'info')
            else:
                flash(f'Cannot pause cycle. Current log status: {current_op_log.current_status}. Ensure cycle is started.', 'warning')
            return redirect(get_redirect_url(machine_name))

        elif action == 'close_all_active_logs':
            if not operator_session_obj:
                flash('Operator session not found. Please re-login.', 'danger')
                return redirect(get_redirect_url(machine_name))

            # Get all active logs for this operator
            logs_to_close = OperatorLog.query.join(OperatorSession).filter(
                OperatorSession.operator_name == operator_session_obj.operator_name,
                OperatorLog.current_status.notin_(['lpi_completed', 'admin_closed'])
            ).all()

            if not logs_to_close:
                flash('No active logs found to close.', 'info')
                return redirect(get_redirect_url(machine_name))

            closed_count = 0
            skipped_count = 0
            for log in logs_to_close:
                # Skip logs with pending rework or quality checks
                pending_rework = ReworkQueue.query.filter_by(
                    source_operator_log_id=log.id,
                    status='pending_manager_approval'
                ).first()
                
                if pending_rework:
                    skipped_count += 1
                    continue

                if log.current_status in ['cycle_completed_pending_fpi', 'cycle_completed_pending_lpi']:
                    skipped_count += 1
                    continue

                log.current_status = 'admin_closed'
                log.notes = (log.notes or '') + f"\nLog auto-closed by operator bulk close action at {datetime.now(timezone.utc)}."
                closed_count += 1

            if closed_count > 0:
                # Clear current log from session as it might have been closed
                session.pop('current_operator_log_id', None)
                db.session.commit()
                message = f'{closed_count} logs closed successfully.'
                if skipped_count > 0:
                    message += f' {skipped_count} logs skipped due to pending quality checks or rework.'
                flash(message, 'success')
            else:
                if skipped_count > 0:
                    flash(f'No logs closed. {skipped_count} logs skipped due to pending quality checks or rework.', 'warning')
                else:
                    flash('No logs were eligible for closing.', 'info')
            
            return redirect(get_redirect_url(machine_name))

    # Prepare data for template
    return render_template(
        template_name,
        operator_name=operator_name,
        machine_name=machine_name,
        current_machine_obj=machine_obj,  # Add this line to pass machine object
        active_drawing=active_drawing_obj,
        current_log=current_op_log,
        active_logs=active_logs,
        approved_rework_items=approved_rework_items,
        fpi_status=calculated_fpi_status_for_template,
        blocking_fpi_log=blocking_fpi_log_details_for_template,
        drawing_number_input=session.get('operator_drawing_number_input', ''),
        is_drawing_globally_held_for_fpi=session.get('drawing_held_for_fpi', False)
    )

# --- QUALITY ---
@app.route('/quality', methods=['GET', 'POST'])
def quality_dashboard():
    print(f"DEBUG: Session at start of /quality: {dict(session)}") 
    if session.get('active_role') != 'quality':
        flash('Access denied. Please login as Quality Inspector.', 'danger')
        return redirect(url_for('login_general'))

    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'set_inspector_name':
            inspector_name = request.form.get('inspector_name', '').strip()
            if inspector_name:
                session['quality_inspector_name'] = inspector_name
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
                    quality_check_id=new_qc_record.id
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
                        quality_check_id=new_qc_record.id
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
                        quality_check_id=new_qc_record.id
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

    print(f"DEBUG QUALITY: Found {len(pending_fpi_logs)} pending FPI logs")
    print(f"DEBUG QUALITY: Found {len(pending_lpi_logs)} pending LPI logs")
    
    for log in pending_fpi_logs:
        print(f"DEBUG QUALITY FPI: Log ID {log.id}, Status {log.current_status}, Drawing {log.drawing_rel.drawing_number if log.drawing_rel else 'No drawing'}")
    
    for log in pending_lpi_logs:
        print(f"DEBUG QUALITY LPI: Log ID {log.id}, Status {log.current_status}, Drawing {log.drawing_rel.drawing_number if log.drawing_rel else 'No drawing'}")

    return render_template(
        'quality.html',
        inspector_name=session.get('quality_inspector_name'),
        pending_fpi_logs=pending_fpi_logs,
        pending_lpi_logs=pending_lpi_logs
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
    if 'active_role' not in session or session['active_role'] not in ['manager', 'planner']:
        flash('Access denied. Only managers and planners can access reports.', 'danger')
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
            db.joinedload(OperatorLog.operator_session_rel),
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
                'shift': log.operator_session_rel.shift,
                'machine': machine.name,
                'operator': log.operator_session_rel.operator_name,
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
                'quality_status': "Pending FPI" if log.current_status == 'cycle_completed_pending_fpi' 
                                else "Pending LPI" if log.current_status == 'cycle_completed_pending_lpi' 
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

# --- DB Initialization ---
def setup_database():
    # db.drop_all() # Use with caution - for development reset only
    db.create_all()
    
    # Pre-populate machines if they don't exist
    for machine_name, _ in get_machine_choices():
        if not Machine.query.filter_by(name=machine_name).first():
            db.session.add(Machine(name=machine_name))
        db.session.commit()
        
if __name__ == '__main__':
    with app.app_context():
        # Call the setup logic directly or inline it
        # Inlining the logic from setup_database():
        # db.drop_all() # Use with caution - for development reset only
        db.create_all()
        
        # Pre-populate machines if they don't exist
        for machine_name, _ in get_machine_choices():
            if not Machine.query.filter_by(name=machine_name).first():
                db.session.add(Machine(name=machine_name))
        db.session.commit()
        print("Database tables created and machines pre-populated within app context.")

    app.run(debug=True, host='0.0.0.0', port=5000)