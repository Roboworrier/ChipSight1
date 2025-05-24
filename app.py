# ChipSight - Copyright (c) 2025 Diwakar Singh. 
# Licensed under MIT for open-source use (see LICENSE) or 
# COMPANY_LICENSE.md for proprietary use by Addverb Technologies Ltd.
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, send_file
import pandas as pd
import os
from datetime import datetime
from werkzeug.utils import secure_filename
import random
import io
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'
socketio = SocketIO(app)

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'xlsx', 'xls'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Existing machines list
machines = ["Haas", "Pinacho", "Leadwell", "SJE10LM", "VMC2", "VMC4", "CNC5", "Lathe"]

# Store bots; each bot may now have 'components' or be a single component bot for backward compatibility
bots = []

# Current assignments: key = bot_id or bot_id_componentName; value = assignment details
assignments = {}

# OEE data: parts produced count by machine
oee_data = {machine: 0 for machine in machines}

# Completed assignments
completed_assignments = {}

shifts = {
    'morning': {"start": "08:00", "end": "16:00", "workers": 4},
    'evening': {"start": "16:00", "end": "00:00", "workers": 3}
}

QUALITY_BATCH_LIMIT = 10
quality_inspection_batches = {}  # key: bot_id or bot_id_component, value: list of pass/fail
pending_confirmation_bots = set()

# ----- Helpers -----

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def calculate_oee(machine_name):
    count = oee_data.get(machine_name)
    if not isinstance(count, (int, float)):
        return None
    availability = min(1, count / 20)
    performance = 0.85
    quality = 0.98
    return availability * performance * quality

def get_live_status():
    return {
        'running': len(assignments),
        'idle': len(machines) - len(assignments),
        'completed': len(completed_assignments)
    }

def get_machine_status(machine_name):
    return "Running" if any(machine_name == a['machine'] for a in assignments.values()) else "Idle"

@app.context_processor
def utility_processor():
    return dict(get_machine_status=get_machine_status)

@app.context_processor
def inject_now():
    return {'now': datetime.now()}

# ----- SocketIO -----
@socketio.on('status_update')
def handle_status_update(data):
    emit('update_machines', {'data': get_live_status()}, broadcast=True)

# ----- Routes -----

@app.route('/')
def home():
    return redirect(url_for('planner'))

@app.route('/planner', methods=['GET', 'POST'])
def planner():
    global bots
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file selected', 'error')
            return redirect(request.url)

        file = request.files['file']
        if file.filename == '':
            flash('No selected file', 'error')
            return redirect(request.url)

        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)

            try:
                df = pd.read_excel(filepath)
                # Support both single-component and component-level import

                # Required columns for old single-component format
                old_required = ['bot_id', 'cycle_time', 'completion_date', 'quantity', 'machine', 'tool']
                # Required columns for component-level: expect bot_id, component, cycle_time, completion_date, quantity, machine, tool
                new_required = ['bot_id', 'component', 'cycle_time', 'completion_date', 'quantity', 'machine', 'tool']

                # If new component-level columns exist, use component-level import
                if all(col in df.columns for col in new_required):
                    # Parse component-level bots
                    # Group by bot_id, gather components per bot_id
                    grouped = df.groupby('bot_id')
                    new_bots = []
                    for bot_id, group in grouped:
                        components = []
                        for _, row in group.iterrows():
                            comp_data = {
                                "component": row['component'],
                                "cycle_time": row['cycle_time'],
                                "completion_date": row['completion_date'],
                                "quantity": int(row['quantity']),
                                "produced": 0,
                                "machine": row['machine'],
                                "tool": row['tool'],
                                "status": "Pending",
                                "completed_time": None
                            }
                            components.append(comp_data)
                        bot_data = {
                            "bot_id": bot_id,
                            "components": components,
                            "status": "Pending"  # overall bot status (calculated later)
                        }
                        new_bots.append(bot_data)
                    # Assign initial machines to assignments for each component if not already assigned
                    for bot in new_bots:
                        for comp in bot['components']:
                            # Assign if machine not busy
                            if not any(a['machine'] == comp['machine'] for a in assignments.values()):
                                assign_key = f"{bot['bot_id']}_{comp['component']}"
                                assignments[assign_key] = {
                                    "machine": comp['machine'],
                                    "start_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                    "status": "Running"
                                }
                                comp['status'] = 'Running'
                                socketio.emit('status_update')
                    bots.extend(new_bots)
                    flash(f'Successfully imported {len(new_bots)} component-level bots', 'success')

                elif all(col in df.columns for col in old_required):
                    # Old format: single-component bots
                    new_bots = []
                    for _, row in df.iterrows():
                        bot_data = {
                            "bot_id": row['bot_id'],
                            "cycle_time": row['cycle_time'],
                            "completion_date": row['completion_date'],
                            "quantity": int(row['quantity']),
                            "produced": 0,
                            "machine": row['machine'],
                            "tool": row['tool'],
                            "status": "Pending",
                            "completed_time": None
                        }
                        new_bots.append(bot_data)
                        if not any(a['machine'] == row['machine'] for a in assignments.values()):
                            assignments[row['bot_id']] = {
                                "machine": row['machine'],
                                "start_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                "status": "Running"
                            }
                            socketio.emit('status_update')
                    bots.extend(new_bots)
                    flash(f'Successfully imported {len(new_bots)} bots', 'success')
                else:
                    flash('Invalid Excel format - missing required columns', 'error')
            except Exception as e:
                flash(f'Error processing file: {str(e)}', 'error')
            finally:
                if os.path.exists(filepath):
                    os.remove(filepath)
        else:
            flash('Allowed file types are: xlsx, xls', 'error')

    return render_template('planner.html', bots=bots, assignments=assignments)

