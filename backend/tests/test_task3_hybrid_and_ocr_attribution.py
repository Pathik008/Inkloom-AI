"""Focused test suite for Task 3:
1. Hybrid AI workflow provider initialization and vector retriever reachability.
2. Deterministic mode AI bypass and safe provider-failure fallbacks.
3. Scanned PDF OCR page-level attribution and chunk metadata preservation.
"""
from __future__ import annotations

import io
import uuid
import pytest
from PIL import Image, ImageDraw
import pypdf
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, init_db
from app.models import Organisation, OrganisationMembership, Role, RoleName, User
from app.models.brand import (
    BrandKit,
    BrandKitVersion,
    BrandKitVersionStatus,
    ComplianceRule,
    ComplianceRuleType,
    FactRuleApprovalStatus,
    RuleMatchMode,
    RuleSeverity,
)
from app.services.ai_workflow.compliance_graph import (
    ComplianceReviewWorkflow,
    WorkflowState,
)
from app.services.ai_workflow.llm_provider import (
    LLMProvider,
    LLMTimeoutError,
    MockLLMProvider,
)
from app.services import document_extraction_service as doc_service
from app.services.rag import chunking_service


@pytest.fixture
def task3_db() -> Session:
    """In-memory SQLite session with schema initialized."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSession()
    init_db(session=session)
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def task3_brand_fixture(task3_db: Session) -> dict:
    """Fixture providing user, org, and BrandKitVersion with compliance rules."""
    db = task3_db
    user = User(
        id=uuid.uuid4(),
        email=f"tester-{uuid.uuid4().hex[:6]}@inkloom.ai",
        full_name="Task 3 Auditor",
        password_hash="hash",
        is_active=True,
        is_verified=True,
    )
    db.add(user)
    db.flush()

    org = Organisation(
        id=uuid.uuid4(),
        name="Task 3 Enterprise",
        slug=f"t3-{uuid.uuid4().hex[:6]}",
        created_by=user.id,
    )
    db.add(org)
    db.flush()

    admin_role = db.query(Role).filter(Role.name == RoleName.ADMIN).first()
    db.add(OrganisationMembership(
        id=uuid.uuid4(),
        user_id=user.id,
        organisation_id=org.id,
        role_id=admin_role.id,
    ))

    kit = BrandKit(
        id=uuid.uuid4(),
        organisation_id=org.id,
        name="Enterprise Kit",
        slug=f"ent-kit-{uuid.uuid4().hex[:6]}",
        created_by_user_id=user.id,
    )
    db.add(kit)
    db.flush()

    version = BrandKitVersion(
        id=uuid.uuid4(),
        brand_kit_id=kit.id,
        organisation_id=org.id,
        version_number=1,
        status=BrandKitVersionStatus.DRAFT,
        created_by_user_id=user.id,
    )
    db.add(version)
    db.flush()

    # Rule: Prohibited risk-free claim
    rule = ComplianceRule(
        id=uuid.uuid4(),
        brand_kit_version_id=version.id,
        organisation_id=org.id,
        rule_code="PROHIBITED_GUARANTEE",
        rule_type=ComplianceRuleType.PROHIBITED_TERM,
        severity=RuleSeverity.CRITICAL,
        title="No Guarantees Allowed",
        description="Risk-free guarantees are forbidden.",
        target_pattern="risk-free",
        match_mode=RuleMatchMode.CASE_INSENSITIVE,
        source_reference="Policy Section 1.2",
        approval_status=FactRuleApprovalStatus.APPROVED,
        is_active=True,
        created_by_user_id=user.id,
    )
    db.add(rule)
    db.flush()

    version.status = BrandKitVersionStatus.PUBLISHED
    kit.active_version_id = version.id
    db.commit()

    return {
        "user": user,
        "org": org,
        "kit": kit,
        "version": version,
        "rule": rule,
    }


# =============================================================================
# PART A TESTS — HYBRID AI WORKFLOW & PROVIDER INITIALIZATION
# =============================================================================

def test_hybrid_mode_with_mock_provider_reaches_vector_retriever(task3_db: Session, task3_brand_fixture: dict, monkeypatch: pytest.MonkeyPatch):
    """When hybrid mode is requested and LLM provider is configured, workflow initializes

    provider and reaches claim_extractor and vector_retriever nodes.
    """
    data = task3_brand_fixture
    workflow = ComplianceReviewWorkflow(task3_db)

    mock_llm = MockLLMProvider(
        canned_claims=[
            {
                "claim_id": 1,
                "claim_text": "Investments offer guaranteed 10% annual return.",
                "category": "PERFORMANCE",
            }
        ]
    )
    monkeypatch.setattr("app.services.ai_workflow.compliance_graph.get_llm_provider", lambda: mock_llm)

    state = WorkflowState(
        submission_id=uuid.uuid4(),
        organisation_id=data["org"].id,
        brand_kit_version_id=data["version"].id,
        raw_text="Our platform offers guaranteed risk-free investments.",
        mode="hybrid",
        # Notice: llm_provider is intentionally omitted (None) to test automatic resolution
    )

    res = workflow.execute_sync(state)

    # 1. Verify provider was resolved and engine mode is HYBRID
    assert res.llm_provider is mock_llm
    assert res.engine_mode == "HYBRID"
    assert res.ai_available is True

    # 2. Verify AI execution trace reached claim extraction and vector retrieval
    assert "claim_extractor" in res.node_execution_trace
    assert "vector_retriever" in res.node_execution_trace
    assert "fact_verifier" in res.node_execution_trace
    assert "tone_auditor" in res.node_execution_trace
    assert "unverified_guard" in res.node_execution_trace

    # 3. Verify deterministic scoring was preserved authoritatively
    assert res.deterministic_score == 60  # 100 - 40
    assert res.final_score == 60


def test_hybrid_mode_with_no_provider_falls_back_safely(task3_db: Session, task3_brand_fixture: dict, monkeypatch: pytest.MonkeyPatch):
    """When hybrid mode is requested but no API key is configured, workflow falls back

    to deterministic mode without error and does not invoke AI nodes.
    """
    data = task3_brand_fixture
    workflow = ComplianceReviewWorkflow(task3_db)

    monkeypatch.setattr("app.services.ai_workflow.compliance_graph.get_llm_provider", lambda: None)

    state = WorkflowState(
        submission_id=uuid.uuid4(),
        organisation_id=data["org"].id,
        brand_kit_version_id=data["version"].id,
        raw_text="Our platform offers guaranteed risk-free investments.",
        mode="hybrid",
        llm_provider=None,
    )

    res = workflow.execute_sync(state)

    assert res.engine_mode == "DETERMINISTIC_FALLBACK"
    assert res.ai_available is False
    assert "claim_extractor" not in res.node_execution_trace
    assert "vector_retriever" not in res.node_execution_trace
    assert res.final_score == 60


def test_deterministic_mode_bypasses_ai_completely(task3_db: Session, task3_brand_fixture: dict, monkeypatch: pytest.MonkeyPatch):
    """When deterministic mode is requested, AI is completely bypassed even if LLM provider exists."""
    data = task3_brand_fixture
    workflow = ComplianceReviewWorkflow(task3_db)

    mock_llm = MockLLMProvider(
        canned_claims=[
            {
                "claim_id": 1,
                "claim_text": "Investments offer guaranteed 10% annual return.",
                "category": "PERFORMANCE",
            }
        ]
    )
    monkeypatch.setattr("app.services.ai_workflow.compliance_graph.get_llm_provider", lambda: mock_llm)

    state = WorkflowState(
        submission_id=uuid.uuid4(),
        organisation_id=data["org"].id,
        brand_kit_version_id=data["version"].id,
        raw_text="Our platform offers guaranteed risk-free investments.",
        mode="deterministic",
    )

    res = workflow.execute_sync(state)

    assert res.engine_mode == "DETERMINISTIC"
    assert res.ai_available is False
    assert "claim_extractor" not in res.node_execution_trace
    assert "vector_retriever" not in res.node_execution_trace
    assert res.final_score == 60


def test_provider_failure_degrades_to_deterministic_fallback(task3_db: Session, task3_brand_fixture: dict, monkeypatch: pytest.MonkeyPatch):
    """When configured provider times out during claim extraction, workflow degrades safely to deterministic fallback."""
    class FailingLLMProvider(LLMProvider):
        provider_name = "failing"
        model_name = "failing-model"

        async def generate_text(self, prompt: str, **kwargs) -> str:
            raise LLMTimeoutError("Inference timed out")

        async def generate_json(self, prompt: str, **kwargs) -> dict:
            raise LLMTimeoutError("Inference timed out")

    data = task3_brand_fixture
    workflow = ComplianceReviewWorkflow(task3_db)

    monkeypatch.setattr("app.services.ai_workflow.compliance_graph.get_llm_provider", lambda: FailingLLMProvider())

    state = WorkflowState(
        submission_id=uuid.uuid4(),
        organisation_id=data["org"].id,
        brand_kit_version_id=data["version"].id,
        raw_text="Our platform offers guaranteed risk-free investments.",
        mode="hybrid",
    )

    res = workflow.execute_sync(state)

    assert res.engine_mode == "DETERMINISTIC_FALLBACK"
    assert res.ai_available is False
    assert res.final_score == 60


# =============================================================================
# PART B TESTS — SCANNED PDF PAGE ATTRIBUTION & CHUNK METADATA
# =============================================================================

def _create_raster_page_image(text: str) -> bytes:
    """Generate high-contrast PNG bitmap with multiline text."""
    img = Image.new("RGB", (1200, 300), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.multiline_text((25, 25), text, fill=(0, 0, 0), spacing=8)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _create_scanned_multipage_pdf() -> bytes:
    """Create a 2-page PDF containing only raster images (no pypdf native text streams)."""
    buf = io.BytesIO()
    writer = pypdf.PdfWriter()

    # Page 1: image with "PAGE ONE BRAND GUIDELINES"
    img1_bytes = _create_raster_page_image("PAGE ONE BRAND GUIDELINES")
    page1 = writer.add_blank_page(width=500, height=150)
    # In pypdf, attach raster image
    # For a lightweight unit test, we can inject image stream into page
    # Or test try_ocr_pdf_fallback directly with mock reader
    writer.write(buf)
    return buf.getvalue()


def test_try_ocr_pdf_fallback_per_page_attribution(monkeypatch: pytest.MonkeyPatch):
    """Validate that try_ocr_pdf_fallback populates text per page and retains accurate page numbers."""
    class MockImg:
        def __init__(self, data: bytes):
            self.data = data

    class MockPage:
        def __init__(self, text: str):
            self.images = [MockImg(_create_raster_page_image(text))]

    class MockReader:
        def __init__(self, page_texts: list[str]):
            self.pages = [MockPage(t) for t in page_texts]

    p1_str = (
        "POLICIES:\n"
        "All marketing materials must strictly follow brand identity guidelines.\n"
        "Tone of voice requirements apply across all regional enterprise campaigns.\n"
        "Content creators must ensure compliance before final publication."
    )
    p2_str = (
        "DISCLOSURES:\n"
        "Every consumer finance product must clearly state regulatory terms.\n"
        "Statutory disclaimers must be clearly visible and completely legible.\n"
        "Omission of risk warnings will result in immediate content rejection."
    )

    reader = MockReader([p1_str, p2_str])
    pages_out: list[dict] = [
        {"page_number": 1, "text": ""},
        {"page_number": 2, "text": ""},
    ]

    import shutil
    if not shutil.which("tesseract"):
        pytest.skip("Tesseract binary not installed on host PATH (tested inside container).")

    full_text = doc_service.try_ocr_pdf_fallback(reader, pages_out=pages_out)

    # 1. Full text contains both pages
    assert "POLICIES" in full_text.upper()
    assert "DISCLOSURES" in full_text.upper()

    # 2. pages_out has page-level text matching the corresponding page
    assert len(pages_out) == 2
    assert pages_out[0]["page_number"] == 1
    assert "POLICIES" in pages_out[0]["text"].upper()
    assert "DISCLOSURES" not in pages_out[0]["text"].upper()

    assert pages_out[1]["page_number"] == 2
    assert "DISCLOSURES" in pages_out[1]["text"].upper()
    assert "POLICIES" not in pages_out[1]["text"].upper()

    # 3. Chunking service receives correct page numbers
    chunks = chunking_service.chunk_document_text(
        text=full_text,
        document_id=uuid.uuid4(),
        brand_kit_version_id=uuid.uuid4(),
        organisation_id=uuid.uuid4(),
        target_tokens=25,  # force small chunks across both pages
        overlap_tokens=0,
        page_metadata=pages_out,
    )

    assert len(chunks) >= 2
    # First chunk belongs to Page 1
    assert chunks[0].page_number == 1
    # Chunk from second page belongs to Page 2
    page_numbers = {c.page_number for c in chunks}
    assert 1 in page_numbers
    assert 2 in page_numbers
