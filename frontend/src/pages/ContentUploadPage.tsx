import React, { useEffect, useState } from 'react';
import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  FileText,
  FileType,
  Image as ImageIcon,
  Loader2,
  Upload,
  X,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { fetchBrandKits, uploadDocument } from '../services/api';
import { BrandKitSummary } from '../types';

interface ExtractionResponse {
  filename: string;
  format: string;
  method: string;
  page_count: number;
  char_count: number;
  extracted_text: string;
  metadata: Record<string, any>;
  ocr_fallback_triggered: boolean;
  submission: {
    id: string;
    title: string;
    status: string;
    analysis: {
      score: number;
      result: string;
      rules_evaluated: number;
      findings: Array<{
        finding_id: string;
        rule_code: string;
        rule_title: string;
        severity: string;
        explanation: string;
        evidence_excerpt?: string | null;
        recommended_correction?: string | null;
      }>;
    };
  } | null;
}

type ProcessingState = 'IDLE' | 'QUEUED' | 'PROCESSING' | 'COMPLETED' | 'FAILED';

export const ContentUploadPage: React.FC = () => {
  const { activeOrganisationId } = useAuth();

  const [brandKits, setBrandKits] = useState<BrandKitSummary[]>([]);
  const [selectedKitId, setSelectedKitId] = useState<string>('');
  const [customTitle, setCustomTitle] = useState<string>('');
  const [autoSubmit, setAutoSubmit] = useState<boolean>(true);
  const [analysisMode, setAnalysisMode] = useState<'hybrid' | 'deterministic'>('hybrid');

  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [dragActive, setDragActive] = useState<boolean>(false);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  const [processingState, setProcessingState] = useState<ProcessingState>('IDLE');
  const [progressPercent, setProgressPercent] = useState<number>(0);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [result, setResult] = useState<ExtractionResponse | null>(null);

  // Load Brand Kits on mount
  useEffect(() => {
    if (!activeOrganisationId) return;
    void fetchBrandKits(activeOrganisationId).then((kits) => {
      setBrandKits(kits);
      if (kits.length > 0) {
        setSelectedKitId(kits[0].id);
      }
    });
  }, [activeOrganisationId]);

  // Clean preview URLs
  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  const handleFileSelect = (file: File) => {
    setErrorMessage(null);
    setResult(null);
    setProcessingState('IDLE');

    // Validate size (10MB limit)
    if (file.size > 10 * 1024 * 1024) {
      setErrorMessage(`File exceeds 10MB limit (${(file.size / (1024 * 1024)).toFixed(1)}MB).`);
      return;
    }

    // Validate extension
    const ext = '.' + file.name.split('.').pop()?.toLowerCase();
    const validExts = ['.pdf', '.docx', '.txt', '.png', '.jpg', '.jpeg'];
    if (!validExts.includes(ext)) {
      setErrorMessage(`Unsupported format '${ext}'. Supported: PDF, DOCX, TXT, PNG, JPG.`);
      return;
    }

    setSelectedFile(file);

    // Image preview
    if (['.png', '.jpg', '.jpeg'].includes(ext)) {
      setPreviewUrl(URL.createObjectURL(file));
    } else {
      setPreviewUrl(null);
    }
  };

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFileSelect(e.dataTransfer.files[0]);
    }
  };

  const handleUploadAndProcess = async () => {
    if (!activeOrganisationId || !selectedFile || !selectedKitId) return;

    setProcessingState('QUEUED');
    setProgressPercent(15);
    setErrorMessage(null);

    const formData = new FormData();
    formData.append('file', selectedFile);
    formData.append('brand_kit_id', selectedKitId);
    if (customTitle.trim()) {
      formData.append('title', customTitle.trim());
    }
    formData.append('auto_submit', autoSubmit ? 'true' : 'false');
    formData.append('mode', analysisMode);

    try {
      setProcessingState('PROCESSING');
      setProgressPercent(45);

      const data = await uploadDocument(activeOrganisationId, formData);
      setProgressPercent(100);
      setProcessingState('COMPLETED');
      setResult(data);
    } catch (err) {
      setProcessingState('FAILED');
      setErrorMessage(err instanceof Error ? err.message : 'Document processing failed.');
    }
  };

  const resetUpload = () => {
    setSelectedFile(null);
    setPreviewUrl(null);
    setResult(null);
    setProcessingState('IDLE');
    setErrorMessage(null);
    setCustomTitle('');
  };

  return (
    <div className="space-y-8 max-w-5xl mx-auto">
      {/* Page Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-6">
        <div>
          <div className="inline-flex items-center gap-2 rounded-full border border-indigo-500/30 bg-indigo-500/10 px-3 py-1 text-xs font-medium text-indigo-300 mb-2">
            <Upload className="h-3.5 w-3.5" />
            <span>Multimodal Ingestion Pipeline</span>
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-white">
            Document Ingestion & Text Extraction
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Upload PDF, DOCX, TXT, or image files. Extracted text is automatically routed to the deterministic compliance engine.
          </p>
        </div>
      </div>

      {/* Main Upload Form */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left 2 Cols: Drag & Drop Zone */}
        <div className="lg:col-span-2 space-y-4">
          <div
            onDragEnter={handleDrag}
            onDragLeave={handleDrag}
            onDragOver={handleDrag}
            onDrop={handleDrop}
            className={`rounded-2xl border-2 border-dashed p-8 text-center transition flex flex-col items-center justify-center min-h-[300px] ${
              dragActive
                ? 'border-indigo-500 bg-indigo-500/10'
                : selectedFile
                ? 'border-slate-700 bg-slate-900/40'
                : 'border-slate-800 bg-slate-900/20 hover:border-slate-700'
            }`}
          >
            {selectedFile ? (
              <div className="space-y-4 max-w-md">
                <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-indigo-600/20 border border-indigo-500/30 text-indigo-400">
                  {selectedFile.name.endsWith('.pdf') ? (
                    <FileType className="h-7 w-7" />
                  ) : ['.png', '.jpg', '.jpeg'].some((e) => selectedFile.name.endsWith(e)) ? (
                    <ImageIcon className="h-7 w-7" />
                  ) : (
                    <FileText className="h-7 w-7" />
                  )}
                </div>

                <div>
                  <h4 className="text-sm font-semibold text-white truncate">{selectedFile.name}</h4>
                  <p className="text-xs text-slate-400 mt-0.5">
                    {(selectedFile.size / 1024).toFixed(1)} KB • {selectedFile.type || 'Document'}
                  </p>
                </div>

                {previewUrl && (
                  <div className="rounded-xl border border-slate-800 overflow-hidden max-h-40 mx-auto">
                    <img src={previewUrl} alt="Preview" className="h-full w-full object-contain" />
                  </div>
                )}

                <button
                  type="button"
                  onClick={resetUpload}
                  className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-rose-400 transition"
                >
                  <X className="h-3.5 w-3.5" />
                  <span>Choose different file</span>
                </button>
              </div>
            ) : (
              <div className="space-y-3">
                <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-slate-800 text-slate-400">
                  <Upload className="h-6 w-6" />
                </div>
                <div>
                  <p className="text-sm font-semibold text-white">
                    Drag and drop your document here, or{' '}
                    <label className="text-indigo-400 hover:underline cursor-pointer">
                      <span>browse</span>
                      <input
                        type="file"
                        className="hidden"
                        accept=".pdf,.docx,.txt,.png,.jpg,.jpeg"
                        onChange={(e) => e.target.files?.[0] && handleFileSelect(e.target.files[0])}
                      />
                    </label>
                  </p>
                  <p className="text-xs text-slate-500 mt-1">
                    Supports PDF, DOCX, TXT, PNG, JPG up to 10MB
                  </p>
                </div>
              </div>
            )}
          </div>

          {/* Processing Progress Bar */}
          {processingState !== 'IDLE' && (
            <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 space-y-2">
              <div className="flex items-center justify-between text-xs">
                <span className="font-medium text-slate-300">
                  {processingState === 'QUEUED' && 'Queued for parsing...'}
                  {processingState === 'PROCESSING' && 'Extracting text & running compliance...'}
                  {processingState === 'COMPLETED' && 'Extraction & analysis complete'}
                  {processingState === 'FAILED' && 'Extraction failed'}
                </span>
                <span className="text-slate-400 font-mono">{progressPercent}%</span>
              </div>
              <div className="h-2 w-full rounded-full bg-slate-800 overflow-hidden">
                <div
                  className={`h-full transition-all duration-300 ${
                    processingState === 'FAILED' ? 'bg-rose-500' : 'bg-indigo-600'
                  }`}
                  style={{ width: `${progressPercent}%` }}
                />
              </div>
            </div>
          )}

          {/* Error Message */}
          {errorMessage && (
            <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-xs text-rose-300 flex items-center gap-2">
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span>{errorMessage}</span>
            </div>
          )}
        </div>

        {/* Right Col: Configuration & Metadata */}
        <div className="space-y-4">
          <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-6 space-y-5">
            <h3 className="text-sm font-semibold text-white">Target Brand & Options</h3>

            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1.5">
                Target Brand Kit
              </label>
              <select
                value={selectedKitId}
                onChange={(e) => setSelectedKitId(e.target.value)}
                className="w-full rounded-xl bg-slate-950 border border-slate-800 px-3 py-2 text-xs text-white focus:outline-none focus:border-indigo-500"
              >
                {brandKits.map((k) => (
                  <option key={k.id} value={k.id}>
                    {k.name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1.5">
                Submission Title (Optional)
              </label>
              <input
                type="text"
                value={customTitle}
                onChange={(e) => setCustomTitle(e.target.value)}
                placeholder="Defaults to original filename"
                className="w-full rounded-xl bg-slate-950 border border-slate-800 px-3.5 py-2 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1.5">
                Compliance Review Mode
              </label>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <button
                  type="button"
                  onClick={() => setAnalysisMode('hybrid')}
                  className={`rounded-xl border p-2 text-left transition ${
                    analysisMode === 'hybrid'
                      ? 'border-indigo-500 bg-indigo-950/30 text-white font-semibold'
                      : 'border-slate-800 bg-slate-950 text-slate-400'
                  }`}
                >
                  <span className="block text-[11px] font-bold">Hybrid AI (RAG)</span>
                  <span className="block text-[10px] text-slate-400">Rules + Chunks</span>
                </button>
                <button
                  type="button"
                  onClick={() => setAnalysisMode('deterministic')}
                  className={`rounded-xl border p-2 text-left transition ${
                    analysisMode === 'deterministic'
                      ? 'border-indigo-500 bg-indigo-950/30 text-white font-semibold'
                      : 'border-slate-800 bg-slate-950 text-slate-400'
                  }`}
                >
                  <span className="block text-[11px] font-bold">Deterministic</span>
                  <span className="block text-[10px] text-slate-400">Strict rules only</span>
                </button>
              </div>
            </div>

            <div className="flex items-center gap-2 pt-1">
              <input
                type="checkbox"
                id="autoSubmit"
                checked={autoSubmit}
                onChange={(e) => setAutoSubmit(e.target.checked)}
                className="rounded border-slate-700 bg-slate-950 text-indigo-600 focus:ring-0"
              />
              <label htmlFor="autoSubmit" className="text-xs text-slate-300 cursor-pointer">
                Automatically run compliance analysis on extracted text
              </label>
            </div>

            <button
              type="button"
              onClick={handleUploadAndProcess}
              disabled={!selectedFile || !selectedKitId || processingState === 'PROCESSING'}
              className="w-full inline-flex items-center justify-center gap-2 rounded-xl bg-indigo-600 px-4 py-2.5 text-xs font-semibold text-white shadow hover:bg-indigo-500 disabled:opacity-50 transition"
            >
              {processingState === 'PROCESSING' ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  <span>Processing Document...</span>
                </>
              ) : (
                <>
                  <Upload className="h-4 w-4" />
                  <span>Upload & Extract</span>
                </>
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Extraction & Compliance Results Panel */}
      {result && (
        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 space-y-6">
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-4">
            <div>
              <div className="flex items-center gap-2">
                <CheckCircle2 className="h-5 w-5 text-emerald-400" />
                <h3 className="text-base font-bold text-white">Extraction Succeeded</h3>
              </div>
              <p className="text-xs text-slate-400 mt-0.5">
                Processed via <span className="font-mono text-slate-300">{result.method}</span> • {result.char_count} characters extracted
              </p>
            </div>

            {result.submission && (
              <Link
                to="/compliance-review"
                className="inline-flex items-center gap-1.5 rounded-xl bg-indigo-600/20 border border-indigo-500/30 px-3 py-1.5 text-xs font-medium text-indigo-300 hover:bg-indigo-600/30 transition"
              >
                <span>Open in Workbench</span>
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            )}
          </div>

          {/* Compliance Summary if auto-submitted */}
          {result.submission && (
            <div className="rounded-xl border border-slate-800 bg-slate-950 p-4 flex flex-wrap items-center justify-between gap-4">
              <div>
                <span className="text-xs text-slate-400">Compliance Score</span>
                <div className="text-xl font-bold text-white flex items-center gap-2 mt-0.5">
                  <span
                    className={
                      result.submission.analysis.result === 'PASS'
                        ? 'text-emerald-400'
                        : 'text-rose-400'
                    }
                  >
                    {result.submission.analysis.score}/100
                  </span>
                  <span
                    className={`rounded px-1.5 py-0.5 text-xs font-semibold ${
                      result.submission.analysis.result === 'PASS'
                        ? 'bg-emerald-500/20 text-emerald-300'
                        : 'bg-rose-500/20 text-rose-300'
                    }`}
                  >
                    {result.submission.analysis.result}
                  </span>
                </div>
              </div>

              <div className="text-right">
                <span className="text-xs text-slate-400">Findings Detected</span>
                <div className="text-lg font-bold text-white mt-0.5">
                  {result.submission.analysis.findings.length}
                </div>
              </div>
            </div>
          )}

          {/* Extracted Text Monospace Preview */}
          <div className="space-y-2">
            <h4 className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
              Extracted Text Preview
            </h4>
            <div className="rounded-xl border border-slate-800 bg-slate-950 p-4 text-xs font-mono text-slate-200 whitespace-pre-wrap leading-relaxed max-h-60 overflow-y-auto">
              {result.extracted_text || '(No text extracted from this file)'}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ContentUploadPage;