from flask import Flask, render_template, request, redirect, url_for
from datetime import datetime

app = Flask(__name__)

# Existing bot data list - keep your current bots data and logic as is
bots = [
    # Example bot dicts (keep your actual data loading logic)
    {'bot_id': 'B001', 'cycle_time': 15, 'completion_date': '2025-05-30', 'quantity': 50,
     'produced': 50, 'machine': 'M1', 'tool': 'T1', 'status': 'Completed', 'completed_time': '2025-05-24 16:00'},
    # Add your existing bots here
]

# Example bot projects with multiple components
bot_projects = [
    {
        'name': 'Tracker',
        'components': [
            {'name': 'Legs', 'status': 'Completed'},
            {'name': 'Head', 'status': 'In Progress'},
            {'name': 'Base Frame', 'status': 'Pending'}
        ],
        'status': ''
    },
    {
        'name': 'Scout',
        'components': [
            {'name': 'Camera', 'status': 'Completed'},
            {'name': 'Processor', 'status': 'Completed'}
        ],
        'status': ''
    }
]

def aggregate_project_status(project):
    statuses = [c['status'] for c in project['components']]
    if all(s == 'Completed' for s in statuses):
        return 'Completed'
    elif any(s == 'In Progress' for s in statuses):
        return 'In Progress'
    else:
        return 'Pending'

@app.route('/', methods=['GET', 'POST'])
def planner_dashboard():
    if request.method == 'POST':
        # Your existing file upload & processing logic goes here
        # e.g. saving file, parsing new bots, etc.
        pass

    # Update project status for rendering
    for project in bot_projects:
        project['status'] = aggregate_project_status(project)

    return render_template('planner_dashboard.html', bots=bots, bot_projects=bot_projects)

@app.route('/delete/<bot_id>')
def delete_bot(bot_id):
    global bots
    bots = [b for b in bots if b['bot_id'] != bot_id]
    return redirect(url_for('planner_dashboard'))


if __name__ == '__main__':
    app.run(debug=True)



