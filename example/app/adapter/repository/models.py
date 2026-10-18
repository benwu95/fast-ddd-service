"""Every ORM model module; Alembic's env.py imports this so all tables reach Base.metadata."""

from app.adapter.repository.billing import invoice_model

MODEL_MODULES = (invoice_model,)
