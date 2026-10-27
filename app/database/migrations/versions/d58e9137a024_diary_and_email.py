"""Patient calendar with revision history and invitation delivery status.

Revision ID: d58e9137a024
Revises: a712e69357c0
"""
from alembic import op
import sqlalchemy as sa

revision = "d58e9137a024"
down_revision = "a712e69357c0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("invitations", sa.Column("delivery_status", sa.String(20), nullable=False, server_default="pending"))
    with op.batch_alter_table("invitations") as batch:
        batch.alter_column("delivery_status", existing_type=sa.String(20), server_default=None)
    op.create_table("diary_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("entry_date", sa.String(10), nullable=False),
        sa.Column("result_id", sa.Integer(), sa.ForeignKey("questionnaire_results.id"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("patient_id", "entry_date"),
    )
    op.create_index("ix_diary_entries_patient_id", "diary_entries", ["patient_id"])
    op.create_table("diary_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_id", sa.Integer(), sa.ForeignKey("diary_entries.id"), nullable=False),
        sa.Column("result_id", sa.Integer(), sa.ForeignKey("questionnaire_results.id"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
    )
    op.create_index("ix_diary_revisions_entry_id", "diary_revisions", ["entry_id"])


def downgrade():
    op.drop_index("ix_diary_revisions_entry_id", "diary_revisions")
    op.drop_table("diary_revisions")
    op.drop_index("ix_diary_entries_patient_id", "diary_entries")
    op.drop_table("diary_entries")
    with op.batch_alter_table("invitations") as batch:
        batch.drop_column("delivery_status")
