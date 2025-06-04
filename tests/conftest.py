import pytest
from datetime import datetime, timezone, timedelta
from app import app, db, Machine, OperatorSession, OperatorLog, MachineDrawing, Project, EndProduct
from app import QualityCheck, ReworkQueue, ScrapLog, SystemLog

@pytest.fixture
def test_client():
    """Create a test client for the application"""
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['WTF_CSRF_ENABLED'] = False
    
    with app.test_client() as client:
        with app.app_context():
            db.create_all()
            yield client
            db.session.remove()
            db.drop_all()

@pytest.fixture
def init_database():
    """Initialize database with basic test data"""
    # Create machines
    machines = [
        Machine(name='Leadwell-1', status='available'),
        Machine(name='Leadwell-2', status='available'),
        Machine(name='HAAS-1', status='available')
    ]
    db.session.add_all(machines)
    
    # Create a test project
    project = Project(
        project_code='TEST-PRJ-001',
        project_name='Test Project',
        description='Test Description',
        route='Test Route'
    )
    db.session.add(project)
    db.session.flush()
    
    # Create end product
    end_product = EndProduct(
        project_id=project.id,
        name='Test Product',
        sap_id='TEST-SAP-001',
        quantity=10,
        completion_date=datetime.now(timezone.utc).date(),
        setup_time_std=30.0,
        cycle_time_std=15.0,
        is_first_piece_fpi_required=True,
        is_last_piece_lpi_required=True
    )
    db.session.add(end_product)
    db.session.flush()
    
    # Create drawing
    drawing = MachineDrawing(
        drawing_number='TEST-DRW-001',
        sap_id=end_product.sap_id
    )
    db.session.add(drawing)
    db.session.commit()
    
    return {'machines': machines, 'project': project, 'end_product': end_product, 'drawing': drawing}

@pytest.fixture
def operator_session(init_database):
    """Create a test operator session"""
    session = OperatorSession(
        operator_name='Test Operator',
        machine_id=init_database['machines'][0].id,
        shift='Morning',
        login_time=datetime.now(timezone.utc),
        is_active=True
    )
    db.session.add(session)
    db.session.commit()
    return session

@pytest.fixture
def operator_log(operator_session, init_database):
    """Create a test operator log"""
    log = OperatorLog(
        operator_session_id=operator_session.id,
        drawing_id=init_database['drawing'].id,
        end_product_sap_id=init_database['end_product'].sap_id,
        setup_start_time=datetime.now(timezone.utc),
        current_status='setup_started',
        run_planned_quantity=5
    )
    db.session.add(log)
    db.session.commit()
    return log

@pytest.fixture
def quality_check(operator_log):
    """Create a test quality check"""
    check = QualityCheck(
        operator_log_id=operator_log.id,
        inspector_name='Test Inspector',
        check_type='FPI',
        result='pass',
        timestamp=datetime.now(timezone.utc)
    )
    db.session.add(check)
    db.session.commit()
    return check

@pytest.fixture
def rework_queue(operator_log, quality_check):
    """Create a test rework queue item"""
    rework = ReworkQueue(
        source_operator_log_id=operator_log.id,
        originating_quality_check_id=quality_check.id,
        drawing_id=operator_log.drawing_id,
        quantity_to_rework=1,
        status='pending_manager_approval',
        rejection_reason='Test rework reason'
    )
    db.session.add(rework)
    db.session.commit()
    return rework

@pytest.fixture
def system_log():
    """Create a test system log"""
    log = SystemLog(
        level='ERROR',
        source='Test Source',
        message='Test error message',
        stack_trace='Test stack trace'
    )
    db.session.add(log)
    db.session.commit()
    return log 