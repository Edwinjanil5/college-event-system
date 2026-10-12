"""add gps status, image evidence and faculty review columns

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1_geo_verifications
"""

from alembic import op
import sqlalchemy as sa


revision = 'f7a8b9c0d1e2'
down_revision = 'e6f7a8b9c0d1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('geo_verifications', sa.Column('gps_status', sa.String(length=32), nullable=True))
    op.add_column(
        'geo_verifications', sa.Column('gps_reason', sa.String(length=255), nullable=True)
    )
    op.add_column(
        'geo_verifications', sa.Column('gps_boundary_source', sa.String(length=16), nullable=True)
    )
    op.add_column(
        'geo_verifications', sa.Column('location_captured_at', sa.DateTime(), nullable=True)
    )
    op.add_column(
        'geo_verifications', sa.Column('verified_at', sa.DateTime(), nullable=True)
    )

    op.add_column(
        'geo_verifications', sa.Column('image_status', sa.String(length=32), nullable=True)
    )
    op.add_column(
        'geo_verifications', sa.Column('image_similarity', sa.Float(), nullable=True)
    )
    op.add_column(
        'geo_verifications',
        sa.Column('image_best_reference', sa.String(length=255), nullable=True),
    )
    op.add_column(
        'geo_verifications', sa.Column('image_backend', sa.String(length=32), nullable=True)
    )
    op.add_column(
        'geo_verifications',
        sa.Column('image_model_version', sa.String(length=64), nullable=True),
    )
    op.add_column(
        'geo_verifications', sa.Column('image_reference_count', sa.Integer(), nullable=True)
    )

    op.add_column(
        'geo_verifications', sa.Column('final_decision', sa.String(length=32), nullable=True)
    )
    op.add_column(
        'geo_verifications', sa.Column('decision_flags', sa.String(length=500), nullable=True)
    )
    op.add_column(
        'geo_verifications', sa.Column('decision_rationale', sa.Text(), nullable=True)
    )

    op.add_column(
        'geo_verifications', sa.Column('reviewed_by_id', sa.Integer(), nullable=True)
    )
    op.add_column(
        'geo_verifications', sa.Column('review_decision', sa.String(length=32), nullable=True)
    )
    op.add_column(
        'geo_verifications', sa.Column('review_note', sa.String(length=500), nullable=True)
    )
    op.add_column('geo_verifications', sa.Column('reviewed_at', sa.DateTime(), nullable=True))

    with op.batch_alter_table('geo_verifications') as batch:
        batch.create_foreign_key(
            'fk_geo_verifications_reviewer', 'users', ['reviewed_by_id'], ['id']
        )
        # A denied or unavailable location must still be recordable, so the
        # coordinates become optional rather than fabricating a value.
        batch.alter_column('latitude', existing_type=sa.Float(), nullable=True)
        batch.alter_column('longitude', existing_type=sa.Float(), nullable=True)
        batch.alter_column('match_probability', existing_type=sa.Float(), nullable=True)

    # Backfill: rows written before this migration used the legacy model
    # verdict, so carry it into the new authoritative column.
    op.execute(
        "UPDATE geo_verifications SET gps_status = 'LOCATION_MATCH' "
        "WHERE verdict = 'match' AND gps_status IS NULL"
    )
    op.execute(
        "UPDATE geo_verifications SET gps_status = 'LOCATION_MISMATCH' "
        "WHERE verdict = 'mismatch' AND gps_status IS NULL"
    )
    op.execute(
        "UPDATE geo_verifications SET verified_at = captured_at WHERE verified_at IS NULL"
    )
    op.execute(
        "UPDATE geo_verifications SET final_decision = 'FACULTY_REVIEW' "
        "WHERE final_decision IS NULL"
    )


def downgrade():
    with op.batch_alter_table('geo_verifications') as batch:
        batch.drop_constraint('fk_geo_verifications_reviewer', type_='foreignkey')
        batch.alter_column('latitude', existing_type=sa.Float(), nullable=False)
        batch.alter_column('longitude', existing_type=sa.Float(), nullable=False)
        batch.alter_column('match_probability', existing_type=sa.Float(), nullable=False)
    for column in (
        'reviewed_at',
        'review_note',
        'review_decision',
        'reviewed_by_id',
        'decision_rationale',
        'decision_flags',
        'final_decision',
        'image_reference_count',
        'image_model_version',
        'image_backend',
        'image_best_reference',
        'image_similarity',
        'image_status',
        'verified_at',
        'location_captured_at',
        'gps_boundary_source',
        'gps_reason',
        'gps_status',
    ):
        op.drop_column('geo_verifications', column)