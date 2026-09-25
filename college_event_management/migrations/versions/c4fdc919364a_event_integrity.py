"""enforce event integrity constraints

Revision ID: c4fdc919364a_event_integrity
Revises: c4fdc919364a
Create Date: 2026-09-24
"""

from alembic import op
import sqlalchemy as sa


revision = 'c4fdc919364a_event_integrity'
down_revision = 'c4fdc919364a'
branch_labels = None
depends_on = None


def _has_constraint(inspector, table_name, constraint_name):
    return any(item.get('name') == constraint_name for item in inspector.get_check_constraints(table_name))


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {item['name']: item for item in inspector.get_columns('events')}

    # Older local SQLite databases were created before these columns had
    # explicit defaults/nullability. Normalize them before adding constraints.
    op.execute("UPDATE events SET status = 'pending' WHERE status IS NULL")
    op.execute('UPDATE events SET is_intercollege = 0 WHERE is_intercollege IS NULL')

    with op.batch_alter_table('events') as batch:
        if columns.get('is_intercollege', {}).get('nullable', True):
            batch.alter_column(
                'is_intercollege',
                existing_type=sa.Boolean(),
                nullable=False,
                server_default='0',
            )
        if columns.get('status', {}).get('nullable', True):
            batch.alter_column(
                'status',
                existing_type=sa.Enum('pending', 'approved', 'rejected', 'completed', name='event_status'),
                nullable=False,
                server_default='pending',
            )

    inspector = sa.inspect(bind)
    with op.batch_alter_table('events') as batch:
        if not _has_constraint(inspector, 'events', 'max_participants_positive'):
            batch.create_check_constraint('max_participants_positive', 'max_participants > 0')
        if not _has_constraint(inspector, 'events', 'ticket_fee_non_negative'):
            batch.create_check_constraint('ticket_fee_non_negative', 'ticket_fee >= 0')


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    with op.batch_alter_table('events') as batch:
        if _has_constraint(inspector, 'events', 'max_participants_positive'):
            batch.drop_constraint('max_participants_positive', type_='check')
        if _has_constraint(inspector, 'events', 'ticket_fee_non_negative'):
            batch.drop_constraint('ticket_fee_non_negative', type_='check')
        batch.alter_column('is_intercollege', existing_type=sa.Boolean(), nullable=True)
        batch.alter_column(
            'status',
            existing_type=sa.Enum('pending', 'approved', 'rejected', 'completed', name='event_status'),
            nullable=True,
        )
