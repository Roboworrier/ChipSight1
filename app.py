from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, session
from werkzeug.utils import secure_filename
from datetime import datetime
import os
import pandas as pd
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from jinja2 import FileSystemLoader

# Disable .env file loading
os.environ['FLASK_SKIP_DOTENV'] = '1'

# Initialize Flask app
app = Flask(__name__)

# Basic configuration without .env
app.secret_key = 'dev_key_only_for_development'  # Change this in production
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///digital_twin.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['ALLOWED_EXTENSIONS'] = {'xlsx'}

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

# Set default MIME type and charset for responses
@app.after_request
def add_header(response):
    if 'text/html' in response.headers['Content-Type']:
        response.headers['Content-Type'] = 'text/html; charset=utf-8'
    return response

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

db = SQLAlchemy(app)

# Models
class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50))
    name = db.Column(db.String(100))
    end_product = db.Column(db.String(100))
    sap_id = db.Column(db.String(50))
    quantity = db.Column(db.Integer)
    completion_date = db.Column(db.String(50))
    setup_time_std = db.Column(db.Float)
    cycle_time_std = db.Column(db.Float)
    batch_number = db.Column(db.Integer)
    actual_quantity = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_deleted = db.Column(db.Boolean, default=False)  # Add deletion flag
    deleted_at = db.Column(db.DateTime, nullable=True)  # Add deletion timestamp

