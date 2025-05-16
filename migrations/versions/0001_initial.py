"""
Initial migration: create tables as previously defined in db/schema.py
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass
    # Add additional tables here as needed
    # Example:
    # op.create_table('Users',
    #     sa.Column('id', sa.Integer, primary_key=True),
    #     sa.Column('user_id', sa.String, nullable=False),
    #     sa.Column('name', sa.String, nullable=False),
    # )


def downgrade() -> None:
    op.drop_table("SchemaVersion")
    # Drop additional tables here as needed
