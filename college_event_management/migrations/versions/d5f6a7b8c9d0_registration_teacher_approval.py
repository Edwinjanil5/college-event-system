"""add class teacher approval to registrations

Revision ID: d5f6a7b8c9d0
Revises: c4fdc919364a_hod_workflow
"""

from alembic import op
import sqlalchemy as sa


revision = 'd5f6a7b8c9d0'
down_revision = 'c4fdc919364a_hod_workflow'
branch_labels = None
depends_on = None

REGISTRATION_STATUS = sa.Enum(
    'pending_teacher', 'approved', 'rejected', name='registration_status'
)


def upgrade():
    op.add_column(
        'registrations',
        sa.Column(
            'status',
            REGISTRATION_STATUS,
            nullable=False,
            server_default='pending_teacher',
        ),
    )
    op.add_column(
        'registrations',
        sa.Column('teacher_id', sa.Integer(), nullable=True),
    )
    op.add_column(
        'registrations',
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
    )
    op.add_column(
        'registrations',
        sa.Column('teacher_note', sa.String(length=500), nullable=True),
    )

    # Existing registrations were confirmed before the approval gate existed.
    op.execute("UPDATE registrations SET status = 'approved'")
    op.execute(
        'UPDATE registrations '
        'SET teacher_id = (SELECT events.organizer_id FROM events '
        'WHERE events.id = registrations.event_id) '
        'WHERE teacher_id IS NULL'
    )

    with op.batch_alter_table('registrations') as batch:
        batch.create_foreign_key(
            'fk_registrations_teacher',
            'users',
            ['teacher_id'],
            ['id'],
        )


def downgrade():
    with op.batch_alter_table('registrations') as batch:
        batch.drop_constraint('fk_registrations_teacher', type_='foreignkey')
        batch.drop_column('teacher_note')
        batch.drop_column('reviewed_at')
        batch.drop_column('teacher_id')
        batch.drop_column('status')