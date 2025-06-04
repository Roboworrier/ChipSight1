import pytest
from datetime import datetime, timezone
from app import db, Machine, OperatorSession, OperatorLog, Project, EndProduct

def test_plant_head_login(test_client):
    """Test plant head login"""
    response = test_client.post('/login', data={
        'username': 'plant_head',
        'password': 'plantpass'
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'Plant Head login successful' in response.data

def test_plant_head_access_control(test_client):
    """Test plant head dashboard access control"""
    # Try accessing without login
    response = test_client.get('/plant_head', follow_redirects=True)
    assert b'Access denied' in response.data
    
    # Login as plant head
    test_client.post('/login', data={
        'username': 'plant_head',
        'password': 'plantpass'
    })
    
    # Access plant head dashboard
    response = test_client.get('/plant_head')
    assert response.status_code == 200
    assert b'Plant Head Dashboard' in response.data

def test_machine_utilization_calculation(test_client, init_database):
    """Test machine utilization calculation"""
    # Login as plant head
    test_client.post('/login', data={
        'username': 'plant_head',
        'password': 'plantpass'
    })
    
    # Set some machines as in use
    machines = Machine.query.all()
    machines[0].status = 'in_use'
    machines[1].status = 'in_use'
    db.session.commit()
    
    # View dashboard
    response = test_client.get('/plant_head')
    assert response.status_code == 200
    
    # Calculate expected utilization (2 out of 3 machines)
    expected_utilization = round((2 / 3 * 100), 1)
    assert str(expected_utilization).encode() in response.data

def test_production_metrics(test_client, operator_log):
    """Test production metrics calculation"""
    # Login as plant head
    test_client.post('/login', data={
        'username': 'plant_head',
        'password': 'plantpass'
    })
    
    # Update operator log with completed parts
    operator_log.run_completed_quantity = 5
    operator_log.setup_start_time = datetime.now(timezone.utc)
    db.session.commit()
    
    # View dashboard
    response = test_client.get('/plant_head')
    assert response.status_code == 200
    assert b'5' in response.data  # Should show 5 completed parts

def test_quality_metrics(test_client, operator_log):
    """Test quality metrics display"""
    # Login as plant head
    test_client.post('/login', data={
        'username': 'plant_head',
        'password': 'plantpass'
    })
    
    # Set operator log with quality issues
    operator_log.current_status = 'cycle_completed_pending_fpi'
    db.session.commit()
    
    # View dashboard
    response = test_client.get('/plant_head')
    assert response.status_code == 200
    assert b'Pending Quality Checks' in response.data
    assert b'1' in response.data  # Should show 1 pending check

def test_oee_calculation(test_client, operator_log):
    """Test OEE calculation"""
    # Login as plant head
    test_client.post('/login', data={
        'username': 'plant_head',
        'password': 'plantpass'
    })
    
    # Set up data for OEE calculation
    machine = operator_log.operator_session.machine_rel
    machine.status = 'in_use'
    
    operator_log.run_completed_quantity = 8
    operator_log.run_planned_quantity = 10
    operator_log.setup_start_time = datetime.now(timezone.utc)
    operator_log.first_cycle_start_time = datetime.now(timezone.utc)
    operator_log.last_cycle_end_time = datetime.now(timezone.utc)
    db.session.commit()
    
    # View dashboard
    response = test_client.get('/plant_head')
    assert response.status_code == 200
    assert b'OEE' in response.data

def test_project_progress(test_client, init_database):
    """Test project progress display"""
    # Login as plant head
    test_client.post('/login', data={
        'username': 'plant_head',
        'password': 'plantpass'
    })
    
    # Set project due today
    project = init_database['project']
    end_product = init_database['end_product']
    end_product.completion_date = datetime.now(timezone.utc).date()
    db.session.commit()
    
    # View dashboard
    response = test_client.get('/plant_head')
    assert response.status_code == 200
    assert bytes(project.project_name, 'utf-8') in response.data

def test_machine_status_display(test_client, init_database, operator_session):
    """Test machine status display"""
    # Login as plant head
    test_client.post('/login', data={
        'username': 'plant_head',
        'password': 'plantpass'
    })
    
    # Set machine status and operator
    machine = operator_session.machine_rel
    machine.status = 'in_use'
    db.session.commit()
    
    # View dashboard
    response = test_client.get('/plant_head')
    assert response.status_code == 200
    assert bytes(machine.name, 'utf-8') in response.data
    assert bytes(operator_session.operator_name, 'utf-8') in response.data
    assert b'in_use' in response.data 