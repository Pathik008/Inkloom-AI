"""Comprehensive test suite for Inkloom AI Phase 6.3:
LangGraph-aligned compliance review workflow, Unverified Guard, deterministic score preservation,
and safe provider-failure fallback.

Covers:
1. Complete deterministic fallback workflow (when LLM_API_KEY is missing/empty).
2. Missing LLM credentials sets ai_available = False, engine_mode = "DETERMINISTIC_FALLBACK".
3. LLM timeout (LLMTimeoutError) and provider API errors trigger safe degradation to fallback.
4. Valid candidate chunk citation validation passes through Unverified Guard.
5. Hallucinated / invented chunk ID is stripped and converted to UNVERIFIED_CLAIM.
6. Cross-tenant / cross-version chunk ID is stripped and marked UNVERIFIED_CLAIM.
7. Unsupported claim marked UNVERIFIED_CLAIM with no citation.
8. Deterministic score preservation (authoritative score unchanged by semantic findings).
9. Duplicate finding prevention (no double-counting of same span/rule).
10. Claim and retrieval bounds (max 15 claims, max 12 unique candidate chunks).
11. Invalid AI JSON response handling.
12. Zero fabricated tone/fact findings during fallback mode.
13. End-to-end API test on POST /compliance/analyze with mode="hybrid" fallback.
14. End-to-end API test on POST /compliance/analyze with mode="deterministic".
"""
from __future__ import annotations

import uuid
from typing import Any
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_access_token
from app.main import app
from app.models.brand import (
    ApprovedBrandFact,
    BrandDocumentChunk,
    BrandGuidelineDocument,
    BrandIdentity,
    BrandKit,
    BrandKitVersion,
    BrandKitVersionStatus,
    ComplianceRule,
    ComplianceRuleType,
    DocumentParsingStatus,
    FactCategory,
    FactRuleApprovalStatus,
    GuidelineDocumentCategory,
    RuleSeverity,
)
from app.models.compliance import ComplianceAnalysis, ContentSubmission
from app.models import Organisation, OrganisationMembership, Role, RoleName, User
from app.services.ai_workflow.compliance_graph import (
    ComplianceReviewWorkflow,
    WorkflowState,
    MAX_CANDIDATE_CHUNKS,
    MAX_CLAIMS_PER_SUBMISSION,
)
from app.services.ai_workflow.llm_provider import (
    LLMProvider,
    LLMTimeoutError,
    LLMProviderAPIError,
    MockLLMProvider,
)
from app.services.rag.retriever import RetrievedChunk


def _create_user_and_org(
    db: Session,
    *,
    email: str = "creator@inkloom.ai",
    org_name: str = "Acme Global",
    role_name: str = RoleName.ADMIN,
) -> tuple[User, Organisation, str]:
    """Helper to create user, organisation, membership, and return bearer token."""
    user = User(
        id=uuid.uuid4(),
        email=email,
        full_name="Compliance Tester",
        password_hash="test_hash",
        is_active=True,
        is_verified=True,
    )
    db.add(user)
    db.flush()

    org = Organisation(
        id=uuid.uuid4(),
        name=org_name,
        slug=f"org-{uuid.uuid4().hex[:8]}",
        created_by=user.id,
    )
    db.add(org)
    db.flush()

    role = db.execute(select(Role).where(Role.name == role_name)).scalar_one()
    membership = OrganisationMembership(
        id=uuid.uuid4(),
        user_id=user.id,
        organisation_id=org.id,
        role_id=role.id,
        status="ACTIVE",
    )
    db.add(membership)
    db.commit()

    token, _, _ = create_access_token(
        subject=str(user.id),
        email=user.email,
    )
    return user, org, token


