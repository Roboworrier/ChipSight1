import pytest
from datetime import datetime, timezone
from app import db, Project, ReworkQueue, ScrapLog

def test_manager_login(test_client):
    """Test manager login"""
    response = test_client.post('/login', data={
        'username': 'manager',
        'password': 'managerpass'
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'Manager login successful' in response.data

def test_manager_access_control(test_client):
    """Test manager dashboard access control"""
    # Try accessing without login
    response = test_client.get('/manager', follow_redirects=True)
    assert b'Access denied' in response.data
    
    # Login as manager
    test_client.post('/login', data={
        'username': 'manager',
        'password': 'managerpass'
    })
    
    # Access manager dashboard
    response = test_client.get('/manager')
    assert response.status_code == 200
    assert b'Manager Dashboard' in response.data

def test_restore_project(test_client, init_database):
    """Test project restoration"""
    # Login as manager
    test_client.post('/login', data={
        'username': 'manager',
        'password': 'managerpass'
    })
    
    # Mark project as deleted first
    project = init_database['project']
    project.is_deleted = True
    project.deleted_at = datetime.now(timezone.utc)
    db.session.commit()
    
    # Restore project
    response = test_client.post('/manager', data={
        'action': 'restore_project',
        'project_id': project.id
    }, follow_redirects=True)
    
    assert b'Project restored successfully' in response.data
    
    # Verify project is restored
    project = Project.query.get(project.id)
    assert not project.is_deleted
    assert project.deleted_at is None

def test_approve_rework(test_client, rework_queue):
    """Test rework approval workflow"""
    # Login as manager
    test_client.post('/login', data={
        'username': 'manager',
        'password': 'managerpass'
    })
    
    # Approve rework
    response = test_client.post('/manager', data={
        'action': 'approve_rework',
        'rework_id': rework_queue.id,
        'manager_notes': 'Approved for rework'
    }, follow_redirects=True)
    
    assert b'Rework request approved successfully' in response.data
    
    # Verify rework queue updated
    rework = ReworkQueue.query.get(rework_queue.id)
    assert rework.status == 'manager_approved'
    assert rework.manager_approved_by == 'manager'
    assert rework.manager_notes == 'Approved for rework'

def test_reject_rework(test_client, rework_queue):
    """Test rework rejection workflow"""
    # Login as manager
    test_client.post('/login', data={
        'username': 'manager',
        'password': 'managerpass'
    })
    
    # Reject rework
    response = test_client.post('/manager', data={
        'action': 'reject_rework',
        'rework_id': rework_queue.id,
        'manager_notes': 'Rejected - scrap parts'
    }, follow_redirects=True)
    
    assert b'Rework request rejected' in response.data
    
    # Verify rework queue updated
    rework = ReworkQueue.query.get(rework_queue.id)
    assert rework.status == 'manager_rejected'
    assert rework.manager_approved_by == 'manager'
    assert rework.manager_notes == 'Rejected - scrap parts'
    
    # Verify scrap record created
    scrap = ScrapLog.query.filter_by(
        drawing_id=rework.drawing_id,
        quantity_scrapped=rework.quantity_to_rework
    ).first()
    assert scrap is not None
    assert 'Rework rejected by manager' in scrap.reason

def test_view_deleted_projects(test_client, init_database):
    """Test viewing deleted projects"""
    # Login as manager
    test_client.post('/login', data={
        'username': 'manager',
        'password': 'managerpass'
    })
    
    # Mark project as deleted
    project = init_database['project']
    project.is_deleted = True
    project.deleted_at = datetime.now(timezone.utc)
    db.session.commit()
    
    # View manager dashboard
    response = test_client.get('/manager')
    assert response.status_code == 200
    assert bytes(project.project_code, 'utf-8') in response.data
    assert b'Deleted Projects' in response.data

def test_rework_queue_display(test_client, rework_queue):
    """Test rework queue display"""
    # Login as manager
    test_client.post('/login', data={
        'username': 'manager',
        'password': 'managerpass'
    })
    
    # View manager dashboard
    response = test_client.get('/manager')
    assert response.status_code == 200
    assert b'Pending Rework Requests' in response.data
    assert bytes(rework_queue.rejection_reason, 'utf-8') in response.data 