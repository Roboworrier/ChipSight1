# ChipSight - Digital Twin for Manufacturing

A comprehensive digital twin solution for manufacturing operations, focusing on CNC machine monitoring, quality control, and production planning.

## Features

- **Multi-Role Access System**
  - Planner Dashboard
  - Manager Dashboard
  - Quality Control Interface
  - Operator Panels (Machine-specific)
  - Digital Twin Overview

- **Real-time Production Monitoring**
  - Setup Time Tracking
  - Cycle Time Monitoring
  - Quality Inspection Integration
  - OEE Calculations

- **Quality Control System**
  - First Piece Inspection (FPI)
  - Last Piece Inspection (LPI)
  - Rework Management
  - Quality History Tracking

- **Production Planning**
  - Excel-based Plan Upload
  - Drawing Management
  - SAP Integration Ready
  - Completion Date Tracking

## Technology Stack

- Backend: Python Flask
- Database: SQLite with SQLAlchemy
- Frontend: Bootstrap 5, Chart.js
- Authentication: Session-based

## Installation

1. Create a virtual environment:
   ```bash
   python -m venv venv
   ```

2. Activate virtual environment:
   ```bash
   # Windows
   venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Initialize database:
   ```bash
   set FLASK_APP=app.py
   flask db upgrade
   ```

5. Start the server:
   ```bash
   python -m flask run --host=0.0.0.0 --port=5000
   ```

## Usage

Access the application through:
- Local: `http://localhost:5000`
- Network: `http://[YOUR-IP]:5000`

Default login credentials:
- Planner: planner/plannerpass
- Manager: manager/managerpass
- Quality: quality/qualitypass
- Operator: Use operator login panel

## License

Copyright © 2025 Diwakar Singh. All rights reserved.
See COMPANY_LICENSE.md for license terms.

## Contact

For inquiries and support:
- Email: diwakar126796@gmail.com 