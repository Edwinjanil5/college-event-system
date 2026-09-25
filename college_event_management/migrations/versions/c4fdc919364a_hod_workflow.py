"""add HoD role and two-stage event approval

Revision ID: c4fdc919364a_hod_workflow
Revises: c4fdc919364a_class_incharge
Create Date: 2026-09-25
"""

from alembic import op
import sqlalchemy as sa


revision = 'c4fdc919364a_hod_workflow'
down_revision = 'c4fdc919364a_class_incharge'
branch_labels = None
depends_on = None


OLD_USER_ROLE = sa.Enum('student', 'organizer', 'admin', name='user_role')
NEW_USER_ROLE = sa.Enum('student', 'organizer', 'hod', 'admin', name='user_role')
OLD_EVENT_STATUS = sa.Enum('pending', 'approved', 'rejected', 'completed', name='event_status')
NEW_EVENT_STATUS = sa.Enum(
    'pending_hod',
    'hod_approved',
    'approved',
    'rejected',
    'completed',
    name='event_status',
)


def upgrade():
    with op.batch_alter_table('users') as batch:
        batch.alter_column(
            'role',
            existing_type=OLD_USER_ROLE,
            type_=NEW_USER_ROLE,
            existing_nullable=False,
            nullable=False,
        )

    with op.batch_alter_table('events') as batch:
        batch.alter_column(
            'status',
            existing_type=OLD_EVENT_STATUS,
            type_=NEW_EVENT_STATUS,
            existing_nullable=False,
            nullable=False,
            server_default='pending_hod',
        )


def downgrade():
    with op.batch_alter_table('events') as batch:
        batch.alter_column(
            'status',
            existing_type=NEW_EVENT_STATUS,
            type_=OLD_EVENT_STATUS,
            existing_nullable=False,
            nullable=False,
            server_default='pending',
        )

    with op.batch_alter_table('users') as batch:
        batch.alter_column(
            'role',
            existing_type=NEW_USER_ROLE,
            type_=OLD_USER_ROLE,
            existing_nullable=False,
            nullable=False,
        )
