import pytest
from io import BytesIO
import pandas as pd
from datetime import datetime, timedelta
from app import db, Project, EndProduct

def test_large_file_upload(test_client):
    """Test uploading a large Excel file (near 16MB limit)"""
    # Login as planner
    test_client.post('/login', data={
        'username': 'planner',
        'password': 'plannerpass'
    })
    
    # Create a large DataFrame
    num_rows = 10000  # Large number of rows
    df = pd.DataFrame({
        'project_code': [f'PRJ-{i:05d}' for i in range(num_rows)],
        'project_name': [f'Project {i}' for i in range(num_rows)],
        'end_product': [f'Product {i}' for i in range(num_rows)],
        'sap_id': [f'SAP-{i:05d}' for i in range(num_rows)],
        'discription': ['Test Description'] * num_rows,
        'qty': [100] * num_rows,
        'route': ['Test Route'] * num_rows,
        'completion_date': [datetime.now().date() + timedelta(days=30)] * num_rows,
        'st': [30.0] * num_rows,
        'ct': [15.0] * num_rows
    })
    
    excel_file = BytesIO()
    df.to_excel(excel_file, index=False)
    excel_file.seek(0)
    
    # Upload file
    response = test_client.post('/planner', data={
        'action': 'upload_plan',
        'production_plan_file': (excel_file, 'large_plan.xlsx')
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b'Production plan uploaded successfully' in response.data
    
    # Verify data in database
    project_count = Project.query.count()
    assert project_count == num_rows

def test_duplicate_project_codes(test_client):
    """Test handling of duplicate project codes"""
    # Login as planner
    test_client.post('/login', data={
        'username': 'planner',
        'password': 'plannerpass'
    })
    
    # Create DataFrame with duplicate project codes
    df = pd.DataFrame({
        'project_code': ['DUP-001', 'DUP-001'],  # Duplicate project code
        'project_name': ['Project 1', 'Project 1'],
        'end_product': ['Product 1', 'Product 2'],
        'sap_id': ['SAP-001', 'SAP-002'],
        'discription': ['Description 1', 'Description 2'],
        'qty': [10, 20],
        'route': ['Route 1', 'Route 2'],
        'completion_date': [datetime.now().date()] * 2,
        'st': [30.0, 30.0],
        'ct': [15.0, 15.0]
    })
    
    excel_file = BytesIO()
    df.to_excel(excel_file, index=False)
    excel_file.seek(0)
    
    # Upload file
    response = test_client.post('/planner', data={
        'action': 'upload_plan',
        'production_plan_file': (excel_file, 'duplicate_plan.xlsx')
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b'Production plan uploaded successfully' in response.data
    
    # Verify that both end products are associated with the same project
    project = Project.query.filter_by(project_code='DUP-001').first()
    assert project is not None
    assert len(project.end_products) == 2

def test_invalid_data_types(test_client):
    """Test handling of invalid data types in Excel"""
    # Login as planner
    test_client.post('/login', data={
        'username': 'planner',
        'password': 'plannerpass'
    })
    
    # Create DataFrame with invalid data types
    df = pd.DataFrame({
        'project_code': ['INV-001'],
        'project_name': ['Invalid Project'],
        'end_product': ['Invalid Product'],
        'sap_id': ['SAP-INV-001'],
        'discription': ['Test Description'],
        'qty': ['not a number'],  # Invalid quantity
        'route': ['Test Route'],
        'completion_date': ['not a date'],  # Invalid date
        'st': ['invalid'],  # Invalid setup time
        'ct': ['invalid']  # Invalid cycle time
    })
    
    excel_file = BytesIO()
    df.to_excel(excel_file, index=False)
    excel_file.seek(0)
    
    # Upload file
    response = test_client.post('/planner', data={
        'action': 'upload_plan',
        'production_plan_file': (excel_file, 'invalid_data.xlsx')
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b'Error uploading plan' in response.data

def test_special_characters(test_client):
    """Test handling of special characters in Excel data"""
    # Login as planner
    test_client.post('/login', data={
        'username': 'planner',
        'password': 'plannerpass'
    })
    
    # Create DataFrame with special characters
    df = pd.DataFrame({
        'project_code': ['SPECIAL-001'],
        'project_name': ['Project & Special Chars !@#$%'],
        'end_product': ['Product (with) [brackets]'],
        'sap_id': ['SAP-SPECIAL-001'],
        'discription': ['Description with ®™©'],
        'qty': [10],
        'route': ['Route with áéíóú'],
        'completion_date': [datetime.now().date()],
        'st': [30.0],
        'ct': [15.0]
    })
    
    excel_file = BytesIO()
    df.to_excel(excel_file, index=False)
    excel_file.seek(0)
    
    # Upload file
    response = test_client.post('/planner', data={
        'action': 'upload_plan',
        'production_plan_file': (excel_file, 'special_chars.xlsx')
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b'Production plan uploaded successfully' in response.data
    
    # Verify data in database
    project = Project.query.filter_by(project_code='SPECIAL-001').first()
    assert project is not None
    assert project.project_name == 'Project & Special Chars !@#$%'
    assert project.end_products[0].name == 'Product (with) [brackets]' 