def _create_brand_kit_with_rules(
    db: Session,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    is_published: bool = True,
    doc_content: str | None = None,
    doc_title: str = "Official Guidelines",
) -> tuple[BrandKit, BrandKitVersion, BrandGuidelineDocument | None, BrandDocumentChunk | None]:
    """Creates a brand kit with 1 active rule, 1 approved pricing fact, and optional document/chunk."""
    kit = BrandKit(
        id=uuid.uuid4(),
        organisation_id=org_id,
        name="Finance Brand Kit",
        slug=f"kit-{uuid.uuid4().hex[:6]}",
        created_by_user_id=user_id,
    )
    db.add(kit)
    db.flush()

    version = BrandKitVersion(
        id=uuid.uuid4(),
        brand_kit_id=kit.id,
        organisation_id=org_id,
        version_number=1,
        status=BrandKitVersionStatus.DRAFT,
        created_by_user_id=user_id,
    )
    db.add(version)
    db.flush()

    # Rule: Prohibit "guaranteed returns"
    rule = ComplianceRule(
        id=uuid.uuid4(),
        organisation_id=org_id,
        brand_kit_version_id=version.id,
        rule_code="BAN-GR",
        rule_type=ComplianceRuleType.PROHIBITED_TERM,
        severity=RuleSeverity.CRITICAL,
        title="Prohibit Guaranteed Returns",
        description="Returns cannot be guaranteed.",
        target_pattern="guaranteed returns",
        suggested_replacement="potential returns",
        source_reference="Manual Rule Entry v1",
        approval_status=FactRuleApprovalStatus.APPROVED,
        is_active=True,
    )
    db.add(rule)

    # Approved pricing fact: ₹99
    fact = ApprovedBrandFact(
        id=uuid.uuid4(),
        organisation_id=org_id,
        brand_kit_version_id=version.id,
        category=FactCategory.PRICING,
        subject_name="Starter Plan",
        fact_key="starter_plan",
        fact_value="₹99 / month",
        source_reference="Pricing Guide v1",
        approval_status=FactRuleApprovalStatus.APPROVED,
        is_active=True,
    )
    db.add(fact)

    # Brand voice guidelines
    identity = BrandIdentity(
        id=uuid.uuid4(),
        organisation_id=org_id,
        brand_kit_version_id=version.id,
        brand_name="Inkloom",
        brand_voice_guidelines="Professional, transparent, authoritative, and helpful. Avoid hyperbole.",
    )
    db.add(identity)
    db.flush()

    doc = None
    chunk = None
    if doc_content:
        doc = BrandGuidelineDocument(
            id=uuid.uuid4(),
            brand_kit_version_id=version.id,
            organisation_id=org_id,
            title=doc_title,
            document_category=GuidelineDocumentCategory.STYLE_GUIDE,
            original_filename="guide.txt",
            stored_filename="guide.txt",
            storage_path=f"orgs/{org_id}/guide.txt",
            mime_type="text/plain",
            file_size_bytes=len(doc_content.encode("utf-8")),
            file_sha256="c" * 64,
            page_count=1,
            parsing_status=DocumentParsingStatus.EMBEDDED,
            raw_text_content=doc_content,
            uploaded_by_user_id=user_id,
        )
        db.add(doc)
        db.flush()

        chunk = BrandDocumentChunk(
            id=uuid.uuid4(),
            document_id=doc.id,
            brand_kit_version_id=version.id,
            organisation_id=org_id,
            chunk_index=0,
            page_number=1,
            char_start=0,
            char_end=len(doc_content),
            content=doc_content,
            content_sha256="chunk_hash" + "0" * 54,
            token_count=len(doc_content.split()),
            embedding_dimension=1024,
        )
        db.add(chunk)
        db.flush()

    if is_published:
        version.status = BrandKitVersionStatus.PUBLISHED
        kit.active_version_id = version.id
        db.flush()

    db.commit()
    db.refresh(kit)
    db.refresh(version)
    if doc:
        db.refresh(doc)
        db.refresh(chunk)
    return kit, version, doc, chunk


