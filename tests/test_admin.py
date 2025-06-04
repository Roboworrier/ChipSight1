import pytest
from datetime import datetime, timezone
import pandas as pd
from io import BytesIO
from app import db, SystemLog, OperatorSession, Machine

def test_admin_login(test_client):
    """Test admin login"""
    response = test_client.post('/login', data={
        'username': 'admin',
        'password': 'adminpass'
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'Admin login successful' in response.data

def test_admin_access_control(test_client):
    """Test admin dashboard access control"""
    # Try accessing without login
    response = test_client.get('/admin', follow_redirects=True)
    assert b'Access denied' in response.data
    
    # Login as admin
    test_client.post('/login', data={
        'username': 'admin',
        'password': 'adminpass'
    })
    
    # Access admin dashboard
    response = test_client.get('/admin')
    assert response.status_code == 200
    assert b'Admin Dashboard' in response.data

def test_export_error_logs(test_client, system_log):
    """Test error log export functionality"""
    # Login as admin
    test_client.post('/login', data={
        'username': 'admin',
        'password': 'adminpass'
    })
    
    # Export error logs
    response = test_client.post('/admin', data={
        'action': 'export_error_logs'
    })
    assert response.status_code == 200
    assert response.headers['Content-Type'] == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    
    # Verify Excel content
    df = pd.read_excel(BytesIO(response.data))
    assert 'Timestamp' in df.columns
    assert 'Level' in df.columns
    assert 'Message' in df.columns
    assert len(df) >= 1  # Should contain at least our test log

def test_resolve_error_log(test_client, system_log):
    """Test error log resolution"""
    # Login as admin
    test_client.post('/login', data={
        'username': 'admin',
        'password': 'adminpass'
    })
    
    # Resolve error log
    response = test_client.post('/admin', data={
        'action': 'resolve_log',
        'log_id': system_log.id
    }, follow_redirects=True)
    
    assert b'Log marked as resolved' in response.data
    
    # Verify log is resolved
    log = SystemLog.query.get(system_log.id)
    assert log.resolved
    assert log.resolved_by == 'admin'
    assert log.resolved_at is not None

def test_system_statistics(test_client, init_database, operator_session):
    """Test system statistics display"""
    # Login as admin
    test_client.post('/login', data={
        'username': 'admin',
        'password': 'adminpass'
    })
    
    # View dashboard
    response = test_client.get('/admin')
    assert response.status_code == 200
    
    # Verify statistics are displayed
    assert b'Total Users' in response.data
    assert b'Active Sessions' in response.data
    assert b'Total Projects' in response.data
    assert b'Total Machines' in response.data
    
    # Verify correct counts
    assert str(OperatorSession.query.distinct(OperatorSession.operator_name).count()).encode() in response.data
    assert str(Machine.query.count()).encode() in response.data

def test_error_log_display(test_client, system_log):
    """Test error log display"""
    # Login as admin
    test_client.post('/login', data={
        'username': 'admin',
        'password': 'adminpass'
    })
    
    # View dashboard
    response = test_client.get('/admin')
    assert response.status_code == 200
    
    # Verify error log is displayed
    assert bytes(system_log.message, 'utf-8') in response.data
    assert bytes(system_log.source, 'utf-8') in response.data
    assert bytes(system_log.level, 'utf-8') in response.data

def test_performance_metrics(test_client):
    """Test performance metrics display"""
    # Login as admin
    test_client.post('/login', data={
        'username': 'admin',
        'password': 'adminpass'
    })
    
    # View dashboard
    response = test_client.get('/admin')
    assert response.status_code == 200
    
    # Verify performance metrics are displayed
    assert b'Database Size' in response.data
    assert b'Average Response Time' in response.data
    assert b'Memory Usage' in response.data
    assert b'CPU Usage' in response.data

def test_multiple_error_resolution(test_client):
    """Test resolving multiple error logs"""
    # Login as admin
    test_client.post('/login', data={
        'username': 'admin',
        'password': 'adminpass'
    })
    
    # Create multiple error logs
    logs = [
        SystemLog(level='ERROR', source='Test', message=f'Error {i}')
        for i in range(3)
    ]
    db.session.add_all(logs)
    db.session.commit()
    
    # Resolve each log
    for log in logs:
        response = test_client.post('/admin', data={
            'action': 'resolve_log',
            'log_id': log.id
        }, follow_redirects=True)
        assert b'Log marked as resolved' in response.data
    
    # Verify all logs are resolved
    unresolved_count = SystemLog.query.filter_by(resolved=False).count()
    assert unresolved_count == 0 