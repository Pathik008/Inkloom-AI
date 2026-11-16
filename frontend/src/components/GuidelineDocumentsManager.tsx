import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Eye,
  FileCode,
  FileText,
  Image as ImageIcon,
  Layers,
  RefreshCw,
  Sparkles,
  Trash2,
  UploadCloud,
  X,
  XCircle,
} from 'lucide-react';
import {
  deleteGuidelineDocument,
  listGuidelineDocumentChunks,
  listGuidelineDocuments,
  reparseGuidelineDocument,
  triggerGuidelineDocumentEmbedding,
  uploadGuidelineDocument,
} from '../services/api';
import {
  BrandDocumentChunk,
  BrandGuidelineDocument,
  GuidelineDocumentCategory,
} from '../types';

interface GuidelineDocumentsManagerProps {
  organisationId: string;
  brandKitId: string;
  versionId: string;
  isDraft: boolean;
  canManage: boolean;
  onDocumentCountChange?: (count: number) => void;
}

const CATEGORY_OPTIONS: { value: GuidelineDocumentCategory; label: string }[] = [
  { value: 'STYLE_GUIDE', label: 'Style & Design Guide' },
  { value: 'BRAND_BOOK', label: 'Master Brand Book' },
  { value: 'LEGAL_POLICY', label: 'Legal & Regulatory Policy' },
  { value: 'TONE_PLAYBOOK', label: 'Tone & Voice Playbook' },
  { value: 'PRODUCT_CATALOG', label: 'Product Catalog & Specs' },
];

const ALLOWED_EXTENSIONS = ['.pdf', '.docx', '.txt', '.png', '.jpg', '.jpeg'];
const MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024; // 10MB

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

function formatDate(iso: string | null): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

function getFileIcon(filename: string) {
  const ext = filename.toLowerCase().split('.').pop() || '';
  if (['png', 'jpg', 'jpeg'].includes(ext)) {
    return <ImageIcon className="h-4 w-4 text-[#38BDF8]" />;
  }
  if (ext === 'pdf') {
    return <FileText className="h-4 w-4 text-[#EF4444]" />;
  }
  if (ext === 'docx') {
    return <FileText className="h-4 w-4 text-[#60A5FA]" />;
  }
  return <FileCode className="h-4 w-4 text-[#A1A1AA]" />;
}

