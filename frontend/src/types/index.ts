export interface HealthStatus {
  status: string;
  service: string;
  version: string;
  environment: string;
  database_status: string;
  database_connected: boolean;
  pgvector_target_dimension: number;
  timestamp: string;
}

export interface ModuleRoadmapItem {
  id: string;
  phase: number;
  name: string;
  owner: string;
  status: 'implemented' | 'planned';
  description: string;
  route: string;
  requiredPermission?: string;
}

export type RoleName = 'ADMIN' | 'BRAND_MANAGER' | 'CONTENT_CREATOR' | 'REVIEWER';

export interface OrganisationSummary {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface UserMembershipContext {
  membership_id: string;
  organisation: OrganisationSummary;
  role: RoleName;
  permissions: string[];
  status: string;
  joined_at: string;
}

export interface CurrentUser {
  id: string;
  full_name: string;
  email: string;
  is_active: boolean;
  is_verified: boolean;
  created_at: string;
  memberships: UserMembershipContext[];
  active_organisation_id: string | null;
  active_role: RoleName | null;
  active_permissions: string[];
}

export interface AuthTokenResponse {
  access_token: string;
  token_type: string;
  expires_at: string;
  user: CurrentUser;
}

export interface OrganisationDetail extends OrganisationSummary {
  current_user_role: RoleName;
  current_user_permissions: string[];
  member_count: number;
}

export interface OrganisationMember {
  id: string;
  organisation_id: string;
  user: {
    id: string;
    full_name: string;
    email: string;
    is_active: boolean;
  };
  role: RoleName;
  permissions: string[];
  status: string;
  joined_at: string;
  created_at: string;
}

export interface OrganisationInvitation {
  id: string;
  organisation_id: string;
  email: string;
  role: RoleName;
  status: 'PENDING' | 'ACCEPTED' | 'REVOKED' | 'EXPIRED';
  expires_at: string;
  created_at: string;
  accepted_at?: string | null;
  revoked_at?: string | null;
  invited_by?: {
    id: string;
    full_name: string;
    email: string;
    is_active: boolean;
  } | null;
}

export interface InvitationCreatePayload {
  email: string;
  role: RoleName;
}

export interface InvitationCreateResponse {
  id: string;
  organisation_id: string;
  email: string;
  role: RoleName;
  status: string;
  expires_at: string;
  created_at: string;
  invitation_token: string;
  invitation_url: string;
  delivery_status: string;
  message: string;
}

export interface InvitationPublicDetail {
  id: string;
  organisation_name: string;
  email: string;
  role: RoleName;
  expires_at: string;
  status: string;
}

export interface InvitationRegisterAndAcceptPayload {
  full_name: string;
  password: string;
  confirm_password: string;
}

export interface InvitationAcceptanceResponse {
  message: string;
  organisation_id: string;
  organisation_name: string;
  role: string;
  joined_at: string;
}

export interface BrandKitSummary {
  id: string;
  organisation_id: string;
  name: string;
  slug: string;
  description: string | null;
  industry: string | null;
  active_version_id: string | null;
  is_archived: boolean;
  created_by_user_id: string | null;
  created_at: string;
  updated_at: string;
  active_version?: {
    id: string;
    version_number: number;
    status: string;
  } | null;
  draft_version?: {
    id: string;
    version_number: number;
    status: string;
  } | null;
}

export interface ComplianceMetrics {
  organisation_id: string;
  total_submissions: number;
  pending_submissions: number;
  approved_submissions: number;
  rejected_submissions: number;
  changes_requested_submissions: number;
  draft_submissions: number;
  total: number;
  pending_review: number;
  approved: number;
  rejected: number;
  changes_requested: number;
  draft: number;
}

export interface ContentSubmissionSummary {
  id: string;
  brand_kit_id: string;
  brand_kit_version_id: string;
  parent_submission_id: string | null;
  revision_number: number;
  title: string;
  score: number | null;
  result: string | null;
  status: string;
  submitted_by_user_id: string | null;
  submitted_by_name: string | null;
  assigned_reviewer_id: string | null;
  assigned_reviewer_name: string | null;
  reviewed_by_name: string | null;
  reviewed_at: string | null;
  created_at: string;
}

export interface LiveDashboardStats {
  totalSubmissions: number | null;
  pendingReviews: number | null;
  approvedContent: number | null;
  activeBrandKits: number | null;
  hasPartialData: boolean;
  isSubmissionsCapped: boolean;
  submissionsError?: string | null;
  brandKitsError?: string | null;
}

// --- Phase 6 Compliance Review & Evidence Types ---

export interface CitationInfo {
  chunk_id: string;
  document_id: string;
  document_title: string;
  page_number?: number | null;
  section_heading?: string | null;
  similarity_score?: number;
  content?: string;
  is_mock?: boolean;
}

export interface ComplianceFinding {
  id?: string;
  finding_id?: string;
  rule_code: string;
  rule_title?: string;
  title?: string;
  severity: string;
  kind?: string;
  rule_type?: string;
  matched_text: string | null;
  start: number | null;
  end: number | null;
  evidence_excerpt: string | null;
  explanation: string;
  description?: string;
  recommended_correction?: string;
  suggested_replacement?: string | null;
  correction?: { replacement: string | null; append_text: string | null };
  citation?: CitationInfo | null;
  source?: string;
  status?: string;
}

export interface SemanticAssessment {
  claims_extracted: number;
  claims_verified: number;
  claims_unverified: number;
  claims_contradicted: number;
  tone_findings_count: number;
  candidate_chunks_retrieved: number;
}

export interface ComplianceScoring {
  formula: string;
  pass_threshold?: number;
  pass_rule?: string;
  total_penalty?: number;
  penalties_total?: number;
  breakdown?: Array<{
    severity: string;
    count: number;
    penalty_each: number;
    penalty_total: number;
  }>;
  deterministic_score?: number;
  deterministic_result?: string;
  engine_mode?: 'DETERMINISTIC' | 'DETERMINISTIC_FALLBACK' | 'HYBRID';
  ai_available?: boolean;
  ai_status_message?: string;
  rules_evaluated?: number;
  semantic_assessment?: SemanticAssessment | null;
  remediations_count?: number;
  node_trace?: string[];
  experimental_score?: number;
}

export interface ComplianceAnalysis {
  id: string;
  submission_id?: string;
  engine_version?: string;
  score: number;
  result: 'PASS' | 'FAIL';
  rules_evaluated: number;
  findings: ComplianceFinding[];
  scoring: ComplianceScoring;
  created_at?: string;
}

export interface ContentAnalyzePayload {
  brand_kit_id: string;
  title: string;
  content_text: string;
  mode?: 'deterministic' | 'hybrid';
  include_experimental_score?: boolean;
}
