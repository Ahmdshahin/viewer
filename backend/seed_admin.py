from app.db.session import SessionLocal, get_engine
from app.db.models import User
from app.core.security import hash_password

db = SessionLocal(bind=get_engine())
if not db.query(User).filter(User.username == 'admin').first():
    admin_user = User(
        username='admin',
        email='admin@geoportal.eg',
        full_name='System Administrator',
        hashed_password=hash_password('admin123'),
        role='admin',
        is_active=True
    )
    db.add(admin_user)
    db.commit()
