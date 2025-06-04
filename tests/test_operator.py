import pytest
from datetime import datetime, timezone
from app import db, Machine, OperatorSession, OperatorLog, MachineDrawing, QualityCheck

def test_operator_login(test_client, init_database):
    """Test operator login workflow"""
    # Create test machine
    machine = Machine(name='Test-Machine', status='available')
    db.session.add(machine)
    db.session.commit()
    
    # Test login
    response = test_client.post('/operator_login', data={
        'operator_name': 'Test Operator',
        'machine_name': 'Test-Machine',
        'shift': 'Morning'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b'Welcome Test Operator' in response.data
    
    # Verify session created
    session = OperatorSession.query.filter_by(
        operator_name='Test Operator',
        machine_id=machine.id
    ).first()
    assert session is not None
    assert session.is_active

def test_concurrent_sessions(test_client, init_database):
    """Test handling of concurrent operator sessions"""
    # Create test machine
    machine = Machine(name='Test-Machine', status='available')
    db.session.add(machine)
    db.session.commit()
    
    # Create first session
    response = test_client.post('/operator_login', data={
        'operator_name': 'Operator 1',
        'machine_name': 'Test-Machine',
        'shift': 'Morning'
    })
    assert response.status_code == 302
    
    # Try to create second session for same machine
    response = test_client.post('/operator_login', data={
        'operator_name': 'Operator 2',
        'machine_name': 'Test-Machine',
        'shift': 'Morning'
    })
    assert response.status_code == 302
    
    # Verify first session was deactivated
    session1 = OperatorSession.query.filter_by(operator_name='Operator 1').first()
    assert not session1.is_active
    
    # Verify second session is active
    session2 = OperatorSession.query.filter_by(operator_name='Operator 2').first()
    assert session2.is_active

def test_operator_logout(test_client, operator_session):
    """Test operator logout workflow"""
    # Perform logout
    response = test_client.post('/operator_logout', follow_redirects=True)
    assert response.status_code == 200
    
    # Verify session was deactivated
    session = OperatorSession.query.get(operator_session.id)
    assert not session.is_active
    assert session.logout_time is not None

def test_drawing_selection(test_client, operator_session, init_database):
    """Test drawing selection workflow"""
    # Create test drawing
    drawing = MachineDrawing(
        drawing_number='TEST-DRW-001',
        sap_id='TEST-SAP-001'
    )
    db.session.add(drawing)
    db.session.commit()
    
    # Select drawing
    response = test_client.post('/operator/leadwell1', data={
        'action': 'select_drawing_and_start_session',
        'drawing_number_input': 'TEST-DRW-001'
    })
    assert response.status_code == 302
    
    # Verify operator log created
    log = OperatorLog.query.filter_by(
        operator_session_id=operator_session.id,
        drawing_id=drawing.id
    ).first()
    assert log is not None
    assert log.current_status == 'pending_setup'

def test_cycle_completion(test_client, operator_log):
    """Test cycle completion workflow"""
    # Start setup
    response = test_client.post('/operator/leadwell1', data={
        'action': 'start_setup',
        'log_id': operator_log.id
    })
    assert response.status_code == 302
    
    # Complete setup
    response = test_client.post('/operator/leadwell1', data={
        'action': 'complete_setup',
        'log_id': operator_log.id
    })
    assert response.status_code == 302
    
    # Complete cycle
    response = test_client.post('/operator/leadwell1', data={
        'action': 'cycle_complete',
        'log_id': operator_log.id,
        'quantity': 1
    })
    assert response.status_code == 302
    
    # Verify log updated
    log = OperatorLog.query.get(operator_log.id)
    assert log.run_completed_quantity == 1
    assert log.last_cycle_end_time is not None

def test_fpi_workflow(test_client, operator_log):
    """Test First Piece Inspection workflow"""
    # Complete first piece
    response = test_client.post('/operator/leadwell1', data={
        'action': 'cycle_complete',
        'log_id': operator_log.id,
        'quantity': 1
    })
    assert response.status_code == 302
    
    # Submit FPI (pass)
    response = test_client.post('/quality', data={
        'action': 'submit_fpi',
        'log_id': operator_log.id,
        'result': 'pass'
    })
    assert response.status_code == 302
    
    # Verify FPI recorded
    check = QualityCheck.query.filter_by(
        operator_log_id=operator_log.id,
        check_type='FPI'
    ).first()
    assert check is not None
    assert check.result == 'pass'
    
    # Verify log updated
    log = OperatorLog.query.get(operator_log.id)
    assert log.fpi_status == 'pass'
    assert not log.production_hold_fpi

def test_lpi_workflow(test_client, operator_log):
    """Test Last Piece Inspection workflow"""
    # Complete planned quantity
    response = test_client.post('/operator/leadwell1', data={
        'action': 'cycle_complete',
        'log_id': operator_log.id,
        'quantity': operator_log.run_planned_quantity
    })
    assert response.status_code == 302
    
    # Submit LPI (pass)
    response = test_client.post('/quality', data={
        'action': 'submit_lpi',
        'log_id': operator_log.id,
        'result': 'pass',
        'quantity_inspected': operator_log.run_planned_quantity
    })
    assert response.status_code == 302
    
    # Verify LPI recorded
    check = QualityCheck.query.filter_by(
        operator_log_id=operator_log.id,
        check_type='LPI'
    ).first()
    assert check is not None
    assert check.result == 'pass'
    
    # Verify log updated
    log = OperatorLog.query.get(operator_log.id)
    assert log.lpi_status == 'pass'

def test_rejection_workflow(test_client, operator_log):
    """Test rejection workflow"""
    # Complete cycle
    response = test_client.post('/operator/leadwell1', data={
        'action': 'cycle_complete',
        'log_id': operator_log.id,
        'quantity': 1
    })
    assert response.status_code == 302
    
    # Submit FPI (reject)
    response = test_client.post('/quality', data={
        'action': 'submit_fpi',
        'log_id': operator_log.id,
        'result': 'reject',
        'rejection_reason': 'Test rejection'
    })
    assert response.status_code == 302
    
    # Verify rejection recorded
    check = QualityCheck.query.filter_by(
        operator_log_id=operator_log.id,
        check_type='FPI'
    ).first()
    assert check is not None
    assert check.result == 'reject'
    assert check.rejection_reason == 'Test rejection'
    
    # Verify log updated
    log = OperatorLog.query.get(operator_log.id)
    assert log.fpi_status == 'fail'
    assert log.run_rejected_quantity_fpi == 1 