import pytest
from app import db, SystemLog
from datetime import datetime, timezone

def test_404_error(test_client):
    """Test 404 error handling"""
    response = test_client.get('/nonexistent-page')
    assert response.status_code == 404
    assert b'Page Not Found' in response.data
    assert b'Check if the URL is correct' in response.data

def test_500_error(test_client, init_database):
    """Test 500 error handling"""
    # Simulate a server error by trying to access a non-existent database table
    with pytest.raises(Exception):
        db.session.execute('SELECT * FROM nonexistent_table')
    
    # Check error was logged
    error = SystemLog.query.filter_by(source='Database').first()
    assert error is not None
    assert error.level == 'ERROR'

def test_database_error_logging(init_database):
    """Test error logging functionality"""
    error_message = "Test error message"
    error_type = "Test Error"
    
    # Create error log
    error = SystemLog(
        level='WARNING',
        source=error_type,
        message=error_message,
        timestamp=datetime.now(timezone.utc)
    )
    db.session.add(error)
    db.session.commit()
    
    # Verify error was logged
    logged_error = SystemLog.query.filter_by(source=error_type).first()
    assert logged_error is not None
    assert logged_error.message == error_message
    assert logged_error.level == 'WARNING'
    assert not logged_error.resolved

def test_error_resolution(init_database, system_log):
    """Test error resolution functionality"""
    # Resolve the error
    system_log.resolved = True
    system_log.resolved_by = "Test User"
    system_log.resolved_at = datetime.now(timezone.utc)
    db.session.commit()
    
    # Verify error was resolved
    resolved_error = SystemLog.query.get(system_log.id)
    assert resolved_error.resolved
    assert resolved_error.resolved_by == "Test User"
    assert resolved_error.resolved_at is not None

def test_operator_session_error(test_client, operator_session):
    """Test operator session error handling"""
    # Deactivate operator session
    operator_session.is_active = False
    db.session.commit()
    
    # Try to access operator panel
    response = test_client.get('/operator/leadwell1')
    assert response.status_code == 302  # Redirect to login
    
    # Follow redirect
    response = test_client.get('/operator/leadwell1', follow_redirects=True)
    assert b'Your session has expired' in response.data

def test_quality_check_error(test_client, operator_log):
    """Test quality check error handling"""
    # Try to submit invalid quality check
    response = test_client.post('/quality', data={
        'action': 'submit_fpi',
        'log_id': operator_log.id,
        'result': 'invalid_result'  # Invalid result
    })
    assert response.status_code == 400
    
    # Verify error was logged
    error = SystemLog.query.filter_by(source='Validation').first()
    assert error is not None
    assert 'Invalid FPI result' in error.message

def test_concurrent_session_handling(test_client, operator_session):
    """Test handling of concurrent operator sessions"""
    # Create second session for same machine
    new_session = {
        'operator_name': 'Another Operator',
        'machine_name': operator_session.machine_rel.name,
        'shift': 'Afternoon'
    }
    
    response = test_client.post('/operator_login', data=new_session)
    assert response.status_code == 302  # Redirect to operator panel
    
    # Verify old session was deactivated
    old_session = operator_session
    assert not old_session.is_active

def test_database_transaction_rollback(test_client, init_database):
    """Test database transaction rollback on error"""
    # Try to create invalid record
    try:
        # This should fail due to missing required fields
        db.session.add(SystemLog())
        db.session.commit()
    except:
        db.session.rollback()
    
    # Verify database is still in consistent state
    error_count = SystemLog.query.count()
    assert error_count == 0  # No errors should have been added 