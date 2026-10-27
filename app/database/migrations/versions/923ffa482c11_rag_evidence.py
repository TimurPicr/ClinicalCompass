"""Preserve citations from the optional existing RAG service.

Revision ID: 923ffa482c11
Revises: 75f7c420c9a1
"""
from alembic import op
import sqlalchemy as sa

revision = "923ffa482c11"
down_revision = "75f7c420c9a1"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("recommendations") as batch:
        batch.alter_column("result_id", existing_type=sa.Integer(), nullable=True)
        batch.add_column(sa.Column("evidence", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
    with op.batch_alter_table("recommendations") as batch:
        batch.alter_column("evidence", existing_type=sa.JSON(), server_default=None)


def downgrade():
    # Existing RAG records must be exported/reconciled before removing their provenance.
    with op.batch_alter_table("recommendations") as batch:
        batch.drop_column("evidence")
        batch.alter_column("result_id", existing_type=sa.Integer(), nullable=False)
