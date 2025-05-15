"""
Initial migration: create tables as previously defined in db/schema.py
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'SchemaVersion',
        sa.Column('version', sa.Integer, primary_key=True)
    )
    # Add additional tables here as needed
    # Example:
    # op.create_table('Volunteers',
    #     sa.Column('id', sa.Integer, primary_key=True),
    #     sa.Column('phone', sa.String, nullable=False),
    #     sa.Column('name', sa.String, nullable=False),
    # )
    op.execute("INSERT INTO SchemaVersion (version) VALUES (2)")

def downgrade():
    op.drop_table('SchemaVersion')
    # Drop additional tables here as needed
