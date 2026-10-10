"""add geo verification records

Revision ID: e6f7a8b9c0d1
Revises: d5f6a7b8c9d0_registration_teacher_approval
"""

from alembic import op
import sqlalchemy as sa


revision = 'e6f7a8b9c0d1'
down_revision = 'd5f6a7b8c9d0'
branch_labels = None
depends_on = None

VERIFICATION_SOURCE = sa.Enum('device', 'random_shot', name='verification_source')
VERIFICATION_VERDICT = sa.Enum('match', 'mismatch', name='verification_verdict')


def upgrade():
    op.create_table(
        'geo_verifications',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.Integer(), nullable=False),
        sa.Column(
            'source',
            VERIFICATION_SOURCE,
            server_default='device',
            nullable=False,
        ),
        sa.Column('latitude', sa.Float(), nullable=False),
        sa.Column('longitude', sa.Float(), nullable=False),
        sa.Column('accuracy_m', sa.Float(), nullable=True),
        sa.Column('distance_m', sa.Float(), nullable=False),
        sa.Column('match_probability', sa.Float(), nullable=False),
        sa.Column('verdict', VERIFICATION_VERDICT, nullable=False),
        sa.Column('model_version', sa.String(length=40), nullable=False),
        sa.Column('campus_name', sa.String(length=160), nullable=False),
        sa.Column('campus_latitude', sa.Float(), nullable=False),
        sa.Column('campus_longitude', sa.Float(), nullable=False),
        sa.Column('image_path', sa.String(length=255), nullable=True),
        sa.Column('captured_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['event_id'], ['events.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'event_id', name='uq_user_event_geo_verification'),
        sa.CheckConstraint(
            'latitude >= -90 AND latitude <= 90', name='verification_latitude_check'
        ),
        sa.CheckConstraint(
            'longitude >= -180 AND longitude <= 180', name='verification_longitude_check'
        ),
    )
    op.create_index(
        'ix_geo_verifications_event_id', 'geo_verifications', ['event_id']
    )


def downgrade():
    op.drop_index('ix_geo_verifications_event_id', table_name='geo_verifications')
    op.drop_table('geo_verifications')
