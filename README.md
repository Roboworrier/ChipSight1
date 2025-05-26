# ChipSight - Manufacturing Execution System

ChipSight is a comprehensive Manufacturing Execution System (MES) designed to manage and control manufacturing operations with a focus on quality control and production efficiency.

## Features

- **Production Planning**
  - Import production plans from Excel
  - Track project status and completion
  - Monitor production timelines

- **Machine Shop Management**
  - Drawing number management
  - Machine assignments and tracking
  - Real-time production status

- **Operator Console**
  - Setup and cycle time tracking
  - First Part Inspection (FPI) workflow
  - Last Part Inspection (LPI) workflow
  - Production hold controls

- **Quality Control**
  - Comprehensive inspection workflow
  - Rework queue management
  - Quality metrics tracking
  - Inspection history

- **Digital Twin Dashboard**
  - Real-time production monitoring
  - OEE (Overall Equipment Effectiveness) tracking
  - Production metrics visualization
  - Quality performance analytics

## Technology Stack

- Backend: Python Flask
- Database: SQLite with SQLAlchemy ORM
- Frontend: Bootstrap 5, JavaScript
- Data Processing: Pandas for Excel handling

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/ChipSight.git
cd ChipSight
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Initialize the database:
```bash
flask db upgrade
```

5. Run the application:
```bash
flask run
```

## Usage

1. **Planning Module**
   - Upload production plans via Excel
   - Monitor project status
   - Track completion dates

2. **Machine Shop**
   - Assign drawings to machines
   - Monitor machine utilization
   - Track production progress

3. **Operator Interface**
   - Start/complete setup and cycles
   - Record production times
   - Manage quality inspections

4. **Quality Control**
   - Perform FPI/LPI inspections
   - Manage rework queue
   - Track quality metrics

5. **Digital Twin**
   - View real-time production status
   - Monitor OEE metrics
   - Analyze production data

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details. 