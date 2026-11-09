"""Phase 3: Enforce old-parent immutability on brand_guideline_documents reassignment.

Revision ID: 0005_guideline_doc_reassignment
Revises: 0004_single_published_version
Create Date: 2026-11-09 15:08:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0005_guideline_doc_reassignment"
down_revision: Union[str, None] = "0004_single_published_version"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION fn_enforce_guideline_doc_immutability()
            RETURNS TRIGGER AS $$
            DECLARE
                parent_status VARCHAR(32);
                old_parent_status VARCHAR(32);
                target_version_id UUID;
                target_org_id UUID;
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    target_version_id := OLD.brand_kit_version_id;
                    target_org_id := OLD.organisation_id;
                ELSE
                    target_version_id := NEW.brand_kit_version_id;
                    target_org_id := NEW.organisation_id;
                END IF;

                IF TG_OP = 'UPDATE' AND NEW.brand_kit_version_id IS DISTINCT FROM OLD.brand_kit_version_id THEN
                    SELECT status INTO old_parent_status
                    FROM brand_kit_versions
                    WHERE id = OLD.brand_kit_version_id;

                    IF old_parent_status IS NOT NULL AND old_parent_status IN ('PUBLISHED', 'ARCHIVED') THEN
                        RAISE EXCEPTION '[P0002] Cannot move child record out of % BrandKitVersion (id=%).',
                            old_parent_status, OLD.brand_kit_version_id
                            USING ERRCODE = '23514';
                    END IF;
                END IF;

                SELECT status INTO parent_status
                FROM brand_kit_versions
                WHERE id = target_version_id;

                IF parent_status IS NOT NULL AND parent_status IN ('PUBLISHED', 'ARCHIVED') THEN
                    IF TG_OP = 'DELETE' THEN
                        IF NOT EXISTS (SELECT 1 FROM organisations WHERE id = target_org_id) THEN
                            RETURN OLD;
                        END IF;
                        RAISE EXCEPTION '[P0002] Cannot DELETE brand_guideline_documents belonging to a % BrandKitVersion (id=%).',
                            parent_status, target_version_id
                            USING ERRCODE = '23514';
                    END IF;

                    IF TG_OP = 'INSERT' THEN
                        RAISE EXCEPTION '[P0002] Cannot INSERT brand_guideline_documents into a % BrandKitVersion (id=%).',
                            parent_status, target_version_id
                            USING ERRCODE = '23514';
                    END IF;

                    IF TG_OP = 'UPDATE' THEN
                        -- Strictly lock all 14 file identity, ownership, version association, and provenance columns.
                        -- Only the 10 allowlisted processing telemetry columns may be updated after publication:
                        -- (parsing_status, parse_attempt_count, last_error_code, last_error_message,
                        --  page_count, raw_text_content, embedding_model, embedding_model_version, parsed_at, embedded_at)
                        IF (
                            NEW.id IS DISTINCT FROM OLD.id OR
                            NEW.brand_kit_version_id IS DISTINCT FROM OLD.brand_kit_version_id OR
                            NEW.organisation_id IS DISTINCT FROM OLD.organisation_id OR
                            NEW.title IS DISTINCT FROM OLD.title OR
                            NEW.document_category IS DISTINCT FROM OLD.document_category OR
                            NEW.original_filename IS DISTINCT FROM OLD.original_filename OR
                            NEW.stored_filename IS DISTINCT FROM OLD.stored_filename OR
                            NEW.storage_backend IS DISTINCT FROM OLD.storage_backend OR
                            NEW.storage_path IS DISTINCT FROM OLD.storage_path OR
                            NEW.mime_type IS DISTINCT FROM OLD.mime_type OR
                            NEW.file_size_bytes IS DISTINCT FROM OLD.file_size_bytes OR
                            NEW.file_sha256 IS DISTINCT FROM OLD.file_sha256 OR
                            NEW.uploaded_by_user_id IS DISTINCT FROM OLD.uploaded_by_user_id OR
                            NEW.created_at IS DISTINCT FROM OLD.created_at
                        ) THEN
                            RAISE EXCEPTION '[P0002] Cannot modify immutable file identity, ownership, or provenance columns on brand_guideline_documents for % BrandKitVersion (id=%).',
                                parent_status, target_version_id
                                USING ERRCODE = '23514';
                        END IF;
                    END IF;
                END IF;

                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION fn_enforce_guideline_doc_immutability()
            RETURNS TRIGGER AS $$
            DECLARE
                parent_status VARCHAR(32);
                target_version_id UUID;
                target_org_id UUID;
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    target_version_id := OLD.brand_kit_version_id;
                    target_org_id := OLD.organisation_id;
                ELSE
                    target_version_id := NEW.brand_kit_version_id;
                    target_org_id := NEW.organisation_id;
                END IF;

                SELECT status INTO parent_status
                FROM brand_kit_versions
                WHERE id = target_version_id;

                IF parent_status IS NOT NULL AND parent_status IN ('PUBLISHED', 'ARCHIVED') THEN
                    IF TG_OP = 'DELETE' THEN
                        IF NOT EXISTS (SELECT 1 FROM organisations WHERE id = target_org_id) THEN
                            RETURN OLD;
                        END IF;
                        RAISE EXCEPTION '[P0002] Cannot DELETE brand_guideline_documents belonging to a % BrandKitVersion (id=%).',
                            parent_status, target_version_id
                            USING ERRCODE = '23514';
                    END IF;

                    IF TG_OP = 'INSERT' THEN
                        RAISE EXCEPTION '[P0002] Cannot INSERT brand_guideline_documents into a % BrandKitVersion (id=%).',
                            parent_status, target_version_id
                            USING ERRCODE = '23514';
                    END IF;

                    IF TG_OP = 'UPDATE' THEN
                        IF (
                            NEW.id IS DISTINCT FROM OLD.id OR
                            NEW.brand_kit_version_id IS DISTINCT FROM OLD.brand_kit_version_id OR
                            NEW.organisation_id IS DISTINCT FROM OLD.organisation_id OR
                            NEW.title IS DISTINCT FROM OLD.title OR
                            NEW.document_category IS DISTINCT FROM OLD.document_category OR
                            NEW.original_filename IS DISTINCT FROM OLD.original_filename OR
                            NEW.stored_filename IS DISTINCT FROM OLD.stored_filename OR
                            NEW.storage_backend IS DISTINCT FROM OLD.storage_backend OR
                            NEW.storage_path IS DISTINCT FROM OLD.storage_path OR
                            NEW.mime_type IS DISTINCT FROM OLD.mime_type OR
                            NEW.file_size_bytes IS DISTINCT FROM OLD.file_size_bytes OR
                            NEW.file_sha256 IS DISTINCT FROM OLD.file_sha256 OR
                            NEW.uploaded_by_user_id IS DISTINCT FROM OLD.uploaded_by_user_id OR
                            NEW.created_at IS DISTINCT FROM OLD.created_at
                        ) THEN
                            RAISE EXCEPTION '[P0002] Cannot modify immutable file identity, ownership, or provenance columns on brand_guideline_documents for % BrandKitVersion (id=%).',
                                parent_status, target_version_id
                                USING ERRCODE = '23514';
                        END IF;
                    END IF;
                END IF;

                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
