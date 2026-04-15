from app import create_app
from models import db, User
from werkzeug.security import generate_password_hash

app = create_app()
with app.app_context():
    existing = User.query.filter_by(username='admin').first()
    if existing:
        print('Admin user already exists.')
    else:
        admin = User(
            username='admin',
            email='admin@teensatwork.com',
            password_hash=generate_password_hash('adminpassword123', method='pbkdf2:sha256'),
            role='admin',
            is_approved=True,
            full_name='System Administrator'
        )
        db.session.add(admin)
        db.session.commit()
        print('Admin user created successfully.')
        print('  Username: admin')
        print('  Password: adminpassword123')
