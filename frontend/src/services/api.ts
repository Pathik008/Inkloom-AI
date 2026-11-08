import {
  AuthTokenResponse,
  CurrentUser,
  HealthStatus,
  InvitationAcceptanceResponse,
  InvitationCreatePayload,
  InvitationCreateResponse,
  InvitationPublicDetail,
  InvitationRegisterAndAcceptPayload,
  OrganisationDetail,
  OrganisationInvitation,
  OrganisationMember,
  RoleName,
} from '../types';

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '');

const TOKEN_STORAGE_KEY = 'inkloom_access_token';
const ACTIVE_ORG_STORAGE_KEY = 'inkloom_active_org_id';

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function getStoredToken(): string | null {
  return sessionStorage.getItem(TOKEN_STORAGE_KEY);
}

export function setStoredToken(token: string | null): void {
  if (token) {
    sessionStorage.setItem(TOKEN_STORAGE_KEY, token);
  } else {
    sessionStorage.removeItem(TOKEN_STORAGE_KEY);
  }
}

export function getStoredOrganisationId(): string | null {
  return sessionStorage.getItem(ACTIVE_ORG_STORAGE_KEY);
}

export function setStoredOrganisationId(orgId: string | null): void {
  if (orgId) {
    sessionStorage.setItem(ACTIVE_ORG_STORAGE_KEY, orgId);
  } else {
    sessionStorage.removeItem(ACTIVE_ORG_STORAGE_KEY);
  }
}

async function apiRequest<T>(
  path: string,
  options: RequestInit = {},
  activeOrgId?: string | null,
): Promise<T> {
  const token = getStoredToken();
  const orgHeader = activeOrgId !== undefined ? activeOrgId : getStoredOrganisationId();

  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...(options.headers as Record<string, string> | undefined),
  };

  if (options.body && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  if (orgHeader) {
    headers['X-Organisation-ID'] = orgHeader;
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
  });

  if (response.status === 204) {
    return undefined as unknown as T;
  }

  let data: unknown = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }

  if (!response.ok) {
    let detail = `HTTP ${response.status}: Request failed`;
    if (data && typeof data === 'object' && 'detail' in data) {
      const rawDetail = (data as { detail: unknown }).detail;
      if (typeof rawDetail === 'string') {
        detail = rawDetail;
      } else if (Array.isArray(rawDetail) && rawDetail.length > 0) {
        const first = rawDetail[0] as { msg?: string };
        detail = first.msg || JSON.stringify(rawDetail);
      }
    }
    throw new ApiError(response.status, detail);
  }

  return data as T;
}

export async function fetchBackendHealth(): Promise<HealthStatus> {
  return apiRequest<HealthStatus>('/api/v1/health');
}

export function getApiBaseUrl(): string {
  return API_BASE_URL || window.location.origin;
}

// --- Authentication API ---

export async function registerAccount(payload: {
  full_name: string;
  email: string;
  password: string;
  confirm_password: string;
  organisation_name: string;
  organisation_description?: string;
}): Promise<AuthTokenResponse> {
  return apiRequest<AuthTokenResponse>('/api/v1/auth/register', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function loginAccount(payload: {
  email: string;
  password: string;
}): Promise<AuthTokenResponse> {
  return apiRequest<AuthTokenResponse>('/api/v1/auth/login', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function logoutAccount(): Promise<{ message: string; revoked_jti: string }> {
  return apiRequest<{ message: string; revoked_jti: string }>('/api/v1/auth/logout', {
    method: 'POST',
  });
}

export async function fetchCurrentUser(activeOrgId?: string | null): Promise<CurrentUser> {
  return apiRequest<CurrentUser>('/api/v1/auth/me', { method: 'GET' }, activeOrgId);
}

// --- Organisations & RBAC Membership API ---

export async function listOrganisations(): Promise<OrganisationDetail[]> {
  return apiRequest<OrganisationDetail[]>('/api/v1/organisations');
}

export async function createOrganisation(payload: {
  name: string;
  description?: string;
}): Promise<OrganisationDetail> {
  return apiRequest<OrganisationDetail>('/api/v1/organisations', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function getOrganisationDetails(organisationId: string): Promise<OrganisationDetail> {
  return apiRequest<OrganisationDetail>(`/api/v1/organisations/${organisationId}`);
}

export async function updateOrganisationDetails(
  organisationId: string,
  payload: { name?: string; description?: string | null },
): Promise<OrganisationDetail> {
  return apiRequest<OrganisationDetail>(`/api/v1/organisations/${organisationId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export async function listOrganisationMembers(
  organisationId: string,
): Promise<OrganisationMember[]> {
  return apiRequest<OrganisationMember[]>(`/api/v1/organisations/${organisationId}/members`);
}

export async function addOrganisationMember(
  organisationId: string,
  payload: {
    email: string;
    role: RoleName;
    full_name?: string;
    initial_password?: string;
  },
): Promise<OrganisationMember> {
  return apiRequest<OrganisationMember>(`/api/v1/organisations/${organisationId}/members`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function updateOrganisationMemberRole(
  organisationId: string,
  membershipId: string,
  role: RoleName,
): Promise<OrganisationMember> {
  return apiRequest<OrganisationMember>(
    `/api/v1/organisations/${organisationId}/members/${membershipId}`,
    {
      method: 'PATCH',
      body: JSON.stringify({ role }),
    },
  );
}

export async function removeOrganisationMember(
  organisationId: string,
  membershipId: string,
): Promise<void> {
  return apiRequest<void>(`/api/v1/organisations/${organisationId}/members/${membershipId}`, {
    method: 'DELETE',
  });
}

// --- Organisation Invitations API ---

export async function createOrganisationInvitation(
  organisationId: string,
  payload: InvitationCreatePayload,
): Promise<InvitationCreateResponse> {
  return apiRequest<InvitationCreateResponse>(`/api/v1/organisations/${organisationId}/invitations`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function listOrganisationInvitations(
  organisationId: string,
): Promise<OrganisationInvitation[]> {
  return apiRequest<OrganisationInvitation[]>(`/api/v1/organisations/${organisationId}/invitations`);
}

export async function revokeOrganisationInvitation(
  organisationId: string,
  invitationId: string,
): Promise<void> {
  return apiRequest<void>(
    `/api/v1/organisations/${organisationId}/invitations/${invitationId}`,
    {
      method: 'DELETE',
    },
  );
}

export async function getInvitationDetails(token: string): Promise<InvitationPublicDetail> {
  return apiRequest<InvitationPublicDetail>(`/api/v1/invitations/${encodeURIComponent(token)}`);
}

export async function acceptInvitation(token: string): Promise<InvitationAcceptanceResponse> {
  return apiRequest<InvitationAcceptanceResponse>(
    `/api/v1/invitations/${encodeURIComponent(token)}/accept`,
    {
      method: 'POST',
    },
  );
}

export async function registerAndAcceptInvitation(
  token: string,
  payload: InvitationRegisterAndAcceptPayload,
): Promise<AuthTokenResponse> {
  return apiRequest<AuthTokenResponse>(
    `/api/v1/invitations/${encodeURIComponent(token)}/register-and-accept`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
  );
}
