"""Reviewed configurable alert rule definitions; no medical content seeded.

Revision ID: a712e69357c0
Revises: 923ffa482c11
"""
from alembic import op
import sqlalchemy as sa

revision = "a712e69357c0"
down_revision = "923ffa482c11"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("clinical_alert_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("version", sa.String(40), nullable=False),
        sa.Column("scale_code", sa.String(64), nullable=False),
        sa.Column("scale_version", sa.String(40), nullable=False),
        sa.Column("evaluator", sa.String(64), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("review_status", sa.String(40), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("code", "version"),
    )


def downgrade():
    op.drop_table("clinical_alert_rules")