class MachineDrawing(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    drawing_number = db.Column(db.String(100), unique=True)
    sap_id = db.Column(db.String(50))

class OperatorLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    drawing_number = db.Column(db.String(100))
    setup_start = db.Column(db.DateTime)
    setup_done = db.Column(db.DateTime)
    cycle_start = db.Column(db.DateTime)
    cycle_done = db.Column(db.DateTime)
    status = db.Column(db.String(50))  # Setup Started, Setup Done, Cycle Started, Cycle Completed, Aborted
    setup_time = db.Column(db.Float)  # Time taken for setup in minutes
    cycle_time = db.Column(db.Float)  # Time taken for cycle in minutes
    abort_reason = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    batch_number = db.Column(db.String(50))  # Track production batches
    planned_quantity = db.Column(db.Integer)  # Planned quantity for this batch
    completed_quantity = db.Column(db.Integer, default=0)  # Successfully completed pieces
    rejected_quantity = db.Column(db.Integer, default=0)  # Rejected pieces
    rework_quantity = db.Column(db.Integer, default=0)  # Pieces in rework
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
    production_hold = db.Column(db.Boolean, default=True)  # True until FPI passes
    drawing_revision = db.Column(db.String(20))  # Track drawing revision
    sap_id = db.Column(db.String(100))  # Link to SAP order

class QualityCheck(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    drawing_number = db.Column(db.String(100))
    type = db.Column(db.String(20))  # First Part, In Process, Last Part, Final
    result = db.Column(db.String(10))  # Pass or Reject
    rejection_reason = db.Column(db.Text)
    quantity_checked = db.Column(db.Integer)  # Number of pieces checked
    quantity_passed = db.Column(db.Integer)  # Number of pieces passed
    quantity_rejected = db.Column(db.Integer)  # Number of pieces rejected
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    operator_log_id = db.Column(db.Integer, db.ForeignKey('operator_log.id'))
    status = db.Column(db.String(20))  # Pending, In Progress, Completed
    rework_count = db.Column(db.Integer, default=0)  # Track number of rework cycles
    batch_id = db.Column(db.String(50))  # Group pieces from same batch
    inspector_id = db.Column(db.String(50))  # Track quality inspector
    inspection_station = db.Column(db.String(50))  # Track inspection station
    previous_check_id = db.Column(db.Integer, db.ForeignKey('quality_check.id'))  # Link to previous check if rework
    rework_queue_id = db.Column(db.Integer, db.ForeignKey('rework_queue.id'))  # Link to rework queue
    inspection_checklist = db.Column(db.JSON)  # Store inspection checklist items and results
    
    __table_args__ = (
        db.UniqueConstraint('drawing_number', 'type', 'batch_id', name='unique_quality_check'),
    )

class ReworkQueue(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    drawing_number = db.Column(db.String(100))
    batch_id = db.Column(db.String(50))  # Group pieces from same batch
    initial_quantity = db.Column(db.Integer)  # Initial quantity sent for rework
    remaining_quantity = db.Column(db.Integer)  # Remaining pieces to be reworked
    completed_quantity = db.Column(db.Integer, default=0)  # Successfully reworked pieces
    rejected_quantity = db.Column(db.Integer, default=0)  # Pieces rejected after rework
    type = db.Column(db.String(10))  # FPI or LPI
    rejection_reason = db.Column(db.Text)
    priority = db.Column(db.Integer, default=1)  # Priority level (1-5)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    started_at = db.Column(db.DateTime)  # When rework started
    completed_at = db.Column(db.DateTime)  # When rework completed
    status = db.Column(db.String(20))  # Pending, In Progress, Completed, On Hold
    assigned_to = db.Column(db.String(50))  # Operator assigned for rework
    rework_station = db.Column(db.String(50))  # Station where rework is performed
    rework_instructions = db.Column(db.Text)  # Special instructions for rework
    rework_history = db.relationship('QualityCheck', 
                                   backref='rework_queue', 
                                   lazy=True,
                                   foreign_keys=[QualityCheck.rework_queue_id])

class MachineAssignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    machine = db.Column(db.String(100))
    drawing_number = db.Column(db.String(100))
    start_time = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20))  # Active, Completed
    quantity = db.Column(db.Integer)
    produced = db.Column(db.Integer, default=0)

class DeletedProjectHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_code = db.Column(db.String(50))
    project_name = db.Column(db.String(100))
    end_product = db.Column(db.String(100))
    sap_id = db.Column(db.String(50))
    batch_number = db.Column(db.Integer)
    planned_quantity = db.Column(db.Integer)
    actual_quantity = db.Column(db.Integer)
    deleted_at = db.Column(db.DateTime, default=datetime.utcnow)
    deleted_by = db.Column(db.String(50), default='planner')
    deletion_type = db.Column(db.String(20))  # 'project' or 'end_product'
    completion_date = db.Column(db.String(50))
    reason = db.Column(db.Text, nullable=True)

# Create tables when the application starts
with app.app_context():
    db.drop_all()  # Drop all existing tables to apply new constraints
    db.create_all()  # Create all tables with new constraints

# Routes
@app.route('/')
def home():
    return redirect(url_for('planner'))

@app.route('/planner', methods=['GET', 'POST'])
def planner():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash("No file part", "danger")
            return redirect(request.url)

        file = request.files['file']
        if file.filename == '':
            flash("No selected file", "danger")
            return redirect(request.url)

        if not allowed_file(file.filename):
            flash("Only Excel (.xlsx) files are allowed", "danger")
            return redirect(request.url)

        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        try:
            file.save(filepath)
            df = pd.read_excel(filepath)
            
            required_columns = ['project_code', 'project_name', 'end_product', 
                             'sap_id', 'qty', 'completion_date', 'st', 'ct']
            missing_columns = [col for col in required_columns if col not in df.columns]
            if missing_columns:
                raise ValueError(f"Missing required columns: {', '.join(missing_columns)}")

            # Data validation
            if df.empty:
                raise ValueError("The Excel file is empty")

            # Validate and convert completion_date
            df['completion_date'] = pd.to_datetime(df['completion_date']).dt.strftime('%Y-%m-%d')
            
            # Validate numeric columns
            df['qty'] = pd.to_numeric(df['qty'], errors='coerce')
            df['st'] = pd.to_numeric(df['st'], errors='coerce')
            df['ct'] = pd.to_numeric(df['ct'], errors='coerce')
            
            if df[['qty', 'st', 'ct']].isna().any().any():
                raise ValueError("Invalid numeric values found in qty, st, or ct columns")

            success_count = 0
            error_count = 0
            
            # Group by SAP ID to handle duplicates
            for sap_id, group in df.groupby('sap_id'):
                batch_number = 1
                for _, row in group.iterrows():
                    try:
                        project = Project(
                            code=str(row['project_code']).strip(),
                            name=str(row['project_name']).strip(),
                            end_product=str(row['end_product']).strip(),
                            sap_id=str(row['sap_id']).strip(),
                            quantity=int(row['qty']),
                            completion_date=row['completion_date'],
                            setup_time_std=float(row['st']),
                            cycle_time_std=float(row['ct']),
                            batch_number=batch_number,
                            actual_quantity=0
                        )
                        db.session.add(project)
                        db.session.commit()
                        success_count += 1
                        batch_number += 1
                    except Exception as e:
                        db.session.rollback()
                        error_count += 1
                        app.logger.error(f"Error processing row: {str(e)}")

            status_message = f"Processed {success_count} projects successfully. "
            if error_count > 0:
                status_message += f"{error_count} errors encountered."
            
            flash(status_message, "success" if error_count == 0 else "warning")
                
        except Exception as e:
            db.session.rollback()
            flash(f"Error processing file: {str(e)}", "danger")
            app.logger.error(f"File processing error: {str(e)}")
        finally:
            # Clean up the uploaded file
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except Exception as e:
                    app.logger.error(f"Error removing temporary file: {str(e)}")

    try:
        # Get active projects (not deleted)
        projects_data = []
        for project in Project.query.filter_by(is_deleted=False).order_by(Project.sap_id, Project.batch_number).all():
            # Get associated drawing
            drawing = MachineDrawing.query.filter_by(sap_id=project.sap_id).first()
            
            # Calculate actual quantity from operator logs
            if drawing:
                completed_logs = OperatorLog.query.filter_by(
                    drawing_number=drawing.drawing_number,
                    status='Cycle Completed'
                ).count()
                project.actual_quantity = completed_logs
                db.session.commit()
            
            # Calculate status and progress
            status = 'not_started'
            status_text = 'Not Started'
            status_color = 'secondary'
            progress = 0
            progress_color = 'info'
            
            if project.actual_quantity > 0:
                progress = (project.actual_quantity / project.quantity) * 100
                
                if progress >= 100:
                    status = 'completed'
                    status_text = 'Completed'
                    status_color = 'success'
                    progress_color = 'success'
                else:
                    status = 'in_progress'
                    status_text = 'In Progress'
                    status_color = 'primary'
                    progress_color = 'info'
                    
                    # Check if delayed
                    try:
                        completion_date = datetime.strptime(project.completion_date, '%Y-%m-%d').date()
                        if datetime.now().date() > completion_date:
                            status = 'delayed'
                            status_text = 'Delayed'
                            status_color = 'danger'
                            progress_color = 'warning'
                    except ValueError:
                        pass
            
            project_data = {
                'id': project.id,
                'code': project.code,
                'name': project.name,
                'end_product': project.end_product,
                'sap_id': project.sap_id,
                'batch_number': project.batch_number,
                'planned_quantity': project.quantity,
                'actual_quantity': project.actual_quantity,
                'completion_date': project.completion_date,
                'status': status,
                'status_text': status_text,
                'status_color': status_color,
                'progress': progress,
                'progress_color': progress_color
            }
            projects_data.append(project_data)

        # Get deletion history
        deletion_history = DeletedProjectHistory.query.order_by(
            DeletedProjectHistory.deleted_at.desc()
        ).limit(50).all()  # Show last 50 deletions

        return render_template('planner.html', 
                            projects=projects_data,
                            deletion_history=deletion_history)

    except Exception as e:
        app.logger.error(f"Error in planner view: {str(e)}")
        flash(f"Error loading planner data: {str(e)}", "danger")
        return render_template('planner.html', 
                            projects=[],
                            deletion_history=[])

@app.route('/api/production_history/<sap_id>')
def production_history(sap_id):
    try:
        # Get drawing number for this SAP ID
        drawing = MachineDrawing.query.filter_by(sap_id=sap_id).first()
        if not drawing:
            return jsonify({'error': 'SAP ID not found'}), 404

        # Get all completed logs for this drawing
        logs = OperatorLog.query.filter_by(
            drawing_number=drawing.drawing_number,
            status='Cycle Completed'
        ).order_by(OperatorLog.created_at.desc()).all()

        runs = []
        for log in logs:
            # Get associated project
            project = Project.query.filter_by(sap_id=sap_id).first()
            
            # Get quality check for this run
            quality_check = QualityCheck.query.filter_by(
                operator_log_id=log.id
            ).first()

            runs.append({
                'date': log.created_at.strftime('%Y-%m-%d'),
                'project_code': project.code if project else 'Unknown',
                'quantity': 1,  # Each log represents one piece
                'setup_time': log.setup_time,
                'cycle_time': log.cycle_time,
                'quality_status': quality_check.result if quality_check else 'N/A'
            })

        return jsonify({
            'sap_id': sap_id,
            'drawing_number': drawing.drawing_number,
            'runs': runs
        })

    except Exception as e:
        app.logger.error(f"Error getting production history: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/machine_shop', methods=['GET', 'POST'])
def machine_shop():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash("No file part", "danger")
            return redirect(request.url)

        file = request.files['file']
        if file.filename == '':
            flash("No selected file", "danger")
            return redirect(request.url)

        if file and allowed_file(file.filename):
            try:
                # Save file first
                filename = os.path.join(app.config['UPLOAD_FOLDER'], 'drawings.xlsx')
                file.save(filename)
                
                # Read Excel file
                try:
                    df = pd.read_excel(filename, engine='openpyxl')
                except Exception as excel_error:
                    app.logger.error(f"Error reading Excel with openpyxl: {str(excel_error)}")
                    try:
                        df = pd.read_excel(filename, engine='xlrd')
                    except Exception as xlrd_error:
                        app.logger.error(f"Error reading Excel with xlrd: {str(xlrd_error)}")
                        raise Exception("Unable to read Excel file. Please ensure it's a valid Excel file.")

                required_columns = ['drawing_number', 'sap_id']
                
                if not all(col in df.columns for col in required_columns):
                    flash('Invalid file format. Missing required columns.', 'error')
                    return redirect(request.url)
                
                success_count = 0
                duplicate_count = 0
                error_count = 0
                
                # Process the data
                for _, row in df.iterrows():
                    try:
                        drawing_number = str(row['drawing_number']).strip()
                        sap_id = str(row['sap_id']).strip()
                        
                        if not drawing_number or not sap_id:
                            error_count += 1
                            continue
                            
                        # Check if drawing already exists
                        existing_drawing = MachineDrawing.query.filter_by(drawing_number=drawing_number).first()
                        if existing_drawing:
                            duplicate_count += 1
                            continue
                            
                        drawing = MachineDrawing(
                            drawing_number=drawing_number,
                            sap_id=sap_id
                        )
                        db.session.add(drawing)
                        db.session.commit()
                        success_count += 1
                    except Exception as e:
                        db.session.rollback()
                        error_count += 1
                        app.logger.error(f"Error processing row: {str(e)}")
                
                status_message = f"Processed {success_count} drawings successfully. "
                if duplicate_count > 0:
                    status_message += f"{duplicate_count} duplicates skipped. "
                if error_count > 0:
                    status_message += f"{error_count} errors encountered."
                
                flash(status_message, "success" if error_count == 0 else "warning")
                
            except Exception as e:
                flash(f'Error processing file: {str(e)}', 'error')
            finally:
                # Clean up the uploaded file
                try:
                    if os.path.exists(filename):
                        os.remove(filename)
                except Exception as e:
                    app.logger.error(f"Error removing temporary file: {str(e)}")
    
    # Get all drawings with their project details
    drawings = []
    for drawing in MachineDrawing.query.all():
        project = Project.query.filter_by(sap_id=drawing.sap_id).first()
        drawing.project_code = project.code if project else None
        drawing.end_product = project.end_product if project else None
        drawings.append(drawing)
    
    # Get machine assignments
    machines = ['Machine 1', 'Machine 2', 'Machine 3']  # Example machines
    active_assignments = MachineAssignment.query.filter_by(status='Active').all()
    active_machines = [a.machine for a in active_assignments]
    
    # Build assignments dictionary
    assignments = {}
    for assignment in active_assignments:
        assignments[assignment.machine] = {
            'drawing_number': assignment.drawing_number,
            'quantity': assignment.quantity,
            'produced': assignment.produced,
            'start_time': assignment.start_time.strftime('%Y-%m-%d %H:%M:%S')
        }
    
    return render_template('machine_shop.html', 
                         drawings=drawings,
                         machines=machines,
                         active_machines=active_machines,
                         assignments=assignments)

@app.route('/assign_machine', methods=['POST'])
def assign_machine():
    try:
        machine = request.form.get('machine')
        drawing_number = request.form.get('drawing_number')
        quantity = request.form.get('quantity', type=int)
        
        if not machine or not drawing_number or not quantity:
            flash('Machine, drawing number, and quantity are required', 'error')
            return redirect(url_for('machine_shop'))
            
        # Validate drawing number exists
        drawing = MachineDrawing.query.filter_by(drawing_number=drawing_number).first()
        if not drawing:
            flash('Invalid drawing number', 'error')
            return redirect(url_for('machine_shop'))
            
        # Check if machine is already assigned
        existing_assignment = MachineAssignment.query.filter_by(
            machine=machine,
            status='Active'
        ).first()
        
        if existing_assignment:
            flash(f'Machine {machine} is already assigned to drawing {existing_assignment.drawing_number}', 'error')
            return redirect(url_for('machine_shop'))
            
        # Create new assignment
        assignment = MachineAssignment(
            machine=machine,
            drawing_number=drawing_number,
            quantity=quantity,
            status='Active'
        )
        db.session.add(assignment)
        db.session.commit()
        
        flash(f'Drawing {drawing_number} assigned to {machine} successfully', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error assigning machine: {str(e)}', 'error')
    
    return redirect(url_for('machine_shop'))

@app.route('/unassign_machine', methods=['POST'])
def unassign_machine():
    try:
        data = request.get_json()
        machine = data.get('machine')
        
        if not machine:
            return jsonify({'error': 'Machine is required'}), 400
            
        # Find and update assignment
        assignment = MachineAssignment.query.filter_by(
            machine=machine,
            status='Active'
        ).first()
        
        if assignment:
            assignment.status = 'Completed'
            db.session.commit()
            return jsonify({'message': 'Machine unassigned successfully'})
        else:
            return jsonify({'error': 'No active assignment found for this machine'}), 404
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/operator', methods=['GET', 'POST'])
def operator():
    try:
        if request.method == 'POST':
            action = request.form.get('action')
            drawing_number = request.form.get('drawing_number')
            batch_id = request.form.get('batch_id')
            operator_id = request.form.get('operator_id')
            
            if not all([action, drawing_number, batch_id, operator_id]):
                flash("Missing required fields", "danger")
                return redirect(url_for('operator'))
            
            # Get operator log
            operator_log = OperatorLog.query.filter_by(
                drawing_number=drawing_number,
                batch_number=batch_id
            ).first()
            
            # Create new operator log if it doesn't exist and action is setup_start
            if not operator_log and action == 'setup_start':
                # Get drawing details to link SAP ID
                drawing = MachineDrawing.query.filter_by(drawing_number=drawing_number).first()
                if not drawing:
                    flash("Drawing number not found in system", "danger")
                    return redirect(url_for('operator'))
                    
                # Get project details for planned quantity
                project = Project.query.filter_by(sap_id=drawing.sap_id).first()
                if not project:
                    flash("No active project found for this drawing", "danger")
                    return redirect(url_for('operator'))
                
                operator_log = OperatorLog(
                    drawing_number=drawing_number,
                    batch_number=batch_id,
                    operator_id=operator_id,
                    status='Pending',
                    planned_quantity=project.quantity,
                    completed_quantity=0,
                    rejected_quantity=0,
                    rework_quantity=0,
                    quality_status='Pending QC',
                    fpi_status='Pending',
                    production_hold=True,
                    sap_id=drawing.sap_id
                )
                db.session.add(operator_log)
                db.session.commit()
            elif not operator_log:
                flash("No production record found", "danger")
                return redirect(url_for('operator'))
                
            # Validate FPI status before allowing production
            if action in ['setup_start', 'cycle_start']:
                if operator_log.production_hold:
                    flash("Cannot start production - FPI required or failed", "danger")
                    return redirect(url_for('operator'))
                    
            # Handle different actions
            if action == 'setup_start':
                # Check if there's an incomplete operation
                active_log = OperatorLog.query.filter_by(
                    drawing_number=drawing_number
                ).filter(
                    OperatorLog.status.in_(['Setup Started', 'Setup Done', 'Cycle Started'])
                ).first()
                
                if active_log:
                    flash("There's an active operation for this drawing. Please complete or abort it first.", "danger")
                    return redirect(url_for('operator'))
                
                operator_log.setup_start = datetime.utcnow()
                operator_log.status = 'Setup Started'
                operator_log.operator_id = operator_id
                
            elif action == 'setup_done':
                if operator_log.status != 'Setup Started':
                    flash("Setup must be started first", "danger")
                    return redirect(url_for('operator'))
                    
                operator_log.setup_done = datetime.utcnow()
                operator_log.status = 'Setup Done'
                operator_log.setup_time = (operator_log.setup_done - operator_log.setup_start).total_seconds() / 60
                
            elif action == 'cycle_start':
                # Validate setup is complete
                if operator_log.status not in ['Setup Done', 'Cycle Completed']:
                    flash("Setup must be completed before starting cycle", "danger")
                    return redirect(url_for('operator'))
                    
                # Validate FPI status
                if operator_log.fpi_status != 'Pass' and operator_log.completed_quantity == 0:
                    flash("First piece must pass FPI before starting production", "danger")
                    return redirect(url_for('operator'))
                    
                operator_log.cycle_start = datetime.utcnow()
                operator_log.status = 'Cycle Started'
                
            elif action == 'cycle_done':
                if operator_log.status != 'Cycle Started':
                    flash("Cycle must be started first", "danger")
                    return redirect(url_for('operator'))
                    
                # Check if this completes the batch
                remaining_qty = operator_log.planned_quantity - operator_log.completed_quantity
                if remaining_qty <= 1:
                    flash("Last piece requires LPI before completion", "warning")
                    
                operator_log.cycle_done = datetime.utcnow()
                operator_log.status = 'Cycle Completed'
                operator_log.cycle_time = (operator_log.cycle_done - operator_log.cycle_start).total_seconds() / 60
                
            elif action == 'abort':
                abort_reason = request.form.get('abort_reason')
                if not abort_reason:
                    flash("Abort reason is required", "danger")
                    return redirect(url_for('operator'))
                    
                operator_log.status = 'Aborted'
                operator_log.abort_reason = abort_reason
                
            db.session.commit()
            flash(f"Operation {action.replace('_', ' ').title()} successfully", "success")
            
        # GET request - load active operations and available drawings
        active_ops = OperatorLog.query.filter(
            OperatorLog.status.in_(['Setup Started', 'Setup Done', 'Cycle Started'])
        ).all()
        
        # Get drawings that need FPI
        fpi_needed = OperatorLog.query.filter_by(
            fpi_status='Pending'
        ).all()
        
        # Get drawings ready for LPI
        lpi_ready = OperatorLog.query.filter(
            OperatorLog.fpi_status == 'Pass',
            OperatorLog.lpi_status.is_(None),
            OperatorLog.completed_quantity >= OperatorLog.planned_quantity - 1
        ).all()
        
        # Get all available drawings from MachineDrawing table
        available_drawings = MachineDrawing.query.join(Project, MachineDrawing.sap_id == Project.sap_id)\
            .filter(Project.is_deleted == False).all()
        
        # Get recent operations
        recent_logs = OperatorLog.query.order_by(OperatorLog.created_at.desc()).limit(10).all()
        
        # Get latest log for current status
        latest_log = OperatorLog.query.order_by(OperatorLog.created_at.desc()).first()
        
        return render_template('operator.html',
                            active_ops=active_ops,
                            fpi_needed=fpi_needed,
                            lpi_ready=lpi_ready,
                            available_drawings=available_drawings,
                            recent_logs=recent_logs,
                            latest_log=latest_log)
                            
    except Exception as e:
        app.logger.error(f"Error in operator route: {str(e)}")
        flash(f"An error occurred: {str(e)}", "danger")
        return redirect(url_for('operator'))

@app.route('/quality', methods=['GET', 'POST'])
def quality():
    try:
        if request.method == 'POST':
            # Get form data with better validation
            drawing_number = request.form.get('drawing_number', '').strip()
            check_type = request.form.get('check_type', '').strip()
            result = request.form.get('result', '').strip()
            rejection_reason = request.form.get('rejection_reason', '').strip()
            inspector_id = request.form.get('inspector_id', '').strip()
            inspection_station = request.form.get('inspection_station', '').strip()
            
            try:
                quantity_checked = int(request.form.get('quantity_checked', 0))
                if quantity_checked < 1:
                    raise ValueError("Quantity checked must be a positive integer")
            except ValueError as e:
                flash(str(e), "danger")
                return redirect(url_for('quality'))

            batch_id = request.form.get('batch_id', '').strip() or datetime.now().strftime('%Y%m%d%H%M%S')

            # Store form data in session to prevent resubmission
            if 'last_quality_submission' in session:
                last_submission = session['last_quality_submission']
                if (last_submission['drawing_number'] == drawing_number and
                    last_submission['check_type'] == check_type and
                    last_submission['batch_id'] == batch_id):
                    flash("This quality check was already submitted.", "warning")
                    return redirect(url_for('quality'))

            # Validate required fields
            if not all([drawing_number, check_type, result, inspector_id, inspection_station]):
                flash("Missing required fields", "danger")
                return redirect(url_for('quality'))

            # Get operator log and validate quantities
            operator_log = OperatorLog.query.filter_by(
                drawing_number=drawing_number,
                batch_number=batch_id
            ).first()

            if operator_log:
                if quantity_checked > operator_log.planned_quantity - operator_log.completed_quantity - operator_log.rejected_quantity:
                    flash("Quantity checked exceeds remaining pieces", "danger")
                    return redirect(url_for('quality'))
            else:
                flash("No production record found for this drawing and batch", "warning")

            # Validate check type
            valid_types = ['First Part', 'In Process', 'Last Part', 'Final']
            if check_type not in valid_types:
                flash("Invalid inspection type", "danger")
                return redirect(url_for('quality'))

            # Additional validation for First Part Inspection
            if check_type == 'First Part':
                # Check if this is actually the first piece
                previous_checks = QualityCheck.query.filter_by(
                    drawing_number=drawing_number,
                    batch_id=batch_id
                ).first()
                
                if previous_checks:
                    flash("First Part Inspection must be done before any other inspections", "danger")
                    return redirect(url_for('quality'))
                    
                # Validate no production has started
                if operator_log and operator_log.completed_quantity > 0:
                    flash("Cannot perform FPI after production has started", "danger")
                    return redirect(url_for('quality'))

            # Additional validation for Last Part Inspection
            if check_type == 'Last Part':
                # Validate FPI has passed
                if not operator_log or operator_log.fpi_status != 'Pass':
                    flash("Cannot perform LPI without a passed FPI", "danger")
                    return redirect(url_for('quality'))
                    
                # Validate this is truly the last piece
                remaining_qty = operator_log.planned_quantity - operator_log.completed_quantity
                if remaining_qty > quantity_checked:
                    flash("LPI must be performed on final pieces only", "danger")
                    return redirect(url_for('quality'))

            # Validate In Process inspection
            if check_type == 'In Process':
                # Check if FPI has passed
                if not operator_log or operator_log.fpi_status != 'Pass':
                    flash("Cannot perform In Process inspection without a passed FPI", "danger")
                    return redirect(url_for('quality'))

            if result not in ['Pass', 'Reject']:
                flash("Invalid result", "danger")
                return redirect(url_for('quality'))

            if result == 'Reject' and not rejection_reason:
                flash("Rejection reason is required when result is Reject", "danger")
                return redirect(url_for('quality'))

            try:
                # Calculate passed and rejected quantities
                quantity_passed = quantity_checked if result == 'Pass' else 0
                quantity_rejected = quantity_checked if result == 'Reject' else 0

                # Create quality check
                qc = QualityCheck(
                    drawing_number=drawing_number,
                    type=check_type,
                    result=result,
                    rejection_reason=rejection_reason if result == 'Reject' else '',
                    quantity_checked=quantity_checked,
                    quantity_passed=quantity_passed,
                    quantity_rejected=quantity_rejected,
                    operator_log_id=operator_log.id if operator_log else None,
                    status='Completed',
                    batch_id=batch_id,
                    inspector_id=inspector_id,
                    inspection_station=inspection_station
                )
                db.session.add(qc)

                # Update operator log quantities and status
                if operator_log:
                    if check_type == 'First Part':
                        operator_log.fpi_status = result
                        operator_log.fpi_timestamp = datetime.utcnow()
                        operator_log.fpi_inspector = inspector_id
                        
                        # Control production based on FPI result
                        if result == 'Pass':
                            operator_log.production_hold = False
                            operator_log.completed_quantity += quantity_passed
                            flash("FPI Passed - Production can proceed", "success")
                        else:
                            operator_log.production_hold = True
                            operator_log.quality_status = 'FPI Failed'
                            flash("FPI Failed - Production on hold", "warning")
                            
                    elif check_type == 'Last Part':
                        operator_log.lpi_status = result
                        operator_log.lpi_timestamp = datetime.utcnow()
                        operator_log.lpi_inspector = inspector_id
                        
                        if result == 'Pass':
                            operator_log.completed_quantity += quantity_passed
                            operator_log.quality_status = 'QC Pass'
                            flash("LPI Passed - Batch completed successfully", "success")
                        else:
                            # If LPI fails, reject entire batch
                            operator_log.rejected_quantity = operator_log.completed_quantity
                            operator_log.completed_quantity = 0
                            operator_log.quality_status = 'LPI Failed - Batch Rejected'
                            flash("LPI Failed - Entire batch rejected", "danger")
                    else:
                        # Normal in-process inspection
                        operator_log.completed_quantity += quantity_passed
                        operator_log.rejected_quantity += quantity_rejected
                        
                        if quantity_rejected > 0:
                            operator_log.quality_status = 'QC Fail'
                        elif operator_log.completed_quantity == operator_log.planned_quantity:
                            operator_log.quality_status = 'QC Pass'
                        else:
                            operator_log.quality_status = 'Pending QC'

                # Handle rework queue if pieces are rejected
                if quantity_rejected > 0:
                    rework = ReworkQueue.query.filter_by(
                        drawing_number=drawing_number,
                        batch_id=batch_id,
                        type=check_type
                    ).first()
                    
                    if rework:
                        rework.remaining_quantity += quantity_rejected
                        rework.rejection_reason = rejection_reason
                        if rework.status == 'Completed':
                            rework.status = 'In Progress'
                    else:
                        rework = ReworkQueue(
                            drawing_number=drawing_number,
                            batch_id=batch_id,
                            initial_quantity=quantity_rejected,
                            remaining_quantity=quantity_rejected,
                            type=check_type,
                            rejection_reason=rejection_reason,
                            priority=5 if check_type in ['First Part', 'Last Part'] else 3,
                            created_at=datetime.utcnow(),
                            status='Pending',
                            rework_instructions=f"Failed {check_type}: {rejection_reason}"
                        )
                        db.session.add(rework)
                    
                    if operator_log:
                        operator_log.rework_quantity += quantity_rejected

                db.session.commit()

                # Store submission in session
                session['last_quality_submission'] = {
                    'drawing_number': drawing_number,
                    'check_type': check_type,
                    'batch_id': batch_id,
                    'timestamp': datetime.now().timestamp()
                }

                flash(f"Quality check recorded successfully! {check_type} - {result} ({quantity_checked} pieces)", "success")
                return redirect(url_for('quality'))

            except IntegrityError:
                db.session.rollback()
                flash("A quality check for this drawing, type and batch already exists.", "warning")
                return redirect(url_for('quality'))
            except Exception as e:
                db.session.rollback()
                app.logger.error(f"Error in quality check: {str(e)}")
                flash(f"Error recording quality check: {str(e)}", "danger")
                return redirect(url_for('quality'))

        # GET request handling
        try:
            page = request.args.get('page', 1, type=int)
            per_page = 10
            
            # Get quality checks with related data
            checks = QualityCheck.query.order_by(
                QualityCheck.timestamp.desc()
            ).paginate(page=page, per_page=per_page, error_out=False)

            # Get active drawings (with pending QC or in rework)
            active_logs = OperatorLog.query.filter(
                OperatorLog.quality_status.in_(['Pending QC', 'QC Fail', 'In Rework'])
            ).all()
            
            active_drawings = sorted(list(set(log.drawing_number for log in active_logs)))

            # Get rework queue with detailed status
            rework_queue = ReworkQueue.query.filter(
                ReworkQueue.remaining_quantity > 0
            ).order_by(
                ReworkQueue.priority.desc(),
                ReworkQueue.created_at.asc()
            ).all()
            
            # Enhance rework queue with history and metrics
            for item in rework_queue:
                # Get quality check history
                item.history = QualityCheck.query.filter_by(
                    drawing_number=item.drawing_number,
                    batch_id=item.batch_id
                ).order_by(QualityCheck.timestamp.desc()).all()
                
                # Calculate rework metrics
                total_checked = sum(check.quantity_checked for check in item.history)
                total_passed = sum(check.quantity_passed for check in item.history)
                item.rework_success_rate = (total_passed / total_checked * 100) if total_checked > 0 else 0

            return render_template('quality.html',
                                checks=checks,
                                active_drawings=active_drawings,
                                rework_queue=rework_queue)

        except Exception as e:
            app.logger.error(f"Error loading quality page: {str(e)}")
            flash(f"Error loading quality data: {str(e)}", "danger")
            return render_template('quality.html', checks=None, active_drawings=[], rework_queue=[])

    except Exception as e:
        app.logger.error(f"Unexpected error in quality route: {str(e)}")
        flash(f"An unexpected error occurred: {str(e)}", "danger")
        return render_template('quality.html', checks=None, active_drawings=[], rework_queue=[])

@app.route('/digital_twin')
def digital_twin():
    try:
        # Get all projects
        projects = Project.query.all()
        projects_data = {}
        current_date = datetime.now().date()

        # Initialize OEE metrics
        total_planned_production_time = 0
        total_actual_production_time = 0
        total_good_pieces = 0
        total_produced_pieces = 0
        ideal_cycle_time = 0  # Will be calculated from standards

        # Initialize projects data structure
        for project in projects:
            projects_data[project.code] = {
                'code': project.code,
                'name': project.name,
                'end_products': {},
                'completion_percentage': 0,
                'total_products': 0,
                'completed_products': 0,
                'oee_metrics': {
                    'availability': 0,
                    'performance': 0,
                    'quality': 0,
                    'oee': 0
                }
            }
            
            # Calculate ideal cycle time from standards
            ideal_cycle_time = min(ideal_cycle_time, project.cycle_time_std) if ideal_cycle_time > 0 else project.cycle_time_std
            
            # Initialize end product data using SAP ID as key
            product_data = {
                'name': project.end_product,
                'sap_id': project.sap_id,
                'total_qty': project.quantity,
                'completed_qty': 0,
                'rework_qty': 0,
                'completion_date': project.completion_date,
                'standard_setup_time': project.setup_time_std,
                'standard_cycle_time': project.cycle_time_std,
                'actual_setup_time': 0,
                'actual_cycle_time': 0,
                'setup_time_status': 'good',
                'cycle_time_status': 'good',
                'on_time': True,
                'completion_percentage': 0,
                'drawing_number': None
            }
            projects_data[project.code]['end_products'][project.sap_id] = product_data

        # Process operator logs for OEE calculation
        completed_logs = OperatorLog.query.filter_by(status='Cycle Completed').all()
        for log in completed_logs:
            if log.setup_time:
                total_planned_production_time += log.setup_time
            if log.cycle_time:
                total_actual_production_time += log.cycle_time
                total_produced_pieces += 1

            # Check quality for good pieces
            quality_check = QualityCheck.query.filter_by(
                operator_log_id=log.id
            ).first()
            if quality_check and quality_check.result == 'Pass':
                total_good_pieces += 1

        # Calculate OEE metrics
        if total_planned_production_time > 0 and ideal_cycle_time > 0:
            availability = (total_actual_production_time / total_planned_production_time) * 100
            performance = ((ideal_cycle_time * total_produced_pieces) / total_actual_production_time) * 100 if total_actual_production_time > 0 else 0
            quality = (total_good_pieces / total_produced_pieces) * 100 if total_produced_pieces > 0 else 0
            oee = (availability * performance * quality) / 10000  # Divide by 10000 as each metric is in percentage

            # Add OEE metrics to response
            oee_metrics = {
                'availability': round(availability, 2),
                'performance': round(performance, 2),
                'quality': round(quality, 2),
                'oee': round(oee, 2)
            }
        else:
            oee_metrics = {
                'availability': 0,
                'performance': 0,
                'quality': 0,
                'oee': 0
            }

        # Get drawing numbers for each SAP ID
        drawings = MachineDrawing.query.all()
        sap_to_drawing = {}
        for drawing in drawings:
            sap_to_drawing[drawing.sap_id] = drawing.drawing_number
            # Update drawing number in projects data
            for project in projects_data.values():
                if drawing.sap_id in project['end_products']:
                    project['end_products'][drawing.sap_id]['drawing_number'] = drawing.drawing_number

        # Process operator logs
        completed_logs = OperatorLog.query.filter_by(status='Cycle Completed').all()
        for log in completed_logs:
            # Find SAP ID for this drawing
            drawing = MachineDrawing.query.filter_by(drawing_number=log.drawing_number).first()
            if not drawing:
                continue

            # Find project and product
            for project_data in projects_data.values():
                if drawing.sap_id in project_data['end_products']:
                    product = project_data['end_products'][drawing.sap_id]
                    product['completed_qty'] += 1
                    if log.setup_time:
                        product['actual_setup_time'] = max(product['actual_setup_time'], log.setup_time)
                    if log.cycle_time:
                        product['actual_cycle_time'] = max(product['actual_cycle_time'], log.cycle_time)

        # Process rework queue
        rework_queue = ReworkQueue.query.all()
        for rework in rework_queue:
            # Find SAP ID for this drawing
            drawing = MachineDrawing.query.filter_by(drawing_number=rework.drawing_number).first()
            if not drawing:
                continue

            # Update rework quantity
            for project_data in projects_data.values():
                if drawing.sap_id in project_data['end_products']:
                    project_data['end_products'][drawing.sap_id]['rework_qty'] = rework.remaining_quantity

        # Calculate statistics
        total_projects = len(projects_data)
        completed_projects = 0
        delayed_projects = 0
        in_progress_projects = 0

        for project_code, project in projects_data.items():
            total_complete = 0
            total_products = len(project['end_products'])
            
            if total_products == 0:
                continue
                
            for product in project['end_products'].values():
                # Calculate completion percentage
                if product['total_qty'] > 0:
                    product['completion_percentage'] = (product['completed_qty'] / product['total_qty']) * 100
                
                # Check if product is complete
                if product['completed_qty'] >= product['total_qty']:
                    total_complete += 1
                
                # Update time performance status
                if product['actual_setup_time'] > 0:
                    product['setup_time_status'] = 'good' if product['actual_setup_time'] <= product['standard_setup_time'] else 'bad'
                if product['actual_cycle_time'] > 0:
                    product['cycle_time_status'] = 'good' if product['actual_cycle_time'] <= product['standard_cycle_time'] else 'bad'
                
                # Check if on time
                try:
                    completion_date = datetime.strptime(product['completion_date'], '%Y-%m-%d').date()
                    product['on_time'] = current_date <= completion_date
                except (ValueError, TypeError):
                    product['on_time'] = True

            # Update project statistics
            project['total_products'] = total_products
            project['completed_products'] = total_complete
            project['completion_percentage'] = (total_complete / total_products * 100) if total_products > 0 else 0

            # Update project counters
            if project['completion_percentage'] == 100:
                completed_projects += 1
            elif project['completion_percentage'] > 0:
                in_progress_projects += 1
                if any(not p['on_time'] for p in project['end_products'].values()):
                    delayed_projects += 1

        # Prepare chart data
        time_performance_labels = []
        setup_time_data = []
        cycle_time_data = []
        quality_data = [0, 0, 0, 0]  # Completed, In Progress, Rework, Pending

        for project in projects_data.values():
            for product in project['end_products'].values():
                if product['completed_qty'] > 0:
                    time_performance_labels.append(product['drawing_number'] or product['sap_id'])
                    setup_time_data.append(product['actual_setup_time'])
                    cycle_time_data.append(product['actual_cycle_time'])

                # Update quality data
                if product['completion_percentage'] == 100:
                    quality_data[0] += 1
                elif product['completion_percentage'] > 0:
                    quality_data[1] += 1
                if product['rework_qty'] > 0:
                    quality_data[2] += 1
                if product['completion_percentage'] == 0:
                    quality_data[3] += 1

        return render_template('digital_twin.html',
                            projects=list(projects_data.values()),
                            total_projects=total_projects,
                            completed_projects=completed_projects,
                            in_progress_projects=in_progress_projects,
                            delayed_projects=delayed_projects,
                            time_performance_labels=time_performance_labels,
                            setup_time_data=setup_time_data,
                            cycle_time_data=cycle_time_data,
                            quality_data=quality_data,
                            oee_metrics=oee_metrics)

    except Exception as e:
        app.logger.error(f"Error in digital twin: {str(e)}")
        flash(f"Error loading digital twin dashboard: {str(e)}", "danger")
        return render_template('digital_twin.html', 
                            projects=[],
                            total_projects=0,
                            completed_projects=0,
                            in_progress_projects=0,
                            delayed_projects=0,
                            time_performance_labels=[],
                            setup_time_data=[],
                            cycle_time_data=[],
                            quality_data=[0, 0, 0, 0],
                            oee_metrics={'availability': 0, 'performance': 0, 'quality': 0, 'oee': 0})

@app.route('/export')
def export_report():
    try:
        logs = OperatorLog.query.all()
        checks = QualityCheck.query.all()

        # Create DataFrames
        df_logs = pd.DataFrame([{
            "Drawing": l.drawing_number,
            "Setup Start": l.setup_start,
            "Setup Done": l.setup_done,
            "Cycle Start": l.cycle_start,
            "Cycle Done": l.cycle_done,
            "Status": l.status
        } for l in logs])

        df_checks = pd.DataFrame([{
            "Drawing": c.drawing_number,
            "Type": c.type,
            "Result": c.result,
            "Remarks": c.remarks,
            "Timestamp": c.timestamp
        } for c in checks])

        # Create Excel file
        output_path = os.path.join(app.config['UPLOAD_FOLDER'], 'report.xlsx')
        with pd.ExcelWriter(output_path, engine='xlsxwriter') as writer:
            df_logs.to_excel(writer, sheet_name="Operator Logs", index=False)
            df_checks.to_excel(writer, sheet_name="Quality Checks", index=False)
        
        return send_file(output_path, as_attachment=True)
    except Exception as e:
        flash(f"Error generating report: {str(e)}", "danger")
        return redirect(url_for('digital_twin'))

@app.route('/manager')
def manager_dashboard():
    try:
        # Get all drawings with their latest status
        drawings = db.session.query(MachineDrawing).all()
        
        # Get rework queue
        rework_queue = ReworkQueue.query.all()
        
        # Get recently deleted projects/products
        deleted_items = DeletedProjectHistory.query.order_by(
            DeletedProjectHistory.deleted_at.desc()
        ).limit(10).all()
        
        # For each drawing, get its project details and latest status
        for drawing in drawings:
            # Get associated project through SAP ID (including deleted ones)
            project = Project.query.filter_by(sap_id=drawing.sap_id).first()
            drawing.project = project
            
            # Get latest status
            latest_log = OperatorLog.query.filter_by(
                drawing_number=drawing.drawing_number
            ).order_by(OperatorLog.id.desc()).first()
            
            if latest_log:
                status_map = {
                    'Setup Started': ('warning', 'Setup In Progress'),
                    'Setup Done': ('info', 'Ready for Production'),
                    'Cycle Started': ('primary', 'In Production'),
                    'Cycle Completed': ('success', 'Completed'),
                    'Aborted': ('danger', 'Aborted')
                }
                drawing.latest_status = {
                    'status_color': status_map.get(latest_log.status, ('secondary', 'Unknown'))[0],
                    'status_text': status_map.get(latest_log.status, ('secondary', 'Unknown'))[1]
                }
            else:
                drawing.latest_status = None

            # Add deletion status if project is deleted
            if project and project.is_deleted:
                drawing.deletion_info = {
                    'deleted_at': project.deleted_at,
                    'type': 'Project' if Project.query.filter_by(code=project.code, is_deleted=True).count() > 1 else 'End Product'
                }
            else:
                drawing.deletion_info = None

        return render_template('manager.html',
                            drawings=drawings,
                            rework_queue=rework_queue,
                            deleted_items=deleted_items)
                            
    except Exception as e:
        app.logger.error(f"Error in manager dashboard: {str(e)}")
        flash(f"Error loading manager dashboard: {str(e)}", "danger")
        return render_template('manager.html', 
                            drawings=[], 
                            rework_queue=[],
                            deleted_items=[])

@app.route('/upload_production_plan', methods=['POST'])
def upload_production_plan():
    if 'file' not in request.files:
        flash('No file uploaded', 'error')
        return redirect(url_for('manager_dashboard'))
    
    file = request.files['file']
    if file.filename == '':
        flash('No file selected', 'error')
        return redirect(url_for('manager_dashboard'))
    
    if file and allowed_file(file.filename):
        try:
            # Save file first
            filename = os.path.join(app.config['UPLOAD_FOLDER'], 'production_plan.xlsx')
            file.save(filename)
            
            # Read Excel file with explicit engine specification
            try:
                df = pd.read_excel(filename, engine='openpyxl')
            except Exception as excel_error:
                app.logger.error(f"Error reading Excel with openpyxl: {str(excel_error)}")
                try:
                    # Try alternative Excel engine if openpyxl fails
                    df = pd.read_excel(filename, engine='xlrd')
                except Exception as xlrd_error:
                    app.logger.error(f"Error reading Excel with xlrd: {str(xlrd_error)}")
                    raise Exception("Unable to read Excel file. Please ensure it's a valid Excel file.")

            required_columns = ['project_code', 'project_name', 'end_product', 'sap_id', 'qty', 'completion_date', 'st', 'ct']
            
            if not all(col in df.columns for col in required_columns):
                flash('Invalid file format. Missing required columns.', 'error')
                return redirect(url_for('manager_dashboard'))
            
            # Process the data
            for _, row in df.iterrows():
                try:
                    project = Project(
                        code=str(row['project_code']).strip(),
                        name=str(row['project_name']).strip(),
                        end_product=str(row['end_product']).strip(),
                        sap_id=str(row['sap_id']).strip(),
                        quantity=int(row['qty']),
                        completion_date=pd.to_datetime(row['completion_date']).strftime('%Y-%m-%d'),
                        setup_time_std=float(row['st']),
                        cycle_time_std=float(row['ct'])
                    )
                    db.session.add(project)
                    db.session.commit()
                except IntegrityError:
                    db.session.rollback()
                except Exception as e:
                    db.session.rollback()
                    app.logger.error(f"Error processing row: {str(e)}")
            
            flash('Production plan uploaded successfully', 'success')
            
        except Exception as e:
            flash(f'Error processing file: {str(e)}', 'error')
        finally:
            # Clean up the uploaded file
            try:
                if os.path.exists(filename):
                    os.remove(filename)
            except Exception as e:
                app.logger.error(f"Error removing temporary file: {str(e)}")
            
    return redirect(url_for('manager_dashboard'))

@app.route('/upload_drawings', methods=['POST'])
def upload_drawings():
    if 'file' not in request.files:
        flash('No file uploaded', 'error')
        return redirect(url_for('manager_dashboard'))
    
    file = request.files['file']
    if file.filename == '':
        flash('No file selected', 'error')
        return redirect(url_for('manager_dashboard'))
    
    if file and allowed_file(file.filename):
        try:
            # Save file first
            filename = os.path.join(app.config['UPLOAD_FOLDER'], 'drawings.xlsx')
            file.save(filename)
            
            # Read Excel file with explicit engine specification
            try:
                df = pd.read_excel(filename, engine='openpyxl')
            except Exception as excel_error:
                app.logger.error(f"Error reading Excel with openpyxl: {str(excel_error)}")
                try:
                    # Try alternative Excel engine if openpyxl fails
                    df = pd.read_excel(filename, engine='xlrd')
                except Exception as xlrd_error:
                    app.logger.error(f"Error reading Excel with xlrd: {str(xlrd_error)}")
                    raise Exception("Unable to read Excel file. Please ensure it's a valid Excel file.")

            required_columns = ['drawing_number', 'sap_id']
            
            if not all(col in df.columns for col in required_columns):
                flash('Invalid file format. Missing required columns.', 'error')
                return redirect(url_for('manager_dashboard'))
            
            success_count = 0
            duplicate_count = 0
            error_count = 0
            
            # Process the data
            for _, row in df.iterrows():
                try:
                    drawing_number = str(row['drawing_number']).strip()
                    sap_id = str(row['sap_id']).strip()
                    
                    if not drawing_number or not sap_id:
                        error_count += 1
                        continue
                            
                    # Check if drawing already exists
                    existing_drawing = MachineDrawing.query.filter_by(drawing_number=drawing_number).first()
                    if existing_drawing:
                        duplicate_count += 1
                        continue
                            
                    drawing = MachineDrawing(
                        drawing_number=drawing_number,
                        sap_id=sap_id
                    )
                    db.session.add(drawing)
                    db.session.commit()
                    success_count += 1
                except Exception as e:
                    db.session.rollback()
                    error_count += 1
                    app.logger.error(f"Error processing row: {str(e)}")
            
            status_message = f"Processed {success_count} drawings successfully. "
            if duplicate_count > 0:
                status_message += f"{duplicate_count} duplicates skipped. "
            if error_count > 0:
                status_message += f"{error_count} errors encountered."
            
            flash(status_message, "success" if error_count == 0 else "warning")
            
        except Exception as e:
            flash(f'Error processing file: {str(e)}', 'error')
        finally:
            # Clean up the uploaded file
            try:
                if os.path.exists(filename):
                    os.remove(filename)
            except Exception as e:
                app.logger.error(f"Error removing temporary file: {str(e)}")
            
    return redirect(url_for('manager_dashboard'))

@app.route('/delete_project/<project_code>', methods=['POST'])
def delete_project(project_code):
    try:
        # Find all projects with this code
        projects = Project.query.filter_by(code=project_code).all()
        
        if not projects:
            return jsonify({'error': 'Project not found'}), 404

        deletion_time = datetime.utcnow()
        reason = request.form.get('reason', '')

        # Create deletion history records
        for project in projects:
            history = DeletedProjectHistory(
                project_code=project.code,
                project_name=project.name,
                end_product=project.end_product,
                sap_id=project.sap_id,
                batch_number=project.batch_number,
                planned_quantity=project.quantity,
                actual_quantity=project.actual_quantity,
                deletion_type='project',
                completion_date=project.completion_date,
                reason=reason,
                deleted_at=deletion_time
            )
            db.session.add(history)
            
            # Mark project as deleted
            project.is_deleted = True
            project.deleted_at = deletion_time

        db.session.commit()
        return jsonify({'message': 'Project deleted successfully'})

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/delete_end_product', methods=['POST'])
def delete_end_product():
    try:
        sap_id = request.form.get('sap_id')
        batch_number = request.form.get('batch_number')
        reason = request.form.get('reason', '')

        if not sap_id or not batch_number:
            return jsonify({'error': 'SAP ID and batch number are required'}), 400

        try:
            batch_number = int(batch_number)
        except ValueError:
            return jsonify({'error': 'Invalid batch number format'}), 400

        # Find the specific end product
        project = Project.query.filter_by(
            sap_id=sap_id,
            batch_number=batch_number,
            is_deleted=False
        ).first()

        if not project:
            # Try to find if it exists but is already deleted
            deleted_project = Project.query.filter_by(
                sap_id=sap_id,
                batch_number=batch_number,
                is_deleted=True
            ).first()
            
            if deleted_project:
                return jsonify({'error': 'This end product has already been deleted'}), 400
            else:
                return jsonify({'error': f'End product not found with SAP ID {sap_id} and batch {batch_number}'}), 404

        deletion_time = datetime.utcnow()

        # Create deletion history record
        history = DeletedProjectHistory(
            project_code=project.code,
            project_name=project.name,
            end_product=project.end_product,
            sap_id=project.sap_id,
            batch_number=project.batch_number,
            planned_quantity=project.quantity,
            actual_quantity=project.actual_quantity,
            deletion_type='end_product',
            completion_date=project.completion_date,
            reason=reason,
            deleted_at=deletion_time
        )
        db.session.add(history)

        # Mark project as deleted
        project.is_deleted = True
        project.deleted_at = deletion_time

        db.session.commit()
        return jsonify({'message': 'End product deleted successfully'})

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error deleting end product: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/get_deletion_details/<identifier>')
def get_deletion_details(identifier):
    try:
        # First try to find it as a project code
        projects = Project.query.filter_by(code=identifier, is_deleted=False).all()
        if projects:
            # It's a project code
            first_project = projects[0]
            return jsonify({
                'type': 'project',
                'value': identifier,
                'details': {
                    'name': first_project.name,
                    'batch_count': len(projects)
                }
            })
        
        # Try to find it as a SAP ID
        project = Project.query.filter_by(
            sap_id=identifier.split('-')[0],  # Handle SAP ID with optional batch number
            is_deleted=False
        ).first()
        
        if project:
            # Check if batch number was provided
            parts = identifier.split('-')
            batch_number = int(parts[1]) if len(parts) > 1 else project.batch_number
            
            # Find specific batch
            batch = Project.query.filter_by(
                sap_id=parts[0],
                batch_number=batch_number,
                is_deleted=False
            ).first()
            
            if batch:
                return jsonify({
                    'type': 'end_product',
                    'value': f"{batch.sap_id}-{batch.batch_number}",
                    'details': {
                        'end_product': batch.end_product,
                        'batch_number': batch.batch_number
                    }
                })
        
        return jsonify({'error': 'No active project or end product found with this identifier'}), 404

    except Exception as e:
        app.logger.error(f"Error getting deletion details: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/drawing_details/<drawing_number>')
def get_drawing_details(drawing_number):
    try:
        # Get the latest operator log for this drawing
        operator_log = OperatorLog.query.filter_by(
            drawing_number=drawing_number
        ).order_by(OperatorLog.id.desc()).first()
        
        if not operator_log:
            return jsonify({
                'error': 'No production record found for this drawing'
            }), 404
        
        return jsonify({
            'drawing_number': operator_log.drawing_number,
            'batch_number': operator_log.batch_number,
            'planned_quantity': operator_log.planned_quantity,
            'completed_quantity': operator_log.completed_quantity,
            'rejected_quantity': operator_log.rejected_quantity,
            'rework_quantity': operator_log.rework_quantity,
            'quality_status': operator_log.quality_status
        })
        
    except Exception as e:
        app.logger.error(f"Error fetching drawing details: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/start_production', methods=['POST'])
def start_production():
    try:
        drawing_number = request.form.get('drawing_number')
        batch_id = request.form.get('batch_id')
        operator_id = request.form.get('operator_id')
        
        if not all([drawing_number, batch_id, operator_id]):
            flash("Missing required fields", "danger")
            return redirect(url_for('operator'))
            
        # Get operator log
        operator_log = OperatorLog.query.filter_by(
            drawing_number=drawing_number,
            batch_number=batch_id
        ).first()
        
        if not operator_log:
            flash("No production record found", "danger")
            return redirect(url_for('operator'))
            
        # Check FPI status
        if operator_log.production_hold:
            if operator_log.fpi_status != 'Pass':
                flash("Cannot start production without passing FPI", "danger")
                return redirect(url_for('operator'))
                
        # Check if this is a new drawing for the operator
        last_operation = OperatorLog.query.filter_by(
            drawing_number=drawing_number,
            operator_id=operator_id,
            status='Cycle Completed'
        ).order_by(OperatorLog.cycle_done.desc()).first()
        
        setup_required = True
        if last_operation:
            # If operator has completed this drawing within last 24 hours, no setup needed
            if last_operation.cycle_done and \
               (datetime.utcnow() - last_operation.cycle_done).total_seconds() < 86400:
                setup_required = False
        
        if setup_required:
            operator_log.status = 'Setup Required'
            flash("Setup required before starting production", "warning")
        else:
            operator_log.status = 'Ready for Production'
            flash("Production can begin", "success")
            
        operator_log.operator_id = operator_id
        db.session.commit()
        
        return redirect(url_for('operator'))
        
    except Exception as e:
        app.logger.error(f"Error starting production: {str(e)}")
        flash(f"Error starting production: {str(e)}", "danger")
        return redirect(url_for('operator'))

if __name__ == '__main__':
    app.run(debug=True)