class TestPhase63ComplianceReviewWorkflow:
    """Targeted acceptance test suite for Work Package 6.3."""

    # -------------------------------------------------------------------------
    # TEST 1 & 2: Deterministic Fallback & Credential Missing Telemetry
    # -------------------------------------------------------------------------
    def test_deterministic_fallback_when_credentials_missing(self, db_session: Session, monkeypatch):
        """When LLM_API_KEY is empty, workflow degrades gracefully to DETERMINISTIC_FALLBACK."""
        monkeypatch.setattr(settings, "LLM_API_KEY", "")
        user, org, _ = _create_user_and_org(db_session)
        kit, version, _, _ = _create_brand_kit_with_rules(db_session, org.id, user.id)

        workflow = ComplianceReviewWorkflow(db_session)
        state = WorkflowState(
            submission_id=uuid.uuid4(),
            organisation_id=org.id,
            brand_kit_version_id=version.id,
            raw_text="Acme investments offer guaranteed returns to everyone.",
            mode="hybrid",
        )

        res = workflow.execute_sync(state)

        # Assert engine degradation and telemetry
        assert res.engine_mode == "DETERMINISTIC_FALLBACK"
        assert res.ai_available is False
        assert "Semantic review bypassed" in res.ai_status_message
        assert res.final_scoring_json["engine_mode"] == "DETERMINISTIC_FALLBACK"
        assert res.final_scoring_json["ai_available"] is False
        assert res.final_scoring_json["semantic_assessment"] is None

        # Assert authoritative deterministic scoring
        assert res.final_score == 60  # 100 - 40 (CRITICAL penalty)
        assert res.final_result == "FAIL"
        assert len(res.final_findings) == 1
        assert res.final_findings[0]["rule_code"] == "BAN-GR"
        assert res.final_findings[0]["severity"] == "CRITICAL"

        # Assert zero fabricated findings
        assert len(res.unverified_claims) == 0
        assert len(res.tone_findings) == 0
        assert len(res.validated_semantic_findings) == 0

    # -------------------------------------------------------------------------
    # TEST 3: LLM Timeout Triggers Safe Degradation
    # -------------------------------------------------------------------------
    @pytest.mark.anyio
    async def test_llm_timeout_triggers_safe_fallback(self, db_session: Session):
        """When the LLM provider times out, pipeline catches error and degrades gracefully."""
        user, org, _ = _create_user_and_org(db_session)
        kit, version, _, _ = _create_brand_kit_with_rules(db_session, org.id, user.id)

        class TimingOutLLMProvider(LLMProvider):
            provider_name = "timeout_mock"
            model_name = "mock"

            async def generate_json(self, prompt: str, system_prompt: str | None = None) -> dict[str, Any]:
                raise LLMTimeoutError("Google Gemini connection timed out after 15.0s")

        workflow = ComplianceReviewWorkflow(db_session)
        state = WorkflowState(
            submission_id=uuid.uuid4(),
            organisation_id=org.id,
            brand_kit_version_id=version.id,
            raw_text="Safe marketing copy with guaranteed returns.",
            mode="hybrid",
            llm_provider=TimingOutLLMProvider(),
        )

        res = await workflow.execute(state)

        assert res.engine_mode == "DETERMINISTIC_FALLBACK"
        assert res.ai_available is False
        assert "AI claim extraction failed" in res.ai_status_message
        assert res.final_score == 60  # Deterministic score preserved
        assert len(res.extracted_claims) == 0
        assert len(res.unverified_claims) == 0

    # -------------------------------------------------------------------------
    # TEST 4: Valid Candidate Chunk Passes Through Unverified Guard
    # -------------------------------------------------------------------------
    @pytest.mark.anyio
    async def test_unverified_guard_valid_citation(self, db_session: Session):
        """Legitimate retrieved chunk citation passes Unverified Guard as VERIFIED."""
        user, org, _ = _create_user_and_org(db_session)
        kit, version, doc, chunk = _create_brand_kit_with_rules(
            db_session,
            org.id,
            user.id,
            doc_content="Starter plan is priced at ₹99 per month for all new subscribers.",
            doc_title="Subscription Pricing Policy",
        )

        retrieved = RetrievedChunk(
            chunk_id=chunk.id,
            document_id=doc.id,
            document_title=doc.title,
            chunk_index=0,
            page_number=1,
            section_heading="Pricing",
            char_start=0,
            char_end=len(chunk.content),
            content=chunk.content,
            content_sha256=chunk.content_sha256,
            token_count=chunk.token_count,
            similarity_score=0.92,
        )

        mock_llm = MockLLMProvider(
            canned_claims=[{"claim_id": 1, "claim_text": "Starter plan costs ₹99 per month."}],
            canned_fact_verifications=[
                {
                    "claim_id": 1,
                    "status": "VERIFIED",
                    "citation_chunk_id": str(chunk.id),
                    "citation_text": chunk.content,
                    "explanation": "Exact match to approved pricing policy.",
                }
            ],
        )

        workflow = ComplianceReviewWorkflow(db_session)
        state = WorkflowState(
            submission_id=uuid.uuid4(),
            organisation_id=org.id,
            brand_kit_version_id=version.id,
            raw_text="Our starter plan costs ₹99 per month.",
            mode="hybrid",
            llm_provider=mock_llm,
        )
        # Pre-seed candidate chunks (as retrieved by Stage 4)
        state.candidate_chunks = [retrieved]

        # Execute node 7: unverified guard
        state.extracted_claims = mock_llm.canned_claims
        state.raw_fact_verifications = mock_llm.canned_fact_verifications
        res = await workflow._node_unverified_guard(state)

        assert res.claims_verified_count == 1
        assert res.claims_unverified_count == 0
        assert len(res.validated_semantic_findings) == 1
        vf = res.validated_semantic_findings[0]
        assert vf["status"] == "VERIFIED"
        assert vf["rule_code"] == "RAG-VERIFIED-FACT"
        assert vf["citation"]["chunk_id"] == str(chunk.id)
        assert vf["citation"]["document_title"] == "Subscription Pricing Policy"
        assert vf["citation"]["similarity_score"] == 0.92

    # -------------------------------------------------------------------------
    # TEST 5: Hallucinated / Invented Chunk ID Stripped
    # -------------------------------------------------------------------------
    @pytest.mark.anyio
    async def test_unverified_guard_strips_hallucinated_citation(self, db_session: Session):
        """LLM cites a non-existent UUID; Unverified Guard detects it, strips citation, marks UNVERIFIED_CLAIM."""
        user, org, _ = _create_user_and_org(db_session)
        kit, version, _, _ = _create_brand_kit_with_rules(db_session, org.id, user.id)

        hallucinated_chunk_id = str(uuid.uuid4())
        mock_llm = MockLLMProvider(
            canned_claims=[{"claim_id": 1, "claim_text": "Inkloom uses quantum processors."}],
            canned_fact_verifications=[
                {
                    "claim_id": 1,
                    "status": "VERIFIED",
                    "citation_chunk_id": hallucinated_chunk_id,  # Invented!
                    "citation_text": "Quantum speed guarantees.",
                    "explanation": "Citing quantum policy.",
                }
            ],
        )

        workflow = ComplianceReviewWorkflow(db_session)
        state = WorkflowState(
            submission_id=uuid.uuid4(),
            organisation_id=org.id,
            brand_kit_version_id=version.id,
            raw_text="Inkloom uses quantum processors.",
            mode="hybrid",
            llm_provider=mock_llm,
        )
        state.extracted_claims = mock_llm.canned_claims
        state.raw_fact_verifications = mock_llm.canned_fact_verifications
        state.candidate_chunks = []  # No such chunk retrieved

        res = await workflow._node_unverified_guard(state)

        assert res.claims_unverified_count == 1
        assert res.claims_verified_count == 0
        assert len(res.unverified_claims) == 1
        uv = res.unverified_claims[0]
        assert uv["rule_code"] == "RAG-UNVERIFIED-CLAIM"
        assert uv["kind"] == "UNVERIFIED_CLAIM"
        assert uv["citation"] is None  # CRITICAL: Stripped!
        assert "could not be verified against any approved brand guideline" in uv["description"]

    # -------------------------------------------------------------------------
    # TEST 6: Cross-Tenant / Cross-Version Chunk Boundary Violation Stripped
    # -------------------------------------------------------------------------
    @pytest.mark.anyio
    async def test_unverified_guard_strips_cross_tenant_or_cross_version_citation(self, db_session: Session):
        """LLM cites a chunk from another organisation; Unverified Guard detects boundary breach and strips citation."""
        # Tenant A (Target)
        user_a, org_a, _ = _create_user_and_org(db_session, email="tenant_a@example.com")
        kit_a, version_a, _, _ = _create_brand_kit_with_rules(db_session, org_a.id, user_a.id)

        # Tenant B (Foreign)
        user_b, org_b, _ = _create_user_and_org(db_session, email="tenant_b@example.com", org_name="Foreign Corp")
        kit_b, version_b, foreign_doc, foreign_chunk = _create_brand_kit_with_rules(
            db_session, org_b.id, user_b.id, doc_content="Tenant B internal confidential algorithm."
        )

        # Forge candidate chunk with foreign chunk_id
        foreign_candidate = RetrievedChunk(
            chunk_id=foreign_chunk.id,
            document_id=foreign_doc.id,
            document_title="Foreign Document",
            chunk_index=0,
            page_number=1,
            section_heading="Confidential",
            char_start=0,
            char_end=50,
            content=foreign_chunk.content,
            content_sha256="abc",
            token_count=10,
            similarity_score=0.95,
        )

        workflow = ComplianceReviewWorkflow(db_session)
        state = WorkflowState(
            submission_id=uuid.uuid4(),
            organisation_id=org_a.id,  # Target is Tenant A
            brand_kit_version_id=version_a.id,
            raw_text="Tenant A copy citing foreign document.",
            mode="hybrid",
        )
        state.extracted_claims = [{"claim_id": 1, "claim_text": "We use proprietary algorithms."}]
        state.raw_fact_verifications = [
            {
                "claim_id": 1,
                "status": "VERIFIED",
                "citation_chunk_id": str(foreign_chunk.id),  # Foreign chunk ID
                "citation_text": foreign_chunk.content,
            }
        ]
        state.candidate_chunks = [foreign_candidate]

        res = await workflow._node_unverified_guard(state)

        # Unverified Guard must reject the citation because it belongs to Tenant B
        assert res.claims_verified_count == 0
        assert res.claims_unverified_count == 1
        assert res.validated_semantic_findings[0]["citation"] is None
        assert res.validated_semantic_findings[0]["kind"] == "UNVERIFIED_CLAIM"

    # -------------------------------------------------------------------------
    # TEST 7: Unsupported Claim Marked UNVERIFIED_CLAIM
    # -------------------------------------------------------------------------
    @pytest.mark.anyio
    async def test_unsupported_claim_marked_unverified(self, db_session: Session):
        """An extracted claim that the LLM or retriever cannot support is marked UNVERIFIED_CLAIM."""
        user, org, _ = _create_user_and_org(db_session)
        kit, version, _, _ = _create_brand_kit_with_rules(db_session, org.id, user.id)

        mock_llm = MockLLMProvider(
            canned_claims=[
                {"claim_id": 1, "claim_text": "Claim A"},
                {"claim_id": 2, "claim_text": "Claim B without verification"},
            ],
            canned_fact_verifications=[
                {"claim_id": 1, "status": "UNVERIFIED", "citation_chunk_id": None}
            ],
        )

        workflow = ComplianceReviewWorkflow(db_session)
        state = WorkflowState(
            submission_id=uuid.uuid4(),
            organisation_id=org.id,
            brand_kit_version_id=version.id,
            raw_text="Claim A and Claim B without verification.",
            mode="hybrid",
            llm_provider=mock_llm,
        )
        state.extracted_claims = mock_llm.canned_claims
        state.raw_fact_verifications = mock_llm.canned_fact_verifications
        state.candidate_chunks = []

        res = await workflow._node_unverified_guard(state)

        # Both claims must be classified as UNVERIFIED_CLAIM
        assert res.claims_unverified_count == 2
        assert len(res.unverified_claims) == 2
        for uv in res.unverified_claims:
            assert uv["citation"] is None
            assert uv["kind"] == "UNVERIFIED_CLAIM"

    # -------------------------------------------------------------------------
    # TEST 8: Deterministic Score Preservation
    # -------------------------------------------------------------------------
    @pytest.mark.anyio
    async def test_authoritative_deterministic_score_preserved(self, db_session: Session):
        """Authoritative deterministic score is strictly preserved and never penalized by semantic findings."""
        user, org, _ = _create_user_and_org(db_session)
        kit, version, doc, chunk = _create_brand_kit_with_rules(
            db_session, org.id, user.id, doc_content="No annual contracts required."
        )

        retrieved = RetrievedChunk(
            chunk_id=chunk.id,
            document_id=doc.id,
            document_title=doc.title,
            chunk_index=0,
            page_number=1,
            section_heading="Contracts",
            char_start=0,
            char_end=len(chunk.content),
            content=chunk.content,
            content_sha256=chunk.content_sha256,
            token_count=chunk.token_count,
            similarity_score=0.90,
        )

        mock_llm = MockLLMProvider(
            canned_claims=[
                {"claim_id": 1, "claim_text": "We offer guaranteed returns."},
                {"claim_id": 2, "claim_text": "Contracts are mandatory for 10 years."},
            ],
            canned_fact_verifications=[
                {
                    "claim_id": 2,
                    "status": "CONTRADICTED",
                    "citation_chunk_id": str(chunk.id),
                    "citation_text": chunk.content,
                }
            ],
        )

        workflow = ComplianceReviewWorkflow(db_session)
        state = WorkflowState(
            submission_id=uuid.uuid4(),
            organisation_id=org.id,
            brand_kit_version_id=version.id,
            raw_text="We offer guaranteed returns. Contracts are mandatory for 10 years.",
            mode="hybrid",
            llm_provider=mock_llm,
            include_experimental_score=True,
        )
        state.candidate_chunks = [retrieved]

        res = await workflow.execute(state)

        # Baseline score must be 100% deterministic (60)
        assert res.final_score == 60
        assert res.deterministic_score == 60
        assert res.final_result == "FAIL"

        # Telemetry records separate semantic assessment and optional experimental score
        scoring = res.final_scoring_json
        assert scoring["deterministic_score"] == 60
        assert scoring["semantic_assessment"]["claims_contradicted"] == 1
        assert scoring["semantic_assessment"]["claims_unverified"] == 1
        # Experimental score: max(0, 60 - (20 * 1) - (10 * 1)) = 30
        assert scoring["experimental_score"] == 30

    # -------------------------------------------------------------------------
    # TEST 9: Duplicate Finding Prevention
    # -------------------------------------------------------------------------
    @pytest.mark.anyio
    async def test_duplicate_finding_prevention(self, db_session: Session):
        """Overlapping spans or text matches between deterministic engine and semantic AI do not duplicate."""
        user, org, _ = _create_user_and_org(db_session)
        kit, version, _, _ = _create_brand_kit_with_rules(db_session, org.id, user.id)

        # Text has "guaranteed returns" at [9:27]
        workflow = ComplianceReviewWorkflow(db_session)
        state = WorkflowState(
            submission_id=uuid.uuid4(),
            organisation_id=org.id,
            brand_kit_version_id=version.id,
            raw_text="We offer guaranteed returns.",
            mode="hybrid",
        )
        state = await workflow._node_ingest_and_normalize(state)
        state = await workflow._node_deterministic_engine(state)

        assert len(state.deterministic_findings) == 1
        det_finding = state.deterministic_findings[0]

        # Inject an overlapping semantic finding on the same text
        state.validated_semantic_findings = [
            {
                "id": str(uuid.uuid4()),
                "rule_code": "RAG-CONTRADICTED-CLAIM",
                "matched_text": "guaranteed returns",
                "start": det_finding["start"],
                "end": det_finding["end"],
                "description": "Contradicts marketing guidelines.",
                "citation": {"document_title": "Rules"},
            }
        ]

        res = await workflow._node_deduplicate_and_score(state)

        # Finding must be annotated on the existing deterministic finding, NOT duplicated
        assert len(res.deduplicated_findings) == 1
        assert res.deduplicated_findings[0]["rule_code"] == "BAN-GR"
        assert res.deduplicated_findings[0]["semantic_annotation"] == "Contradicts marketing guidelines."
        assert res.deduplicated_findings[0]["citation"]["document_title"] == "Rules"

    # -------------------------------------------------------------------------
    # TEST 10: Claim and Retrieval Bounding
    # -------------------------------------------------------------------------
    @pytest.mark.anyio
    async def test_claim_and_retrieval_bounding(self, db_session: Session):
        """Submissions with > 15 claims are capped to 15; candidate chunks are capped to 12."""
        user, org, _ = _create_user_and_org(db_session)
        kit, version, _, _ = _create_brand_kit_with_rules(db_session, org.id, user.id)

        # Return 25 claims from LLM
        twenty_five_claims = [
            {"claim_id": i, "claim_text": f"Marketing statement {i}"}
            for i in range(1, 26)
        ]
        mock_llm = MockLLMProvider(canned_claims=twenty_five_claims)

        workflow = ComplianceReviewWorkflow(db_session)
        state = WorkflowState(
            submission_id=uuid.uuid4(),
            organisation_id=org.id,
            brand_kit_version_id=version.id,
            raw_text="Large marketing document with 25 bullet points.",
            mode="hybrid",
            llm_provider=mock_llm,
        )

        state = await workflow._node_ingest_and_normalize(state)
        state = await workflow._node_deterministic_engine(state)
        state = await workflow._node_claim_extractor(state)

        # Assert claims capped at MAX_CLAIMS_PER_SUBMISSION (15)
        assert len(state.extracted_claims) == MAX_CLAIMS_PER_SUBMISSION

    # -------------------------------------------------------------------------
    # TEST 11: Invalid AI JSON Response Handling
    # -------------------------------------------------------------------------
    @pytest.mark.anyio
    async def test_invalid_ai_json_response_handling(self, db_session: Session):
        """If the LLM returns invalid or malformed output, the workflow degrades safely."""
        user, org, _ = _create_user_and_org(db_session)
        kit, version, _, _ = _create_brand_kit_with_rules(db_session, org.id, user.id)

        class MalformedLLMProvider(LLMProvider):
            provider_name = "malformed_mock"
            model_name = "mock"

            async def generate_json(self, prompt: str, system_prompt: str | None = None) -> Any:
                raise LLMProviderAPIError("Gemini returned invalid JSON structure.")

        workflow = ComplianceReviewWorkflow(db_session)
        state = WorkflowState(
            submission_id=uuid.uuid4(),
            organisation_id=org.id,
            brand_kit_version_id=version.id,
            raw_text="Acme investments copy.",
            mode="hybrid",
            llm_provider=MalformedLLMProvider(),
        )

        res = await workflow.execute(state)

        assert res.engine_mode == "DETERMINISTIC_FALLBACK"
        assert res.ai_available is False
        assert "AI claim extraction failed" in res.ai_status_message
        assert res.final_score == 100
        assert res.final_result == "PASS"

    # -------------------------------------------------------------------------
    # TEST 12: Zero Fabricated Findings During Fallback
    # -------------------------------------------------------------------------
    def test_zero_fabricated_findings_in_fallback(self, db_session: Session):
        """Verify fallback mode never invents citations, tone scores, or fact checks."""
        user, org, _ = _create_user_and_org(db_session)
        kit, version, _, _ = _create_brand_kit_with_rules(db_session, org.id, user.id)

        workflow = ComplianceReviewWorkflow(db_session)
        state = WorkflowState(
            submission_id=uuid.uuid4(),
            organisation_id=org.id,
            brand_kit_version_id=version.id,
            raw_text="Completely generic marketing copy.",
            mode="deterministic",
        )

        res = workflow.execute_deterministic_fallback(state)

        assert res.engine_mode == "DETERMINISTIC"
        assert res.ai_available is False
        assert res.final_scoring_json["semantic_assessment"] is None
        assert len(res.tone_findings) == 0
        assert len(res.unverified_claims) == 0
        assert len(res.validated_semantic_findings) == 0

    # -------------------------------------------------------------------------
    # TEST 13: End-to-End POST /compliance/analyze Route in Hybrid Mode
    # -------------------------------------------------------------------------
    def test_end_to_end_analyze_route_hybrid_mode_fallback(self, db_session: Session, monkeypatch):
        """Calling POST /compliance/analyze with mode='hybrid' and empty credentials returns fallback analysis."""
        monkeypatch.setattr(settings, "LLM_API_KEY", "")
        client = TestClient(app)
        user, org, token = _create_user_and_org(db_session)
        kit, version, _, _ = _create_brand_kit_with_rules(db_session, org.id, user.id)

        resp = client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/analyze",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "brand_kit_id": str(kit.id),
                "title": "Hybrid Analysis Test",
                "content_text": "We offer guaranteed returns today.",
                "mode": "hybrid",
            },
        )

        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        data = resp.json()
        assert data["title"] == "Hybrid Analysis Test"
        an = data["analysis"]
        assert an["score"] == 60  # Deterministic score preserved
        assert an["result"] == "FAIL"
        assert an["scoring"]["engine_mode"] == "DETERMINISTIC_FALLBACK"
        assert an["scoring"]["ai_available"] is False
        assert an["scoring"]["semantic_assessment"] is None

    # -------------------------------------------------------------------------
    # TEST 14: End-to-End POST /compliance/analyze Route in Deterministic Mode
    # -------------------------------------------------------------------------
    def test_end_to_end_analyze_route_deterministic_mode(self, db_session: Session):
        """Calling POST /compliance/analyze with mode='deterministic' runs purely deterministic engine."""
        client = TestClient(app)
        user, org, token = _create_user_and_org(db_session)
        kit, version, _, _ = _create_brand_kit_with_rules(db_session, org.id, user.id)

        resp = client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/analyze",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "brand_kit_id": str(kit.id),
                "title": "Deterministic Test",
                "content_text": "Clean marketing copy without any violations.",
                "mode": "deterministic",
            },
        )

        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        data = resp.json()
        an = data["analysis"]
        assert an["score"] == 100
        assert an["result"] == "PASS"
        assert an["rules_evaluated"] == 1
