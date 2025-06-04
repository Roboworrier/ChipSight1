import pytest
from io import BytesIO
import pandas as pd
from app import db, Project, EndProduct

def test_planner_login(test_client):
    """Test planner login"""
    response = test_client.post('/login', data={
        'username': 'planner',
        'password': 'plannerpass'
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'Planner login successful' in response.data

def test_planner_access_control(test_client):
    """Test planner dashboard access control"""
    # Try accessing without login
    response = test_client.get('/planner', follow_redirects=True)
    assert b'Access denied' in response.data
    
    # Login as planner
    test_client.post('/login', data={
        'username': 'planner',
        'password': 'plannerpass'
    })
    
    # Access planner dashboard
    response = test_client.get('/planner')
    assert response.status_code == 200
    assert b'Planner Dashboard' in response.data

def test_upload_production_plan(test_client, init_database):
    """Test production plan upload"""
    # Login as planner
    test_client.post('/login', data={
        'username': 'planner',
        'password': 'plannerpass'
    })
    
    # Create test Excel file
    df = pd.DataFrame({
        'project_code': ['TEST-001'],
        'project_name': ['Test Project'],
        'end_product': ['Test Product'],
        'sap_id': ['SAP-001'],
        'discription': ['Test Description'],
        'qty': [10],
        'route': ['Test Route'],
        'completion_date': [pd.Timestamp.now()],
        'st': [30.0],
        'ct': [15.0]
    })
    
    excel_file = BytesIO()
    df.to_excel(excel_file, index=False)
    excel_file.seek(0)
    
    # Upload file
    response = test_client.post('/planner', data={
        'action': 'upload_plan',
        'production_plan_file': (excel_file, 'test_plan.xlsx')
    }, follow_redirects=True)
    
    assert b'Production plan uploaded successfully' in response.data
    
    # Verify data in database
    project = Project.query.filter_by(project_code='TEST-001').first()
    assert project is not None
    assert project.project_name == 'Test Project'
    
    end_product = EndProduct.query.filter_by(sap_id='SAP-001').first()
    assert end_product is not None
    assert end_product.quantity == 10

def test_delete_project(test_client, init_database):
    """Test project deletion"""
    # Login as planner
    test_client.post('/login', data={
        'username': 'planner',
        'password': 'plannerpass'
    })
    
    # Delete project
    response = test_client.post('/planner', data={
        'action': 'delete_project',
        'project_id': init_database['project'].id
    }, follow_redirects=True)
    
    assert b'Project deleted successfully' in response.data
    
    # Verify project is marked as deleted
    project = Project.query.get(init_database['project'].id)
    assert project.is_deleted
    assert project.deleted_at is not None

def test_delete_end_product(test_client, init_database):
    """Test end product deletion"""
    # Login as planner
    test_client.post('/login', data={
        'username': 'planner',
        'password': 'plannerpass'
    })
    
    # Delete end product
    response = test_client.post('/planner', data={
        'action': 'delete_end_product',
        'end_product_id': init_database['end_product'].id
    }, follow_redirects=True)
    
    assert b'End product deleted successfully' in response.data
    
    # Verify end product is deleted
    end_product = EndProduct.query.get(init_database['end_product'].id)
    assert end_product is None

def test_invalid_excel_upload(test_client):
    """Test handling of invalid Excel file upload"""
    # Login as planner
    test_client.post('/login', data={
        'username': 'planner',
        'password': 'plannerpass'
    })
    
    # Create invalid Excel file (missing required columns)
    df = pd.DataFrame({
        'project_code': ['TEST-001'],
        'project_name': ['Test Project']
        # Missing other required columns
    })
    
    excel_file = BytesIO()
    df.to_excel(excel_file, index=False)
    excel_file.seek(0)
    
    # Upload file
    response = test_client.post('/planner', data={
        'action': 'upload_plan',
        'production_plan_file': (excel_file, 'test_plan.xlsx')
    }, follow_redirects=True)
    
    assert b'Excel file missing required columns' in response.data 