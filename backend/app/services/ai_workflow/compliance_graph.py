"""LangGraph-aligned compliance review workflow state and graph execution (Phase 6.3).

Implements the 11 logical stages with conditional graph routing:
1. ingest_and_normalize
2. deterministic_engine
3. claim_extractor
4. vector_retriever
5. fact_verifier
6. tone_auditor
7. unverified_guard (CRITICAL EVIDENCE VALIDATION GATE)
8. deduplicate_and_score
9. remediation_generator
10. schema_validator
11. final_synthesis
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, List, Sequence

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.brand import (
    ApprovedBrandFact,
    BrandDocumentChunk,
    BrandGuidelineDocument,
    BrandIdentity,
    ComplianceRule,
    DocumentParsingStatus,
    FactCategory,
    FactRuleApprovalStatus,
    utcnow,
)
from app.models.compliance import ComplianceAnalysis, ContentSubmission
from app.services import compliance_engine
from app.services.ai_workflow.llm_provider import (
    LLMError,
    LLMNotConfiguredError,
    LLMProvider,
    LLMProviderAPIError,
    LLMTimeoutError,
    get_llm_provider,
    sanitize_prompt_input,
)
from app.services.rag.retriever import (
    RetrievedChunk,
    retrieve_candidate_chunks,
)

logger = logging.getLogger(__name__)

# Execution bounds (SEC-04 & Cost Controls)
MAX_CLAIMS_PER_SUBMISSION = 15
MAX_CHUNKS_PER_CLAIM = 3
MAX_CANDIDATE_CHUNKS = 12
MAX_SUBMISSION_CHARS = 50_000


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@dataclass
class WorkflowState:
    """State object passing through the 11 logical compliance stages."""

    # Input parameters
    submission_id: uuid.UUID
    organisation_id: uuid.UUID
    brand_kit_version_id: uuid.UUID
    raw_text: str
    mode: str = "hybrid"  # "hybrid" | "deterministic"
    llm_provider: LLMProvider | None = None
    include_experimental_score: bool = False

    # Stage 1: Ingest & Normalize
    normalized_text: str = ""
    content_sha256: str = ""

    # Stage 2: Deterministic Engine
    deterministic_findings: list[dict[str, Any]] = field(default_factory=list)
    deterministic_scoring: dict[str, Any] = field(default_factory=dict)
    deterministic_score: int = 100
    deterministic_result: str = "PASS"
    rules_evaluated: int = 0
    engine_mode: str = "HYBRID"
    ai_available: bool = True
    ai_status_message: str = "Semantic assessment active."

    # Stage 3: Claim Extractor
    extracted_claims: list[dict[str, Any]] = field(default_factory=list)

    # Stage 4: Vector Retriever
    candidate_chunks: list[RetrievedChunk] = field(default_factory=list)

    # Stage 5: Fact Verifier
    raw_fact_verifications: list[dict[str, Any]] = field(default_factory=list)

    # Stage 6: Tone Auditor
    tone_findings: list[dict[str, Any]] = field(default_factory=list)
    tone_grade: str = "ACCEPTABLE"
    tone_feedback: str = "Tone aligns with brand guidelines."

    # Stage 7: Unverified Guard
    validated_semantic_findings: list[dict[str, Any]] = field(default_factory=list)
    unverified_claims: list[dict[str, Any]] = field(default_factory=list)
    claims_verified_count: int = 0
    claims_unverified_count: int = 0
    claims_contradicted_count: int = 0

    # Stage 8: Deduplicate & Score
    deduplicated_findings: list[dict[str, Any]] = field(default_factory=list)
    final_score: int = 100
    final_result: str = "PASS"

    # Stage 9: Remediation Generator
    remediations: list[dict[str, Any]] = field(default_factory=list)

    # Stage 10 & 11: Schema Validator & Final Synthesis
    final_findings: list[dict[str, Any]] = field(default_factory=list)
    final_scoring_json: dict[str, Any] = field(default_factory=dict)
    node_execution_trace: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class ComplianceReviewWorkflow:
    """Orchestrates the 11 logical stages using conditional state graph execution."""

    def __init__(self, db: Session):
        self.db = db

    async def execute(self, state: WorkflowState) -> WorkflowState:
        """Run workflow state through the justified graph nodes."""
        # Node 1: Ingest and Normalize
        state = await self._node_ingest_and_normalize(state)

        # Node 2: Deterministic Engine
        state = await self._node_deterministic_engine(state)

        # Conditional Routing: If AI unavailable or deterministic mode requested, bypass AI stages
        if not state.ai_available or state.mode == "deterministic" or state.llm_provider is None:
            state.engine_mode = "DETERMINISTIC_FALLBACK" if state.mode == "hybrid" else "DETERMINISTIC"
            state.ai_available = False
            if state.mode == "deterministic":
                state.ai_status_message = "Deterministic mode requested: AI semantic assessment skipped."
            else:
                state.ai_status_message = "Semantic review bypassed: AI provider unconfigured or unreachable."
            state = await self._node_deduplicate_and_score(state)
            state = await self._node_remediation_generator(state)
            state = await self._node_schema_validator(state)
            state = await self._node_final_synthesis(state)
            return state

        # Node 3: Claim Extractor
        state = await self._node_claim_extractor(state)

        # If claim extraction encountered a fatal provider error and degraded to fallback
        if not state.ai_available or state.engine_mode == "DETERMINISTIC_FALLBACK":
            state = await self._node_deduplicate_and_score(state)
            state = await self._node_remediation_generator(state)
            state = await self._node_schema_validator(state)
            state = await self._node_final_synthesis(state)
            return state

        # Conditional Edge: If claims were extracted, run retrieval and fact verification
        if state.extracted_claims:
            # Node 4: Vector Retriever
            state = await self._node_vector_retriever(state)

            # Node 5: Fact Verifier
            state = await self._node_fact_verifier(state)

        # Node 6: Tone Auditor
        state = await self._node_tone_auditor(state)

        # If an error during fact verifier or tone auditor degraded provider
        if not state.ai_available:
            state.engine_mode = "DETERMINISTIC_FALLBACK"

        # Node 7: Unverified Guard (Mandatory Security Gate)
        state = await self._node_unverified_guard(state)

        # Node 8: Deduplicate & Score (Deterministic Preservation)
        state = await self._node_deduplicate_and_score(state)

        # Node 9: Remediation Generator
        state = await self._node_remediation_generator(state)

        # Node 10: Schema Validator
        state = await self._node_schema_validator(state)

        # Node 11: Final Synthesis
        state = await self._node_final_synthesis(state)

        return state

    def execute_deterministic_fallback(self, state: WorkflowState) -> WorkflowState:
        """Synchronously execute deterministic engine and fallback synthesis without async loop overhead."""
        # Node 1: Ingest and Normalize
        state.node_execution_trace.append("ingest_and_normalize")
        raw = state.raw_text or ""
        clean = raw.strip()
        if not clean:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Submission text cannot be empty.",
            )
        if len(clean) > MAX_SUBMISSION_CHARS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Submission text exceeds maximum limit of {MAX_SUBMISSION_CHARS} characters.",
            )
        state.normalized_text = clean
        state.content_sha256 = hashlib.sha256(clean.encode("utf-8")).hexdigest()

        # Node 2: Deterministic Engine
        state = self._sync_run_deterministic_engine(state)

        # Fallback routing
        state.engine_mode = "DETERMINISTIC_FALLBACK" if state.mode == "hybrid" else "DETERMINISTIC"
        state.ai_available = False
        if state.mode == "deterministic":
            state.ai_status_message = "Deterministic mode requested: AI semantic assessment skipped."
        else:
            state.ai_status_message = "Semantic review bypassed: AI provider unconfigured or unreachable."

        # Node 8, 9, 10, 11
        state = self._sync_deduplicate_and_score(state)
        state = self._sync_remediation_generator(state)
        state = self._sync_schema_validator(state)
        state = self._sync_final_synthesis(state)
        return state

    def _sync_run_deterministic_engine(self, state: WorkflowState) -> WorkflowState:
        state.node_execution_trace.append("deterministic_engine")
        now = datetime.now(timezone.utc)
        rules_stmt = (
            select(ComplianceRule)
            .where(
                ComplianceRule.brand_kit_version_id == state.brand_kit_version_id,
                ComplianceRule.organisation_id == state.organisation_id,
                ComplianceRule.is_active == True,
                ComplianceRule.approval_status == FactRuleApprovalStatus.APPROVED,
            )
            .order_by(ComplianceRule.priority.asc(), ComplianceRule.rule_code.asc())
        )
        rules = list(self.db.execute(rules_stmt).scalars().all())
        rule_specs = []
        for r in rules:
            if _aware(r.effective_from) and _aware(r.effective_from) > now:
                continue
            if _aware(r.effective_to) and _aware(r.effective_to) < now:
                continue
            rule_specs.append(
                compliance_engine.RuleSpec(
                    id=str(r.id),
                    rule_code=r.rule_code,
                    rule_type=r.rule_type,
                    severity=r.severity,
                    title=r.title,
                    description=r.description,
                    target_pattern=r.target_pattern,
                    match_mode=r.match_mode,
                    required_disclaimer_text=r.required_disclaimer_text,
                    suggested_replacement=r.suggested_replacement,
                    config=dict(r.rule_config_json or {}),
                )
            )

        pricing_facts = self.db.execute(
            select(ApprovedBrandFact.fact_value).where(
                ApprovedBrandFact.brand_kit_version_id == state.brand_kit_version_id,
                ApprovedBrandFact.organisation_id == state.organisation_id,
                ApprovedBrandFact.category == FactCategory.PRICING,
                ApprovedBrandFact.approval_status == FactRuleApprovalStatus.APPROVED,
                ApprovedBrandFact.is_active.is_(True),
            )
        ).scalars().all()

        approved_prices: list[str] = []
        for val in pricing_facts:
            approved_prices.extend(compliance_engine._extract_prices(val or ""))

        analysis_out = compliance_engine.analyze(
            state.normalized_text,
            rule_specs,
            approved_prices=approved_prices,
        )

        state.deterministic_findings = list(analysis_out.get("findings", []))
        state.deterministic_scoring = dict(analysis_out.get("scoring", {}))
        state.deterministic_score = int(analysis_out.get("score", 100))
        state.deterministic_result = str(analysis_out.get("result", "PASS"))
        state.rules_evaluated = int(analysis_out.get("rules_evaluated", len(rule_specs)))
        return state

    def _sync_deduplicate_and_score(self, state: WorkflowState) -> WorkflowState:
        state.node_execution_trace.append("deduplicate_and_score")
        state.deduplicated_findings = list(state.deterministic_findings)
        state.final_score = state.deterministic_score
        state.final_result = state.deterministic_result
        return state

    def _sync_remediation_generator(self, state: WorkflowState) -> WorkflowState:
        state.node_execution_trace.append("remediation_generator")
        remediations = []
        for finding in state.deduplicated_findings:
            replacement = finding.get("suggested_replacement")
            disclaimer = finding.get("required_disclaimer_text")
            if replacement or disclaimer:
                remediations.append({
                    "finding_id": finding.get("id"),
                    "action": "REPLACE" if replacement else "APPEND_DISCLAIMER",
                    "proposed_text": replacement or disclaimer,
                })
        state.remediations = remediations
        return state

    def _sync_schema_validator(self, state: WorkflowState) -> WorkflowState:
        state.node_execution_trace.append("schema_validator")
        valid_findings = []
        for f in state.deduplicated_findings:
            item = dict(f)
            item.setdefault("id", str(uuid.uuid4()))
            item.setdefault("rule_code", "COMPLIANCE-FINDING")
            item.setdefault("severity", "INFO")
            item.setdefault("title", "Compliance Finding")
            item.setdefault("description", "")
            item.setdefault("source", "RULE_ENGINE")
            valid_findings.append(item)
        state.final_findings = valid_findings
        return state

    def _sync_final_synthesis(self, state: WorkflowState) -> WorkflowState:
        state.node_execution_trace.append("final_synthesis")
        scoring: dict[str, Any] = {
            "formula": "100 - sum(deterministic_penalties)",
            "score": state.deterministic_score,
            "result": state.deterministic_result,
            "pass_threshold": state.deterministic_scoring.get("pass_threshold", 70),
            "penalties_total": state.deterministic_scoring.get("penalties_total", 0),
            "breakdown": state.deterministic_scoring.get("breakdown", []),
            "deterministic_score": state.deterministic_score,
            "deterministic_result": state.deterministic_result,
            "engine_mode": state.engine_mode,
            "ai_available": state.ai_available,
            "ai_status_message": state.ai_status_message,
            "rules_evaluated": state.rules_evaluated,
            "semantic_assessment": None,
            "remediations_count": len(state.remediations),
            "node_trace": state.node_execution_trace,
        }
        if state.include_experimental_score:
            scoring["experimental_score"] = state.deterministic_score
        state.final_scoring_json = scoring
        return state

    def execute_sync(self, state: WorkflowState) -> WorkflowState:
        """Synchronous execution wrapper: fast-paths deterministic fallback."""
        active_llm = state.llm_provider or get_llm_provider()
        if active_llm is None or state.mode == "deterministic":
            return self.execute_deterministic_fallback(state)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(lambda: asyncio.run(self.execute(state))).result()
        else:
            return asyncio.run(self.execute(state))

    # =========================================================================
    # Stage 1: Ingest and Normalize
    # =========================================================================
    async def _node_ingest_and_normalize(self, state: WorkflowState) -> WorkflowState:
        state.node_execution_trace.append("ingest_and_normalize")
        raw = state.raw_text or ""
        clean = raw.strip()
        if not clean:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Submission text cannot be empty.",
            )
        if len(clean) > MAX_SUBMISSION_CHARS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Submission text exceeds maximum limit of {MAX_SUBMISSION_CHARS} characters.",
            )

        state.normalized_text = clean
        state.content_sha256 = hashlib.sha256(clean.encode("utf-8")).hexdigest()
        return state

    # =========================================================================
    # Stage 2: Deterministic Engine
    # =========================================================================
    async def _node_deterministic_engine(self, state: WorkflowState) -> WorkflowState:
        state.node_execution_trace.append("deterministic_engine")

        now = datetime.now(timezone.utc)

        # Load active approved rules for this version
        rules_stmt = (
            select(ComplianceRule)
            .where(
                ComplianceRule.brand_kit_version_id == state.brand_kit_version_id,
                ComplianceRule.organisation_id == state.organisation_id,
                ComplianceRule.is_active == True,
                ComplianceRule.approval_status == FactRuleApprovalStatus.APPROVED,
            )
            .order_by(ComplianceRule.priority.asc(), ComplianceRule.rule_code.asc())
        )
        rules = list(self.db.execute(rules_stmt).scalars().all())

        rule_specs = []
        for r in rules:
            if _aware(r.effective_from) and _aware(r.effective_from) > now:
                continue
            if _aware(r.effective_to) and _aware(r.effective_to) < now:
                continue
            rule_specs.append(
                compliance_engine.RuleSpec(
                    id=str(r.id),
                    rule_code=r.rule_code,
                    rule_type=r.rule_type,
                    severity=r.severity,
                    title=r.title,
                    description=r.description,
                    target_pattern=r.target_pattern,
                    match_mode=r.match_mode,
                    required_disclaimer_text=r.required_disclaimer_text,
                    suggested_replacement=r.suggested_replacement,
                    config=dict(r.rule_config_json or {}),
                )
            )

        # Load approved pricing facts
        pricing_facts = self.db.execute(
            select(ApprovedBrandFact.fact_value).where(
                ApprovedBrandFact.brand_kit_version_id == state.brand_kit_version_id,
                ApprovedBrandFact.organisation_id == state.organisation_id,
                ApprovedBrandFact.category == FactCategory.PRICING,
                ApprovedBrandFact.approval_status == FactRuleApprovalStatus.APPROVED,
                ApprovedBrandFact.is_active.is_(True),
            )
        ).scalars().all()

        approved_prices: list[str] = []
        for val in pricing_facts:
            approved_prices.extend(compliance_engine._extract_prices(val or ""))

        analysis_out = compliance_engine.analyze(
            state.normalized_text,
            rule_specs,
            approved_prices=approved_prices,
        )

        state.deterministic_findings = list(analysis_out.get("findings", []))
        state.deterministic_scoring = dict(analysis_out.get("scoring", {}))
        state.deterministic_score = int(analysis_out.get("score", 100))
        state.deterministic_result = str(analysis_out.get("result", "PASS"))
        state.rules_evaluated = int(analysis_out.get("rules_evaluated", len(rule_specs)))

        # Resolve active LLM provider
        active_llm = state.llm_provider or get_llm_provider()
        if active_llm is None or state.mode == "deterministic":
            state.ai_available = False
            state.llm_provider = None
        else:
            state.ai_available = True
            state.llm_provider = active_llm

        return state

    # =========================================================================
    # Stage 3: Claim Extractor
    # =========================================================================
    async def _node_claim_extractor(self, state: WorkflowState) -> WorkflowState:
        state.node_execution_trace.append("claim_extractor")
        if not state.llm_provider:
            return state

        safe_text = sanitize_prompt_input(state.normalized_text)
        prompt = (
            f"Extract all factual, pricing, performance, and superlative marketing claims from the following text:\n"
            f"<submission>\n{safe_text}\n</submission>\n\n"
            f"Output JSON format:\n"
            f'{{"claims": [{{"claim_id": 1, "claim_text": "...", "category": "PRICING|SUPERLATIVE|FACT"}}]}}'
        )

        try:
            res = await state.llm_provider.generate_json(prompt, system_prompt="You are a legal and brand fact extraction model.")
            if not isinstance(res, dict):
                raise LLMProviderAPIError(f"Expected dict response from LLM, got {type(res).__name__}")
            raw_claims = res.get("claims", [])
            if not isinstance(raw_claims, list):
                raw_claims = []
            # Bounded: maximum 15 claims
            state.extracted_claims = raw_claims[:MAX_CLAIMS_PER_SUBMISSION]
        except (LLMTimeoutError, LLMProviderAPIError, LLMNotConfiguredError, LLMError) as exc:
            logger.warning("LLM provider error in claim_extractor: %s; degrading to deterministic fallback", exc)
            state.engine_mode = "DETERMINISTIC_FALLBACK"
            state.ai_available = False
            state.ai_status_message = f"AI claim extraction failed ({type(exc).__name__}); degraded to deterministic evaluation."
            state.errors.append(str(exc))
            state.extracted_claims = []
        except Exception as exc:
            logger.warning("Unexpected error in claim_extractor: %s; degrading to fallback", exc)
            state.engine_mode = "DETERMINISTIC_FALLBACK"
            state.ai_available = False
            state.ai_status_message = f"AI claim extraction failed; degraded to deterministic evaluation."
            state.errors.append(str(exc))
            state.extracted_claims = []

        return state

    # =========================================================================
    # Stage 4: Vector Retriever
    # =========================================================================
    async def _node_vector_retriever(self, state: WorkflowState) -> WorkflowState:
        state.node_execution_trace.append("vector_retriever")
        unique_chunks_map: dict[uuid.UUID, RetrievedChunk] = {
            c.chunk_id: c for c in state.candidate_chunks
        }

        for claim in state.extracted_claims:
            claim_text = str(claim.get("claim_text", "")).strip()
            if not claim_text:
                continue

            try:
                # Query up to 3 chunks per claim
                retrieved = await retrieve_candidate_chunks(
                    self.db,
                    organisation_id=state.organisation_id,
                    brand_kit_version_id=state.brand_kit_version_id,
                    query_text=claim_text,
                    top_k=MAX_CHUNKS_PER_CLAIM,
                    similarity_threshold=0.72,
                    allow_unembedded_docs=True,
                )
                for rc in retrieved:
                    unique_chunks_map[rc.chunk_id] = rc
                    # Capped at 12 unique candidate chunks overall
                    if len(unique_chunks_map) >= MAX_CANDIDATE_CHUNKS:
                        break
            except Exception as exc:
                logger.warning("Retrieval failed for claim '%s': %s", claim_text[:30], exc)

            if len(unique_chunks_map) >= MAX_CANDIDATE_CHUNKS:
                break

        state.candidate_chunks = list(unique_chunks_map.values())
        return state

    # =========================================================================
    # Stage 5: Fact Verifier
    # =========================================================================
    async def _node_fact_verifier(self, state: WorkflowState) -> WorkflowState:
        state.node_execution_trace.append("fact_verifier")
        if not state.llm_provider or not state.extracted_claims:
            return state

        # If zero candidate chunks retrieved, all claims are unbacked -> proceed to unverified_guard
        if not state.candidate_chunks:
            state.raw_fact_verifications = [
                {
                    "claim_id": c.get("claim_id"),
                    "status": "UNVERIFIED",
                    "citation_chunk_id": None,
                    "explanation": "No matching guideline documents found.",
                }
                for c in state.extracted_claims
            ]
            return state

        # Prepare candidate excerpts
        chunks_excerpt = "\n".join(
            [f"[Chunk ID: {c.chunk_id}] (Doc: {c.document_title}, Page: {c.page_number}): {c.content}" for c in state.candidate_chunks]
        )
        claims_text = "\n".join([f"Claim {c.get('claim_id')}: {c.get('claim_text')}" for c in state.extracted_claims])

        prompt = (
            f"Verify whether each claim is supported by the guideline document chunks:\n"
            f"<candidate_chunks>\n{chunks_excerpt}\n</candidate_chunks>\n\n"
            f"<claims>\n{claims_text}\n</claims>\n\n"
            f"Output JSON format:\n"
            f'{{"verifications": [{{"claim_id": 1, "status": "VERIFIED|CONTRADICTED|UNVERIFIED", "citation_chunk_id": "<uuid-or-null>", "citation_text": "...", "explanation": "..."}}]}}'
        )

        try:
            res = await state.llm_provider.generate_json(prompt, system_prompt="You are a strict compliance fact verification auditor.")
            raw_verifs = res.get("verifications", []) if isinstance(res, dict) else []
            state.raw_fact_verifications = raw_verifs
        except (LLMTimeoutError, LLMProviderAPIError, LLMNotConfiguredError, LLMError) as exc:
            logger.warning("Fact verifier LLM error: %s; falling back to unverified guard", exc)
            state.errors.append(str(exc))
            # Safely degrade: all claims unverified
            state.raw_fact_verifications = [
                {
                    "claim_id": c.get("claim_id"),
                    "status": "UNVERIFIED",
                    "citation_chunk_id": None,
                    "explanation": f"Fact verifier unavailable: {exc}",
                }
                for c in state.extracted_claims
            ]
        except Exception as exc:
            logger.warning("Fact verifier unexpected error: %s", exc)
            state.errors.append(str(exc))
            state.raw_fact_verifications = []

        return state

    # =========================================================================
    # Stage 6: Tone Auditor
    # =========================================================================
    async def _node_tone_auditor(self, state: WorkflowState) -> WorkflowState:
        state.node_execution_trace.append("tone_auditor")
        if not state.llm_provider:
            return state

        # Fetch BrandIdentity
        identity = self.db.execute(
            select(BrandIdentity).where(
                BrandIdentity.brand_kit_version_id == state.brand_kit_version_id,
                BrandIdentity.organisation_id == state.organisation_id,
            )
        ).scalar_one_or_none()

        guidelines = identity.brand_voice_guidelines if identity else None
        if not guidelines or not guidelines.strip():
            state.tone_grade = "NOT_CONFIGURED"
            state.tone_feedback = "Brand voice guidelines not configured for this version."
            return state

        safe_text = sanitize_prompt_input(state.normalized_text)
        prompt = (
            f"Evaluate the marketing text against the brand voice guidelines:\n"
            f"<guidelines>\n{guidelines}\n</guidelines>\n\n"
            f"<submission>\n{safe_text}\n</submission>\n\n"
            f"Output JSON format:\n"
            f'{{"tone_grade": "EXCELLENT|ACCEPTABLE|NEEDS_WORK", "tone_feedback": "...", "tone_findings": [{{"rule_code": "TONE-VOICE", "title": "Tone Inconsistency", "description": "...", "severity": "LOW|MEDIUM", "start": 0, "end": 10}}]}}'
        )

        try:
            res = await state.llm_provider.generate_json(prompt, system_prompt="You are an enterprise brand voice auditor.")
            if isinstance(res, dict):
                state.tone_grade = res.get("tone_grade", "ACCEPTABLE")
                state.tone_feedback = res.get("tone_feedback", "Tone evaluated against brand guidelines.")
                tone_list = res.get("tone_findings", [])
                for item in tone_list:
                    item["source"] = "TONE_ANALYSIS"
                    state.tone_findings.append(item)
        except Exception as exc:
            logger.warning("Tone audit failed: %s; continuing without tone findings", exc)
            state.errors.append(f"Tone auditor error: {exc}")
            state.tone_grade = "ERROR"
            state.tone_feedback = "Tone evaluation temporarily unavailable."

        return state

    # =========================================================================
    # Stage 7: Unverified Guard (CRITICAL EVIDENCE VALIDATION GATE)
    # =========================================================================
    async def _node_unverified_guard(self, state: WorkflowState) -> WorkflowState:
        """Never trust LLM-generated citations without database validation.

        Strips citations and classifies as UNVERIFIED_CLAIM if:
        1. citation_chunk_id is missing, invalid UUID, or not in candidate_chunks.
        2. chunk does not belong to the submission's organisation_id and brand_kit_version_id.
        3. chunk's document does not belong to the submission's organisation_id and brand_kit_version_id.
        """
        state.node_execution_trace.append("unverified_guard")

        candidate_chunk_map = {str(c.chunk_id): c for c in state.candidate_chunks}
        claims_map = {c.get("claim_id"): c for c in state.extracted_claims}

        processed_claim_ids = set()

        for verif in state.raw_fact_verifications:
            claim_id = verif.get("claim_id")
            processed_claim_ids.add(claim_id)

            claim = claims_map.get(claim_id, {})
            claim_text = claim.get("claim_text", "")
            proposed_chunk_id = str(verif.get("citation_chunk_id") or "").strip()
            verif_status = str(verif.get("status", "UNVERIFIED")).upper()

            is_valid_citation = False
            matching_chunk: RetrievedChunk | None = None

            # 1. Candidate chunk membership check
            if proposed_chunk_id and proposed_chunk_id in candidate_chunk_map:
                candidate = candidate_chunk_map[proposed_chunk_id]
                # 2. Defense-in-depth database verification: Ensure chunk belongs to same org and version
                chunk_record = self.db.execute(
                    select(BrandDocumentChunk)
                    .join(
                        BrandGuidelineDocument,
                        BrandDocumentChunk.document_id == BrandGuidelineDocument.id,
                    )
                    .where(
                        BrandDocumentChunk.id == candidate.chunk_id,
                        BrandDocumentChunk.organisation_id == state.organisation_id,
                        BrandDocumentChunk.brand_kit_version_id == state.brand_kit_version_id,
                        BrandGuidelineDocument.organisation_id == state.organisation_id,
                        BrandGuidelineDocument.brand_kit_version_id == state.brand_kit_version_id,
                    )
                ).scalar_one_or_none()

                if chunk_record is not None:
                    is_valid_citation = True
                    matching_chunk = candidate

            # Handle VERIFIED
            if is_valid_citation and matching_chunk and verif_status == "VERIFIED":
                state.claims_verified_count += 1
                finding = {
                    "id": str(uuid.uuid4()),
                    "rule_code": "RAG-VERIFIED-FACT",
                    "rule_type": "FACTUAL_CLAIM",
                    "severity": "INFO",
                    "title": "Verified Claim",
                    "description": f"Claim backed by approved guideline document '{matching_chunk.document_title}'.",
                    "matched_text": claim_text,
                    "evidence_excerpt": matching_chunk.content[:200],
                    "citation": {
                        "chunk_id": str(matching_chunk.chunk_id),
                        "document_id": str(matching_chunk.document_id),
                        "document_title": matching_chunk.document_title,
                        "page_number": matching_chunk.page_number,
                        "section_heading": matching_chunk.section_heading,
                        "similarity_score": matching_chunk.similarity_score,
                    },
                    "source": "RAG_SEMANTIC",
                    "status": "VERIFIED",
                }
                state.validated_semantic_findings.append(finding)

            # Handle CONTRADICTED
            elif is_valid_citation and matching_chunk and verif_status == "CONTRADICTED":
                state.claims_contradicted_count += 1
                finding = {
                    "id": str(uuid.uuid4()),
                    "rule_code": "RAG-CONTRADICTED-CLAIM",
                    "rule_type": "FACTUAL_CONTRADICTION",
                    "severity": "HIGH",
                    "title": "Contradicted Marketing Claim",
                    "description": f"Claim contradicts approved brand guideline document '{matching_chunk.document_title}'.",
                    "matched_text": claim_text,
                    "evidence_excerpt": matching_chunk.content[:200],
                    "citation": {
                        "chunk_id": str(matching_chunk.chunk_id),
                        "document_id": str(matching_chunk.document_id),
                        "document_title": matching_chunk.document_title,
                        "page_number": matching_chunk.page_number,
                        "section_heading": matching_chunk.section_heading,
                        "similarity_score": matching_chunk.similarity_score,
                    },
                    "source": "RAG_SEMANTIC",
                    "status": "CONTRADICTED",
                }
                state.validated_semantic_findings.append(finding)

            # Fallback to UNVERIFIED (strips invalid, hallucinated, or unbacked citation)
            else:
                state.claims_unverified_count += 1
                unverified_finding = {
                    "id": str(uuid.uuid4()),
                    "rule_code": "RAG-UNVERIFIED-CLAIM",
                    "rule_type": "UNVERIFIED_CLAIM",
                    "severity": "LOW",
                    "title": "Unverified Marketing Claim",
                    "description": "This marketing claim could not be verified against any approved brand guideline document or fact.",
                    "matched_text": claim_text,
                    "evidence_excerpt": None,
                    "citation": None,  # Stripped! Never trust unverified citation IDs
                    "source": "RAG_SEMANTIC",
                    "kind": "UNVERIFIED_CLAIM",
                    "status": "UNVERIFIED",
                }
                state.unverified_claims.append(unverified_finding)
                state.validated_semantic_findings.append(unverified_finding)

        # Catch any extracted claim that was not in raw_fact_verifications
        for claim in state.extracted_claims:
            cid = claim.get("claim_id")
            if cid not in processed_claim_ids:
                state.claims_unverified_count += 1
                unverified_finding = {
                    "id": str(uuid.uuid4()),
                    "rule_code": "RAG-UNVERIFIED-CLAIM",
                    "rule_type": "UNVERIFIED_CLAIM",
                    "severity": "LOW",
                    "title": "Unverified Marketing Claim",
                    "description": "This marketing claim could not be verified against any approved brand guideline document or fact.",
                    "matched_text": claim.get("claim_text", ""),
                    "evidence_excerpt": None,
                    "citation": None,
                    "source": "RAG_SEMANTIC",
                    "kind": "UNVERIFIED_CLAIM",
                    "status": "UNVERIFIED",
                }
                state.unverified_claims.append(unverified_finding)
                state.validated_semantic_findings.append(unverified_finding)

        return state

    # =========================================================================
    # Stage 8: Deduplicate and Score (Deterministic Score Preservation)
    # =========================================================================
    async def _node_deduplicate_and_score(self, state: WorkflowState) -> WorkflowState:
        """Preserves authoritative deterministic compliance score and deduplicates overlapping findings."""
        state.node_execution_trace.append("deduplicate_and_score")

        # Deterministic findings are authoritative
        deduped = list(state.deterministic_findings)

        # Build index of existing spans and text matches
        existing_spans = set()
        existing_matches = set()
        for f in state.deterministic_findings:
            start = f.get("start")
            end = f.get("end")
            rule_code = f.get("rule_code")
            matched_text = (f.get("matched_text") or "").strip().lower()
            if start is not None and end is not None:
                existing_spans.add((start, end))
            if matched_text:
                existing_matches.add(matched_text)

        # Append non-overlapping semantic findings
        for sf in state.validated_semantic_findings:
            sf_start = sf.get("start")
            sf_end = sf.get("end")
            sf_text = (sf.get("matched_text") or "").strip().lower()

            # Overlap check on character spans
            if sf_start is not None and sf_end is not None and (sf_start, sf_end) in existing_spans:
                # Annotate existing finding rather than duplicate
                for det in deduped:
                    if det.get("start") == sf_start and det.get("end") == sf_end:
                        det["semantic_annotation"] = sf.get("description")
                        if sf.get("citation"):
                            det["citation"] = sf["citation"]
                continue

            # Overlap check on exact matched text
            if sf_text and sf_text in existing_matches:
                for det in deduped:
                    if (det.get("matched_text") or "").strip().lower() == sf_text:
                        det["semantic_annotation"] = sf.get("description")
                        if sf.get("citation"):
                            det["citation"] = sf["citation"]
                continue

            deduped.append(sf)

        # Append tone findings
        for tf in state.tone_findings:
            deduped.append(tf)

        state.deduplicated_findings = deduped

        # Authoritative score preservation: deterministic score is NEVER lowered by semantic findings
        state.final_score = state.deterministic_score
        state.final_result = state.deterministic_result

        return state

    # =========================================================================
    # Stage 9: Remediation Generator
    # =========================================================================
    async def _node_remediation_generator(self, state: WorkflowState) -> WorkflowState:
        state.node_execution_trace.append("remediation_generator")
        remediations = []
        for finding in state.deduplicated_findings:
            replacement = finding.get("suggested_replacement")
            disclaimer = finding.get("required_disclaimer_text")
            if replacement or disclaimer:
                remediations.append({
                    "finding_id": finding.get("id"),
                    "action": "REPLACE" if replacement else "APPEND_DISCLAIMER",
                    "proposed_text": replacement or disclaimer,
                })
        state.remediations = remediations
        return state

    # =========================================================================
    # Stage 10: Schema Validator
    # =========================================================================
    async def _node_schema_validator(self, state: WorkflowState) -> WorkflowState:
        state.node_execution_trace.append("schema_validator")
        valid_findings = []
        for f in state.deduplicated_findings:
            item = dict(f)
            item.setdefault("id", str(uuid.uuid4()))
            item.setdefault("rule_code", "COMPLIANCE-FINDING")
            item.setdefault("severity", "INFO")
            item.setdefault("title", "Compliance Finding")
            item.setdefault("description", "")
            item.setdefault("source", "RULE_ENGINE")
            valid_findings.append(item)

        state.final_findings = valid_findings
        return state

    # =========================================================================
    # Stage 11: Final Synthesis
    # =========================================================================
    async def _node_final_synthesis(self, state: WorkflowState) -> WorkflowState:
        state.node_execution_trace.append("final_synthesis")

        scoring: dict[str, Any] = {
            "formula": "100 - sum(deterministic_penalties)",
            "score": state.deterministic_score,
            "result": state.deterministic_result,
            "pass_threshold": state.deterministic_scoring.get("pass_threshold", 70),
            "penalties_total": state.deterministic_scoring.get("penalties_total", 0),
            "breakdown": state.deterministic_scoring.get("breakdown", []),
            "deterministic_score": state.deterministic_score,
            "deterministic_result": state.deterministic_result,
            "engine_mode": state.engine_mode,
            "ai_available": state.ai_available,
            "ai_status_message": state.ai_status_message,
            "rules_evaluated": state.rules_evaluated,
            "remediations_count": len(state.remediations),
            "node_trace": state.node_execution_trace,
        }

        if state.ai_available:
            scoring["semantic_assessment"] = {
                "claims_evaluated": len(state.extracted_claims),
                "claims_verified": state.claims_verified_count,
                "claims_unverified": state.claims_unverified_count,
                "claims_contradicted": state.claims_contradicted_count,
                "tone_grade": state.tone_grade,
                "tone_feedback": state.tone_feedback,
            }
        else:
            scoring["semantic_assessment"] = None

        if state.include_experimental_score:
            exp_score = max(
                0,
                state.deterministic_score
                - (20 * state.claims_contradicted_count)
                - (10 * state.claims_unverified_count),
            )
            scoring["experimental_score"] = exp_score

        state.final_scoring_json = scoring
        return state
