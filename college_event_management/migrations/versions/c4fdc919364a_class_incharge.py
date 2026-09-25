"""add organizer class-incharge status

Revision ID: c4fdc919364a_class_incharge
Revises: c4fdc919364a_event_integrity
Create Date: 2026-09-25
"""

from alembic import op
import sqlalchemy as sa


revision = 'c4fdc919364a_class_incharge'
down_revision = 'c4fdc919364a_event_integrity'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'users',
        sa.Column(
            'is_class_incharge',
            sa.Boolean(),
            nullable=False,
            server_default='0',
        ),
    )


def downgrade():
    with op.batch_alter_table('users') as batch:
        batch.drop_column('is_class_incharge')