export const GuidelineDocumentsManager: React.FC<GuidelineDocumentsManagerProps> = ({
  organisationId,
  brandKitId,
  versionId,
  isDraft,
  canManage,
  onDocumentCountChange,
}) => {
  const [documents, setDocuments] = useState<BrandGuidelineDocument[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [operatingDocId, setOperatingDocId] = useState<string | null>(null);

  // Upload Form State
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [docTitle, setDocTitle] = useState('');
  const [docCategory, setDocCategory] = useState<GuidelineDocumentCategory>('STYLE_GUIDE');

  // Modal / Drawer state for inspecting chunks
  const [inspectDoc, setInspectDoc] = useState<BrandGuidelineDocument | null>(null);
  const [inspectChunks, setInspectChunks] = useState<BrandDocumentChunk[]>([]);
  const [inspectLoading, setInspectLoading] = useState(false);

  // Delete confirm modal state
  const [deleteConfirmDoc, setDeleteConfirmDoc] = useState<BrandGuidelineDocument | null>(null);

  // Status feedback
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const loadDocuments = useCallback(async () => {
    if (!organisationId || !brandKitId || !versionId) return;
    setIsLoading(true);
    setError(null);
    try {
      const docs = await listGuidelineDocuments(organisationId, brandKitId, versionId);
      setDocuments(docs);
      onDocumentCountChange?.(docs.length);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load brand guideline documents.');
    } finally {
      setIsLoading(false);
    }
  }, [organisationId, brandKitId, versionId, onDocumentCountChange]);

  useEffect(() => {
    void loadDocuments();
  }, [loadDocuments]);

  // Client-side file validation
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) {
      setSelectedFile(null);
      return;
    }

    const ext = `.${file.name.toLowerCase().split('.').pop()}`;
    if (!ALLOWED_EXTENSIONS.includes(ext)) {
      setError(`Unsupported file format "${ext}". Allowed: PDF, DOCX, TXT, PNG, JPG, JPEG.`);
      setSelectedFile(null);
      e.target.value = '';
      return;
    }

    if (file.size > MAX_FILE_SIZE_BYTES) {
      setError(`File size (${formatBytes(file.size)}) exceeds maximum allowed 10MB limit.`);
      setSelectedFile(null);
      e.target.value = '';
      return;
    }

    if (file.size === 0) {
      setError('File is empty. Please select a valid document.');
      setSelectedFile(null);
      e.target.value = '';
      return;
    }

    setError(null);
    setSelectedFile(file);
    if (!docTitle.trim()) {
      const nameWithoutExt = file.name.substring(0, file.name.lastIndexOf('.')) || file.name;
      const formatted = nameWithoutExt
        .replace(/[-_]/g, ' ')
        .replace(/\b\w/g, (c) => c.toUpperCase());
      setDocTitle(formatted);
    }
  };

  // Upload Action Handler
  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedFile) {
      setError('Please choose a file to upload.');
      return;
    }
    if (!isDraft || !canManage) {
      setError('Documents can only be uploaded to DRAFT versions by authorized managers.');
      return;
    }

    setIsUploading(true);
    setError(null);
    setNotice(null);

    try {
      const created = await uploadGuidelineDocument(
        organisationId,
        brandKitId,
        versionId,
        selectedFile,
        docTitle.trim() || undefined,
        docCategory,
      );

      setNotice(
        `Document "${created.title}" uploaded & parsed (${created.chunks_count} chunks generated).`,
      );
      setSelectedFile(null);
      setDocTitle('');
      setDocCategory('STYLE_GUIDE');

      const fileInput = document.getElementById('guideline-file-input') as HTMLInputElement | null;
      if (fileInput) fileInput.value = '';

      await loadDocuments();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed. Please check network/file format.');
    } finally {
      setIsUploading(false);
    }
  };

  // Delete Action Handler
  const handleDeleteConfirm = async () => {
    if (!deleteConfirmDoc) return;
    setOperatingDocId(deleteConfirmDoc.id);
    setError(null);
    setNotice(null);

    try {
      await deleteGuidelineDocument(organisationId, brandKitId, versionId, deleteConfirmDoc.id);
      setNotice(`"${deleteConfirmDoc.title}" deleted.`);
      setDeleteConfirmDoc(null);
      await loadDocuments();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete guideline document.');
    } finally {
      setOperatingDocId(null);
    }
  };

  // Reparse Action Handler
  const handleReparse = async (doc: BrandGuidelineDocument) => {
    if (!isDraft || !canManage) return;
    setOperatingDocId(doc.id);
    setError(null);
    setNotice(null);

    try {
      const updated = await reparseGuidelineDocument(organisationId, brandKitId, versionId, doc.id);
      setNotice(`"${updated.title}" reparsed successfully (${updated.chunks_count} chunks).`);
      await loadDocuments();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reparse guideline document.');
    } finally {
      setOperatingDocId(null);
    }
  };

  // Embedding Trigger Handler
  const handleTriggerEmbed = async (doc: BrandGuidelineDocument) => {
    if (!isDraft || !canManage) return;
    setOperatingDocId(doc.id);
    setError(null);
    setNotice(null);

    try {
      const updated = await triggerGuidelineDocumentEmbedding(organisationId, brandKitId, versionId, doc.id);
      setNotice(`Vector embeddings generated for "${updated.title}".`);
      await loadDocuments();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Embedding generation failed.');
    } finally {
      setOperatingDocId(null);
    }
  };

  // Inspect Chunks Handler
  const handleInspectChunks = async (doc: BrandGuidelineDocument) => {
    setInspectDoc(doc);
    setInspectLoading(true);
    setInspectChunks([]);
    try {
      const chunks = await listGuidelineDocumentChunks(organisationId, brandKitId, versionId, doc.id);
      setInspectChunks(chunks);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load document chunks.');
    } finally {
      setInspectLoading(false);
    }
  };

  const totalChunks = useMemo(
    () => documents.reduce((acc, d) => acc + (d.chunks_count || 0), 0),
    [documents]
  );

  return (
    <div className="space-y-6">
      {/* Alert Notices */}
      {error && (
        <div className="rounded-lg border border-[#EF4444]/40 bg-[#EF4444]/10 p-3.5 text-xs text-[#EF4444] flex items-start justify-between gap-3">
          <div className="flex items-start gap-2.5">
            <XCircle className="h-4 w-4 text-[#EF4444] shrink-0 mt-0.5" />
            <div>
              <p className="font-semibold text-[#EF4444]">Action Failed</p>
              <p className="mt-0.5">{error}</p>
            </div>
          </div>
          <button
            onClick={() => setError(null)}
            className="text-[#EF4444] hover:text-[#ECECEC] p-1"
            title="Dismiss"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {notice && (
        <div className="rounded-lg border border-[#10A37F]/40 bg-[#10A37F]/10 p-3.5 text-xs text-[#10A37F] flex items-start justify-between gap-3">
          <div className="flex items-start gap-2.5">
            <CheckCircle2 className="h-4 w-4 text-[#10A37F] shrink-0 mt-0.5" />
            <div>
              <p className="font-semibold text-[#10A37F]">Success</p>
              <p className="mt-0.5">{notice}</p>
            </div>
          </div>
          <button
            onClick={() => setNotice(null)}
            className="text-[#10A37F] hover:text-[#ECECEC] p-1"
            title="Dismiss"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* Upload Section (Only visible on DRAFT when user has canManage) */}
      {canManage && isDraft ? (
        <form
          onSubmit={handleUpload}
          className="rounded-xl border border-[#424242] bg-[#2F2F2F] p-5 shadow-sm space-y-4"
        >
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#424242] pb-3">
            <div>
              <h2 className="text-xs font-semibold text-[#ECECEC] uppercase tracking-wider flex items-center gap-2">
                <UploadCloud className="h-4 w-4 text-[#10A37F]" />
                <span>Upload Brand Guideline Document</span>
              </h2>
              <p className="text-xs text-[#A1A1AA] mt-0.5">
                Upload policy guidelines, brand books, catalogs, or imagery. Documents are parsed, chunked, and prepared for RAG compliance verification.
              </p>
            </div>
            <span className="text-[11px] font-mono text-[#A1A1AA] bg-[#212121] px-2.5 py-1 rounded border border-[#424242]">
              Max 10MB · PDF, DOCX, TXT, PNG, JPG
            </span>
          </div>

          <div className="grid md:grid-cols-3 gap-4">
            {/* File Picker */}
            <div className="space-y-1 md:col-span-1">
              <label className="text-xs font-medium text-[#A1A1AA]">
                Select Guideline File <span className="text-[#EF4444]">*</span>
              </label>
              <input
                id="guideline-file-input"
                type="file"
                disabled={isUploading}
                accept=".pdf,.docx,.txt,.png,.jpg,.jpeg,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,image/png,image/jpeg"
                onChange={handleFileChange}
                className="w-full text-xs text-[#ECECEC] file:mr-2.5 file:py-1.5 file:px-3 file:rounded-md file:border-0 file:text-xs file:font-semibold file:bg-[#10A37F] file:text-white hover:file:bg-[#0D8F70] file:cursor-pointer cursor-pointer bg-[#212121] border border-[#424242] rounded-lg p-1 focus:outline-none"
              />
              {selectedFile && (
                <p className="text-[11px] text-[#A1A1AA] flex items-center gap-1.5 mt-1 font-mono">
                  {getFileIcon(selectedFile.name)}
                  <span>{selectedFile.name} ({formatBytes(selectedFile.size)})</span>
                </p>
              )}
            </div>

            {/* Display Title */}
            <div className="space-y-1 md:col-span-1">
              <label className="text-xs font-medium text-[#A1A1AA]">Display Title</label>
              <input
                type="text"
                disabled={isUploading}
                placeholder="e.g. Master Typography & Logo Standards"
                value={docTitle}
                onChange={(e) => setDocTitle(e.target.value)}
                className="w-full rounded-lg bg-[#212121] border border-[#424242] px-3 py-2 text-xs text-[#ECECEC] placeholder-[#71717A] focus:border-[#10A37F] focus:outline-none disabled:opacity-50"
              />
            </div>

            {/* Document Category */}
            <div className="space-y-1 md:col-span-1">
              <label className="text-xs font-medium text-[#A1A1AA]">Document Category</label>
              <select
                disabled={isUploading}
                value={docCategory}
                onChange={(e) => setDocCategory(e.target.value as GuidelineDocumentCategory)}
                className="w-full rounded-lg bg-[#212121] border border-[#424242] px-3 py-2 text-xs text-[#ECECEC] focus:border-[#10A37F] focus:outline-none disabled:opacity-50"
              >
                {CATEGORY_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="flex items-center justify-end gap-3 pt-1">
            <button
              type="submit"
              disabled={!selectedFile || isUploading}
              className="inline-flex items-center gap-2 rounded-lg bg-[#10A37F] px-4 py-2 text-xs font-semibold text-white hover:bg-[#0D8F70] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isUploading ? (
                <>
                  <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                  <span>Parsing & Chunking Document...</span>
                </>
              ) : (
                <>
                  <UploadCloud className="h-3.5 w-3.5" />
                  <span>Upload & Ingest Guideline</span>
                </>
              )}
            </button>
          </div>
        </form>
      ) : (
        !isDraft && (
          <div className="rounded-lg border border-[#424242] bg-[#2F2F2F] p-4 text-xs text-[#A1A1AA] flex items-center gap-3">
            <Clock className="h-4 w-4 text-[#F59E0B] shrink-0" />
            <span>
              This Brand Kit version is <strong className="text-[#ECECEC]">PUBLISHED</strong> and immutable. To upload or edit brand guideline documents, create a new sequential DRAFT version.
            </span>
          </div>
        )
      )}

      {/* Document Library List */}
      <div className="rounded-xl border border-[#424242] bg-[#2F2F2F] shadow-sm overflow-hidden">
        {/* Header Bar */}
        <div className="p-3.5 bg-[#212121] border-b border-[#424242] flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <h3 className="font-semibold text-xs text-[#ECECEC] uppercase tracking-wider flex items-center gap-2">
              <Layers className="h-3.5 w-3.5 text-[#10A37F]" />
              <span>Ingested Guidelines ({documents.length})</span>
            </h3>
            {documents.length > 0 && (
              <span className="text-xs font-mono font-medium text-[#ECECEC] bg-[#2F2F2F] border border-[#424242] px-2 py-0.5 rounded">
                {totalChunks} Total RAG Chunks
              </span>
            )}
          </div>

          <button
            onClick={() => void loadDocuments()}
            disabled={isLoading}
            className="inline-flex items-center gap-1.5 text-xs text-[#A1A1AA] hover:text-[#ECECEC] px-2.5 py-1 rounded-md border border-[#424242] bg-[#212121] hover:bg-[#424242] transition-colors disabled:opacity-50"
            title="Refresh documents list"
          >
            <RefreshCw className={`h-3 w-3 ${isLoading ? 'animate-spin' : ''}`} />
            <span>Refresh</span>
          </button>
        </div>

        {/* Empty State */}
        {documents.length === 0 && !isLoading && (
          <div className="p-10 text-center space-y-2">
            <div className="mx-auto w-10 h-10 rounded-lg bg-[#212121] border border-[#424242] flex items-center justify-center text-[#A1A1AA]">
              <FileText className="h-5 w-5" />
            </div>
            <h4 className="text-sm font-semibold text-[#ECECEC]">No Guideline Documents Ingested</h4>
            <p className="text-xs text-[#71717A] max-w-md mx-auto">
              Upload brand style manuals, policies, or visual collateral to populate this version's semantic knowledge base. Uploaded documents are converted to 512-token chunks and cross-referenced during marketing review.
            </p>
          </div>
        )}

        {/* Loading State */}
        {isLoading && documents.length === 0 && (
          <div className="p-10 text-center space-y-2">
            <RefreshCw className="h-5 w-5 animate-spin text-[#10A37F] mx-auto" />
            <p className="text-xs text-[#71717A]">Loading guideline documents and vector chunks...</p>
          </div>
        )}

        {/* Documents Cards / Rows */}
        {documents.length > 0 && (
          <div className="divide-y divide-[#424242]">
            {documents.map((doc) => {
              const isOperating = operatingDocId === doc.id;
              const hasChunks = doc.chunks_count > 0;
              const isEmbedded = Boolean(doc.embedded_at);

              return (
                <div
                  key={doc.id}
                  className="p-4 flex flex-wrap items-center justify-between gap-4 hover:bg-[#424242]/20 transition-colors"
                >
                  {/* Left: Document Info */}
                  <div className="space-y-1 min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-[#ECECEC]">
                        {getFileIcon(doc.original_filename)}
                        <span className="truncate max-w-xs">{doc.title}</span>
                      </span>

                      {/* Category Badge */}
                      <span className="rounded bg-[#212121] border border-[#424242] px-2 py-0.5 text-[11px] text-[#A1A1AA]">
                        {doc.document_category.replace(/_/g, ' ')}
                      </span>

                      {/* Parsing Status Badge */}
                      <span
                        className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-semibold ${
                          doc.parsing_status === 'PARSED'
                            ? 'bg-[#10A37F]/15 border border-[#10A37F]/30 text-[#10A37F]'
                            : doc.parsing_status === 'FAILED'
                            ? 'bg-[#EF4444]/15 border border-[#EF4444]/30 text-[#EF4444]'
                            : 'bg-[#F59E0B]/15 border border-[#F59E0B]/30 text-[#F59E0B]'
                        }`}
                      >
                        {doc.parsing_status === 'PARSED' && <CheckCircle2 className="h-3 w-3" />}
                        {doc.parsing_status === 'FAILED' && <XCircle className="h-3 w-3" />}
                        {['PENDING', 'PROCESSING'].includes(doc.parsing_status) && (
                          <RefreshCw className="h-3 w-3 animate-spin" />
                        )}
                        <span>{doc.parsing_status}</span>
                      </span>

                      {/* Chunk Count Badge */}
                      <span className="font-mono text-[11px] font-semibold text-[#ECECEC] bg-[#212121] border border-[#424242] rounded px-2 py-0.5">
                        {doc.chunks_count} chunk{doc.chunks_count !== 1 ? 's' : ''}
                      </span>

                      {/* Page Count */}
                      {doc.page_count !== null && (
                        <span className="text-[11px] text-[#71717A]">
                          ({doc.page_count} page{doc.page_count !== 1 ? 's' : ''})
                        </span>
                      )}

                      {/* Vector Embedding Status */}
                      {isEmbedded ? (
                        <span
                          className="inline-flex items-center gap-1 rounded bg-[#10A37F]/15 border border-[#10A37F]/30 px-2 py-0.5 text-[11px] font-semibold text-[#10A37F]"
                          title={`Embedded at ${formatDate(doc.embedded_at)}`}
                        >
                          <Sparkles className="h-3 w-3 text-[#10A37F]" />
                          <span>pgvector Embedded</span>
                        </span>
                      ) : (
                        <span className="text-[11px] text-[#71717A] italic">Embeddings pending</span>
                      )}
                    </div>

                    {/* Metadata line */}
                    <div className="flex flex-wrap items-center gap-3 text-xs text-[#71717A]">
                      <span>File: <code className="text-[#A1A1AA] font-mono text-[11px]">{doc.original_filename}</code></span>
                      <span>·</span>
                      <span>Size: {formatBytes(doc.file_size_bytes)}</span>
                      <span>·</span>
                      <span>Uploaded: {formatDate(doc.created_at)}</span>
                      {doc.parsed_at && (
                        <>
                          <span>·</span>
                          <span>Parsed: {formatDate(doc.parsed_at)}</span>
                        </>
                      )}
                    </div>

                    {/* Error disclosure if parsing failed */}
                    {doc.parsing_status === 'FAILED' && doc.last_error_message && (
                      <div className="rounded-lg border border-[#EF4444]/30 bg-[#EF4444]/10 p-2 text-xs text-[#EF4444] mt-1">
                        <strong>Error:</strong> {doc.last_error_message}
                      </div>
                    )}
                  </div>

                  {/* Right: Actions */}
                  <div className="flex items-center gap-2 shrink-0">
                    {/* View Chunks Button */}
                    {hasChunks && (
                      <button
                        onClick={() => void handleInspectChunks(doc)}
                        className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs font-medium bg-[#212121] border border-[#424242] text-[#ECECEC] hover:bg-[#424242] transition-colors"
                        title="Inspect generated RAG chunks"
                      >
                        <Eye className="h-3.5 w-3.5 text-[#10A37F]" />
                        <span>Inspect Chunks</span>
                      </button>
                    )}

                    {/* Trigger Embedding Button (Draft Only) */}
                    {canManage && isDraft && hasChunks && (
                      <button
                        onClick={() => void handleTriggerEmbed(doc)}
                        disabled={isOperating}
                        className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs font-semibold bg-[#10A37F]/15 border border-[#10A37F]/30 text-[#10A37F] hover:bg-[#10A37F]/25 transition-colors disabled:opacity-50"
                        title="Generate vector embeddings for semantic retrieval"
                      >
                        {isOperating ? (
                          <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Sparkles className="h-3.5 w-3.5" />
                        )}
                        <span>{isEmbedded ? 'Re-embed' : 'Generate Embeddings'}</span>
                      </button>
                    )}

                    {/* Reparse Button (Draft Only) */}
                    {canManage && isDraft && (
                      <button
                        onClick={() => void handleReparse(doc)}
                        disabled={isOperating}
                        className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs font-medium bg-[#212121] border border-[#424242] text-[#A1A1AA] hover:bg-[#424242] hover:text-[#ECECEC] transition-colors disabled:opacity-50"
                        title="Reparse from stored binary on disk"
                      >
                        <RefreshCw className={`h-3 w-3 ${isOperating ? 'animate-spin' : ''}`} />
                        <span>Reparse</span>
                      </button>
                    )}

                    {/* Delete Button (Draft Only) */}
                    {canManage && isDraft && (
                      <button
                        onClick={() => setDeleteConfirmDoc(doc)}
                        disabled={isOperating}
                        className="inline-flex items-center justify-center rounded-lg p-1.5 text-[#EF4444] bg-[#EF4444]/15 border border-[#EF4444]/30 hover:bg-[#EF4444]/25 transition-colors disabled:opacity-50"
                        title="Delete document"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Delete Confirmation Modal */}
      {deleteConfirmDoc && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4">
          <div className="w-full max-w-md rounded-xl border border-[#424242] bg-[#2F2F2F] p-6 shadow-xl space-y-4">
            <div className="flex items-center gap-3 text-[#EF4444]">
              <AlertTriangle className="h-5 w-5 shrink-0" />
              <h3 className="text-sm font-semibold text-[#ECECEC]">Delete Guideline Document</h3>
            </div>
            <p className="text-xs text-[#A1A1AA]">
              Are you sure you want to delete <strong className="text-[#ECECEC]">"{deleteConfirmDoc.title}"</strong> ({deleteConfirmDoc.original_filename})?
            </p>
            <p className="text-xs text-[#71717A] bg-[#212121] p-3 rounded-lg border border-[#424242]">
              This action will permanently delete the stored document binary and all associated <strong>{deleteConfirmDoc.chunks_count} vector chunks</strong> from this draft version.
            </p>
            <div className="flex items-center justify-end gap-2.5 pt-2">
              <button
                type="button"
                onClick={() => setDeleteConfirmDoc(null)}
                className="rounded-lg px-3 py-1.5 text-xs font-medium text-[#A1A1AA] hover:bg-[#424242] hover:text-[#ECECEC] transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleDeleteConfirm}
                className="inline-flex items-center gap-1.5 rounded-lg bg-[#EF4444] px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-[#DC2626] transition-colors"
              >
                <Trash2 className="h-3.5 w-3.5" />
                <span>Confirm Delete</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Inspect Chunks Modal */}
      {inspectDoc && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4">
          <div className="w-full max-w-3xl max-h-[85vh] rounded-xl border border-[#424242] bg-[#2F2F2F] shadow-xl flex flex-col overflow-hidden">
            {/* Modal Header */}
            <div className="p-4 bg-[#212121] border-b border-[#424242] flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-[#ECECEC] flex items-center gap-2">
                  <Layers className="h-4 w-4 text-[#10A37F]" />
                  <span>RAG Vector Chunks: {inspectDoc.title}</span>
                </h3>
                <p className="text-xs text-[#71717A] mt-0.5 font-mono">
                  {inspectDoc.original_filename} · {inspectChunks.length} sentence-aware segments
                </p>
              </div>
              <button
                onClick={() => setInspectDoc(null)}
                className="text-[#A1A1AA] hover:text-[#ECECEC] p-1 rounded hover:bg-[#424242]"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {/* Modal Body */}
            <div className="p-5 overflow-y-auto space-y-3 flex-1 bg-[#2F2F2F]">
              {inspectLoading && (
                <div className="py-10 text-center space-y-2">
                  <RefreshCw className="h-5 w-5 animate-spin text-[#10A37F] mx-auto" />
                  <p className="text-xs text-[#71717A]">Loading chunk excerpts...</p>
                </div>
              )}

              {!inspectLoading && inspectChunks.length === 0 && (
                <p className="text-center text-xs text-[#71717A] py-8">
                  No chunks generated for this document.
                </p>
              )}

              {!inspectLoading &&
                inspectChunks.map((chunk) => (
                  <div
                    key={chunk.id}
                    className="rounded-lg border border-[#424242] bg-[#212121] p-3.5 space-y-2"
                  >
                    <div className="flex flex-wrap items-center justify-between text-[11px] text-[#71717A] border-b border-[#424242] pb-1.5 font-mono">
                      <span className="font-semibold text-[#10A37F]">
                        Chunk #{chunk.chunk_index + 1}
                      </span>
                      <div className="flex items-center gap-3">
                        <span>Page {chunk.page_number ?? 1}</span>
                        <span>·</span>
                        <span>Chars {chunk.char_start}..{chunk.char_end}</span>
                        <span>·</span>
                        <span className="text-[#ECECEC]">~{chunk.token_count} tokens</span>
                      </div>
                    </div>

                    {chunk.section_heading && (
                      <p className="text-[11px] font-semibold text-[#ECECEC]">
                        Section: {chunk.section_heading}
                      </p>
                    )}

                    <p className="text-xs text-[#ECECEC] leading-relaxed font-sans whitespace-pre-wrap">
                      {chunk.content}
                    </p>
                  </div>
                ))}
            </div>

            {/* Modal Footer */}
            <div className="p-3 bg-[#212121] border-t border-[#424242] flex justify-end">
              <button
                type="button"
                onClick={() => setInspectDoc(null)}
                className="rounded-lg bg-[#424242] px-3.5 py-1.5 text-xs font-medium text-[#ECECEC] hover:bg-[#525252] transition-colors"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default GuidelineDocumentsManager;
