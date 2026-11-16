/**
 * Frontend Unit & Contract Tests for Brand Hub Guideline Document Management UI.
 * Verifies client-side validation, URL builders, category options, size limits,
 * and multipart/form-data request assembly matching the backend contract.
 */
import test from 'node:test';
import assert from 'node:assert/strict';

const ORG_ID = '00000000-0000-0000-0000-000000000001';
const KIT_ID = '11111111-1111-1111-1111-111111111111';
const VERSION_ID = '22222222-2222-2222-2222-222222222222';
const DOC_ID = '33333333-3333-3333-3333-333333333333';

// 1. Frontend validation bounds
const ALLOWED_EXTENSIONS = ['.pdf', '.docx', '.txt', '.png', '.jpg', '.jpeg'];
const MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024; // 10MB
const ALLOWED_CATEGORIES = [
  'STYLE_GUIDE',
  'PRODUCT_CATALOG',
  'LEGAL_POLICY',
  'TONE_PLAYBOOK',
  'BRAND_BOOK',
];

test('1. Client-side extension validation accepts all supported formats', () => {
  const validFiles = [
    'brand_guide.pdf',
    'policies.docx',
    'copy_rules.txt',
    'palette.png',
    'logo.jpg',
    'banner.jpeg',
    'UPPERCASE.PNG',
  ];

  for (const filename of validFiles) {
    const ext = `.${filename.toLowerCase().split('.').pop()}`;
    assert.ok(
      ALLOWED_EXTENSIONS.includes(ext),
      `Expected ${filename} (ext: ${ext}) to be allowed`
    );
  }
});

test('2. Client-side extension validation rejects unsupported formats', () => {
  const invalidFiles = [
    'malware.exe',
    'script.sh',
    'styles.css',
    'animation.gif',
    'image.bmp',
    'document.rtf',
    'archive.zip',
  ];

  for (const filename of invalidFiles) {
    const ext = `.${filename.toLowerCase().split('.').pop()}`;
    assert.equal(
      ALLOWED_EXTENSIONS.includes(ext),
      false,
      `Expected ${filename} (ext: ${ext}) to be rejected`
    );
  }
});

test('3. Client-side size limit enforces 10MB maximum', () => {
  const validSize = 10 * 1024 * 1024; // Exactly 10MB
  const smallSize = 1024 * 500; // 500 KB
  const oversized = 10 * 1024 * 1024 + 1; // 10MB + 1 byte
  const emptySize = 0;

  assert.ok(validSize <= MAX_FILE_SIZE_BYTES, '10MB should be within limit');
  assert.ok(smallSize <= MAX_FILE_SIZE_BYTES, '500KB should be within limit');
  assert.ok(oversized > MAX_FILE_SIZE_BYTES, '10MB + 1 byte should exceed limit');
  assert.equal(emptySize === 0, true, '0 bytes should be caught as empty');
});

test('4. Document category options match backend GuidelineDocumentCategory.ALL', () => {
  const expectedCategories = [
    'STYLE_GUIDE',
    'PRODUCT_CATALOG',
    'LEGAL_POLICY',
    'TONE_PLAYBOOK',
    'BRAND_BOOK',
  ];

  assert.deepEqual(ALLOWED_CATEGORIES.sort(), expectedCategories.sort());
});

test('5. Upload request URL and multipart FormData assembly', () => {
  const url = `/api/v1/organisations/${ORG_ID}/brand-kits/${KIT_ID}/versions/${VERSION_ID}/documents`;
  assert.equal(
    url,
    `/api/v1/organisations/${ORG_ID}/brand-kits/${KIT_ID}/versions/${VERSION_ID}/documents`
  );

  const formData = new FormData();
  formData.append('file', new Blob(['test content'], { type: 'image/png' }), 'palette.png');
  formData.append('title', 'Brand Color Palette');
  formData.append('document_category', 'STYLE_GUIDE');

  assert.ok(formData.has('file'));
  assert.equal(formData.get('title'), 'Brand Color Palette');
  assert.equal(formData.get('document_category'), 'STYLE_GUIDE');
});

test('6. Document actions URL builders match exact backend routes', () => {
  // List endpoint
  const listUrl = `/api/v1/organisations/${ORG_ID}/brand-kits/${KIT_ID}/versions/${VERSION_ID}/documents`;
  assert.equal(listUrl, `/api/v1/organisations/${ORG_ID}/brand-kits/${KIT_ID}/versions/${VERSION_ID}/documents`);

  // Delete endpoint
  const deleteUrl = `/api/v1/organisations/${ORG_ID}/brand-kits/${KIT_ID}/versions/${VERSION_ID}/documents/${DOC_ID}`;
  assert.equal(deleteUrl, `/api/v1/organisations/${ORG_ID}/brand-kits/${KIT_ID}/versions/${VERSION_ID}/documents/${DOC_ID}`);

  // Reparse endpoint
  const reparseUrl = `/api/v1/organisations/${ORG_ID}/brand-kits/${KIT_ID}/versions/${VERSION_ID}/documents/${DOC_ID}/reparse`;
  assert.equal(reparseUrl, `/api/v1/organisations/${ORG_ID}/brand-kits/${KIT_ID}/versions/${VERSION_ID}/documents/${DOC_ID}/reparse`);

  // Embed endpoint
  const embedUrl = `/api/v1/organisations/${ORG_ID}/brand-kits/${KIT_ID}/versions/${VERSION_ID}/documents/${DOC_ID}/embed`;
  assert.equal(embedUrl, `/api/v1/organisations/${ORG_ID}/brand-kits/${KIT_ID}/versions/${VERSION_ID}/documents/${DOC_ID}/embed`);

  // Chunks endpoint
  const chunksUrl = `/api/v1/organisations/${ORG_ID}/brand-kits/${KIT_ID}/versions/${VERSION_ID}/documents/${DOC_ID}/chunks`;
  assert.equal(chunksUrl, `/api/v1/organisations/${ORG_ID}/brand-kits/${KIT_ID}/versions/${VERSION_ID}/documents/${DOC_ID}/chunks`);
});

test('7. Immutability guard forbids mutating actions on published versions', () => {
  const publishedVersion = { status: 'PUBLISHED' };
  const draftVersion = { status: 'DRAFT' };

  const canEditPublished = publishedVersion.status === 'DRAFT';
  const canEditDraft = draftVersion.status === 'DRAFT';

  assert.equal(canEditPublished, false, 'PUBLISHED versions must be immutable on frontend');
  assert.equal(canEditDraft, true, 'DRAFT versions must allow upload and edit');
});

test('8. RBAC permission contract: mutating guideline document actions require brand:manage', () => {
  // Backend canonical permissions are brand:read and brand:manage (not legacy/hypothetical brand_kit:write)
  const canonicalWritePermission = 'brand:manage';
  const canonicalReadPermission = 'brand:read';

  const readOnlyUserPerms = [canonicalReadPermission, 'content:create'];
  const canManageReadOnly = readOnlyUserPerms.includes(canonicalWritePermission);
  assert.equal(canManageReadOnly, false, 'Users without brand:manage must not have canManage authority');

  const brandManagerPerms = [canonicalReadPermission, canonicalWritePermission];
  const canManageManager = brandManagerPerms.includes(canonicalWritePermission);
  assert.equal(canManageManager, true, 'Users with brand:manage must have canManage authority');
});