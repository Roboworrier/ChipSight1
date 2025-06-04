import pytest
from datetime import datetime, timezone
from app import db, OperatorLog, QualityCheck, ReworkQueue, ScrapLog

def test_fpi_pass(test_client, operator_log):
    """Test First Piece Inspection pass workflow"""
    # Submit FPI pass
    response = test_client.post('/quality', data={
        'action': 'submit_fpi',
        'log_id': operator_log.id,
        'result': 'pass',
        'inspector_name': 'Test Inspector'
    })
    assert response.status_code == 302
    
    # Verify quality check created
    check = QualityCheck.query.filter_by(
        operator_log_id=operator_log.id,
        check_type='FPI'
    ).first()
    assert check is not None
    assert check.result == 'pass'
    assert check.inspector_name == 'Test Inspector'
    
    # Verify operator log updated
    log = OperatorLog.query.get(operator_log.id)
    assert log.fpi_status == 'pass'
    assert not log.production_hold_fpi

def test_fpi_reject(test_client, operator_log):
    """Test First Piece Inspection reject workflow"""
    # Submit FPI reject
    response = test_client.post('/quality', data={
        'action': 'submit_fpi',
        'log_id': operator_log.id,
        'result': 'reject',
        'rejection_reason': 'Test rejection',
        'inspector_name': 'Test Inspector'
    })
    assert response.status_code == 302
    
    # Verify quality check created
    check = QualityCheck.query.filter_by(
        operator_log_id=operator_log.id,
        check_type='FPI'
    ).first()
    assert check is not None
    assert check.result == 'reject'
    assert check.rejection_reason == 'Test rejection'
    
    # Verify operator log updated
    log = OperatorLog.query.get(operator_log.id)
    assert log.fpi_status == 'fail'
    assert log.production_hold_fpi
    assert log.run_rejected_quantity_fpi == 1

def test_fpi_rework(test_client, operator_log):
    """Test First Piece Inspection rework workflow"""
    # Submit FPI rework
    response = test_client.post('/quality', data={
        'action': 'submit_fpi',
        'log_id': operator_log.id,
        'result': 'rework',
        'rejection_reason': 'Needs rework',
        'inspector_name': 'Test Inspector'
    })
    assert response.status_code == 302
    
    # Verify quality check created
    check = QualityCheck.query.filter_by(
        operator_log_id=operator_log.id,
        check_type='FPI'
    ).first()
    assert check is not None
    assert check.result == 'rework'
    
    # Verify rework queue created
    rework = ReworkQueue.query.filter_by(
        source_operator_log_id=operator_log.id,
        originating_quality_check_id=check.id
    ).first()
    assert rework is not None
    assert rework.status == 'pending_manager_approval'
    
    # Verify operator log updated
    log = OperatorLog.query.get(operator_log.id)
    assert log.fpi_status == 'rework'
    assert log.production_hold_fpi
    assert log.run_rework_quantity_fpi == 1

def test_lpi_pass(test_client, operator_log):
    """Test Last Piece Inspection pass workflow"""
    # Submit LPI pass
    response = test_client.post('/quality', data={
        'action': 'submit_lpi',
        'log_id': operator_log.id,
        'result': 'pass',
        'quantity_inspected': 10,
        'inspector_name': 'Test Inspector'
    })
    assert response.status_code == 302
    
    # Verify quality check created
    check = QualityCheck.query.filter_by(
        operator_log_id=operator_log.id,
        check_type='LPI'
    ).first()
    assert check is not None
    assert check.result == 'pass'
    assert check.lpi_quantity_inspected == 10
    
    # Verify operator log updated
    log = OperatorLog.query.get(operator_log.id)
    assert log.lpi_status == 'pass'

def test_lpi_partial_reject(test_client, operator_log):
    """Test Last Piece Inspection partial reject workflow"""
    # Submit LPI with partial reject
    response = test_client.post('/quality', data={
        'action': 'submit_lpi',
        'log_id': operator_log.id,
        'result': 'reject',
        'quantity_inspected': 10,
        'quantity_rejected': 3,
        'rejection_reason': 'Partial batch rejection',
        'inspector_name': 'Test Inspector'
    })
    assert response.status_code == 302
    
    # Verify quality check created
    check = QualityCheck.query.filter_by(
        operator_log_id=operator_log.id,
        check_type='LPI'
    ).first()
    assert check is not None
    assert check.result == 'reject'
    assert check.lpi_quantity_inspected == 10
    assert check.lpi_quantity_rejected == 3
    
    # Verify operator log updated
    log = OperatorLog.query.get(operator_log.id)
    assert log.lpi_status == 'fail'
    assert log.run_rejected_quantity_lpi == 3

def test_lpi_partial_rework(test_client, operator_log):
    """Test Last Piece Inspection partial rework workflow"""
    # Submit LPI with partial rework
    response = test_client.post('/quality', data={
        'action': 'submit_lpi',
        'log_id': operator_log.id,
        'result': 'rework',
        'quantity_inspected': 10,
        'quantity_to_rework': 4,
        'rejection_reason': 'Partial batch rework',
        'inspector_name': 'Test Inspector'
    })
    assert response.status_code == 302
    
    # Verify quality check created
    check = QualityCheck.query.filter_by(
        operator_log_id=operator_log.id,
        check_type='LPI'
    ).first()
    assert check is not None
    assert check.result == 'rework'
    assert check.lpi_quantity_inspected == 10
    assert check.lpi_quantity_to_rework == 4
    
    # Verify rework queue created
    rework = ReworkQueue.query.filter_by(
        source_operator_log_id=operator_log.id,
        originating_quality_check_id=check.id
    ).first()
    assert rework is not None
    assert rework.quantity_to_rework == 4
    
    # Verify operator log updated
    log = OperatorLog.query.get(operator_log.id)
    assert log.lpi_status == 'rework'
    assert log.run_rework_quantity_lpi == 4

def test_scrap_workflow(test_client, quality_check):
    """Test scrap workflow"""
    # Create scrap record
    response = test_client.post('/quality', data={
        'action': 'create_scrap',
        'quality_check_id': quality_check.id,
        'quantity': 2,
        'reason': 'Test scrap reason'
    })
    assert response.status_code == 302
    
    # Verify scrap log created
    scrap = ScrapLog.query.filter_by(
        originating_quality_check_id=quality_check.id
    ).first()
    assert scrap is not None
    assert scrap.quantity_scrapped == 2
    assert scrap.reason == 'Test scrap reason'

def test_rework_approval(test_client, rework_queue):
    """Test rework approval workflow"""
    # Approve rework
    response = test_client.post('/quality', data={
        'action': 'approve_rework',
        'rework_id': rework_queue.id,
        'manager_name': 'Test Manager',
        'notes': 'Approved for rework'
    })
    assert response.status_code == 302
    
    # Verify rework queue updated
    rework = ReworkQueue.query.get(rework_queue.id)
    assert rework.status == 'manager_approved'
    assert rework.manager_approved_by == 'Test Manager'
    assert rework.manager_notes == 'Approved for rework' 