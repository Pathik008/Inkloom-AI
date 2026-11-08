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
