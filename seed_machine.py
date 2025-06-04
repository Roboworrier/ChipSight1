# seed_machines.py
from app import db, Machine
from app import app

machine_names = [
    "Leadwell-1", "Leadwell-2",
    "VMC1", "VMC2", "VMC3", "VMC4",
    "HAAS-1", "HAAS-2"
]

with app.app_context():
    added = 0
    for name in machine_names:
        if not Machine.query.filter_by(name=name).first():
            db.session.add(Machine(name=name))
            added += 1
    db.session.commit()
    print(f"✅ {added} machines added successfully.")