@app.route('/operator', methods=['GET', 'POST'])
def operator():
    if request.method == 'POST':
        bot_id = request.form['bot_id']
        component = request.form.get('component')  # Optional for old format
        result = request.form.get('quality_result')  # 'pass' or 'fail'

        # Find bot (component-level or single)
        bot = next((b for b in bots if b['bot_id'] == bot_id), None)
        if not bot:
            flash(f'Bot {bot_id} not found', 'error')
            return redirect(request.url)

        # If component-level bot
        if 'components' in bot and component:
            comp = next((c for c in bot['components'] if c['component'] == component), None)
            if not comp:
                flash(f'Component {component} for Bot {bot_id} not found', 'error')
                return redirect(request.url)
            bot_comp_key = f"{bot_id}_{component}"

            if comp['status'] == 'Completed':
                flash(f'Component {component} of Bot {bot_id} already completed', 'info')
                return redirect(request.url)

            if bot_comp_key in pending_confirmation_bots:
                flash(f'Component {component} of Bot {bot_id} pending confirmation before continuing production', 'warning')
                return redirect(request.url)

            comp['produced'] += 1
            if bot_comp_key not in quality_inspection_batches:
                quality_inspection_batches[bot_comp_key] = []
            quality_inspection_batches[bot_comp_key].append(result == 'pass')

            if len(quality_inspection_batches[bot_comp_key]) >= QUALITY_BATCH_LIMIT:
                rejections = quality_inspection_batches[bot_comp_key].count(False)
                if rejections > QUALITY_BATCH_LIMIT // 2:
                    flash(f'Majority parts rejected. Production halted for {bot_id} component {component}. Awaiting confirmation.', 'error')
                    pending_confirmation_bots.add(bot_comp_key)
                quality_inspection_batches[bot_comp_key] = []

            # Check if component completed
            if comp['produced'] >= comp['quantity']:
                comp['status'] = 'Completed'
                comp['completed_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                # Update assignments and OEE for this component
                if bot_comp_key in assignments:
                    machine = assignments[bot_comp_key]['machine']
                    oee_data[machine] += comp['quantity']
                    completed_assignments[bot_comp_key] = assignments[bot_comp_key]
                    completed_assignments[bot_comp_key]['end_time'] = comp['completed_time']
                    del assignments[bot_comp_key]

                    # Assign next pending component on same machine if any
                    next_comp = None
                    for b in bots:
                        if 'components' in b:
                            for c in b['components']:
                                key = f"{b['bot_id']}_{c['component']}"
                                if c['machine'] == machine and c['status'] == 'Pending' and key not in assignments:
                                    next_comp = (b, c)
                                    break
                        if next_comp:
                            break
                    if next_comp:
                        nb, nc = next_comp
                        assign_key = f"{nb['bot_id']}_{nc['component']}"
                        assignments[assign_key] = {
                            "machine": machine,
                            "start_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                            "status": "Running"
                        }
                        nc['status'] = 'Running'
                        flash(f'✅ Auto-assigned Component {nc["component"]} of Bot {nb["bot_id"]} to {machine}', 'success')

                flash(f'✅ Produced {comp["produced"]}/{comp["quantity"]} for Bot {bot_id} Component {component}. Marked complete.', 'success')
            else:
                flash(f'🛠 Produced {comp["produced"]}/{comp["quantity"]} for Bot {bot_id} Component {component}', 'info')

            # Update overall bot status if all components complete
            if all(c['status'] == 'Completed' for c in bot['components']):
                bot['status'] = 'Completed'
                bot['completed_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        else:
            # Single-component bot handling (existing logic)
            if bot['status'] == 'Completed':
                flash(f'Bot {bot_id} already completed', 'info')
                return redirect(request.url)
            if bot_id in pending_confirmation_bots:
                flash(f'Bot {bot_id} is pending confirmation before continuing production', 'warning')
                return redirect(request.url)

            bot['produced'] += 1
            if bot_id not in quality_inspection_batches:
                quality_inspection_batches[bot_id] = []
            quality_inspection_batches[bot_id].append(result == 'pass')

            if len(quality_inspection_batches[bot_id]) >= QUALITY_BATCH_LIMIT:
                rejections = quality_inspection_batches[bot_id].count(False)
                if rejections > QUALITY_BATCH_LIMIT // 2:
                    flash(f'Majority parts rejected. Production halted for {bot_id}. Awaiting confirmation.', 'error')
                    pending_confirmation_bots.add(bot_id)
                quality_inspection_batches[bot_id] = []

            if bot['produced'] >= bot['quantity']:
                bot['status'] = 'Completed'
                bot['completed_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                if bot_id in assignments:
                    machine = assignments[bot_id]['machine']
                    oee_data[machine] += bot['quantity']
                    completed_assignments[bot_id] = assignments[bot_id]
                    completed_assignments[bot_id]['end_time'] = bot['completed_time']
                    del assignments[bot_id]
                flash(f'✅ Bot {bot_id} production completed.', 'success')
            else:
                flash(f'🛠 Produced {bot["produced"]}/{bot["quantity"]} for Bot {bot_id}', 'info')

        socketio.emit('status_update')
        return redirect(request.url)

    # GET
    return render_template('operator.html', bots=bots, assignments=assignments, pending_confirmation_bots=pending_confirmation_bots)


@app.route('/confirm_production', methods=['POST'])
def confirm_production():
    bot_id = request.form['bot_id']
    component = request.form.get('component')

    if component:
        key = f"{bot_id}_{component}"
    else:
        key = bot_id

    if key in pending_confirmation_bots:
        pending_confirmation_bots.remove(key)
        flash(f'Production confirmed for {"Component " + component if component else "Bot " + bot_id}. Production resumed.', 'success')
    else:
        flash('No pending confirmation for this bot/component.', 'info')

    return redirect(url_for('operator'))


@app.route('/digital_twin')
def digital_twin():
    # Send full bot status including components if any
    display_bots = []
    for bot in bots:
        bot_dict = dict(bot)
        if 'components' in bot:
            bot_dict['components'] = bot['components']
        display_bots.append(bot_dict)

    return render_template('digital_twin.html', bots=display_bots, assignments=assignments, machines=machines)

@app.route('/dashboard')
def dashboard():
    # Calculate OEE for each machine
    oee_scores = {machine: calculate_oee(machine) for machine in machines}
    live_status = get_live_status()
    return render_template('dashboard.html', oee=oee_scores, live_status=live_status, machines=machines)

# Additional routes for download/upload etc. remain unchanged here


# ----- Main -----

if __name__ == '__main__':
    socketio.run(app, debug=True)
