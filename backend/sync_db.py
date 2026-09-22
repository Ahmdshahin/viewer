from app.db.session import get_engine
from app.db.models import Base
Base.metadata.create_all(bind=get_engine())
