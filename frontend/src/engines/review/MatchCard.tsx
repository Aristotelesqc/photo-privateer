import React from 'react';
import {
  CheckCircle,
  AlertOctagon,
  EyeOff,
  RotateCcw,
  Maximize2,
  ExternalLink,
  Filter,
  Globe,
} from 'lucide-react';
import { MatchItem, ClassificationType } from '../../types';
import { Thumbnail } from '../../components/Thumbnail';
import { ProjectBadge } from '../../components/blocks/ProjectBadge';

export interface MatchCardProps {
  match: MatchItem;
  editingNote?: string;
  noteSaveState?: 'saving' | 'saved' | 'error';
  onNoteChange: (text: string) => void;
  onSaveNotes: () => void;
  onClassify: (classification: ClassificationType) => void;
  onInspect: () => void;
  onRequestRuleModal: (domain: string) => void;
}

export const MatchCard: React.FC<MatchCardProps> = ({
  match: m,
  editingNote,
  noteSaveState,
  onNoteChange,
  onSaveNotes,
  onClassify,
  onInspect,
  onRequestRuleModal,
}) => {
  const isUnreviewed = m.classification === 'UNREVIEWED';
  const isApproved = m.classification === 'APPROVED';
  const isUnauthorized = m.classification === 'UNAUTHORIZED';
  const isIrrelevant = m.classification === 'IRRELEVANT';

  return (
    <div className="bg-carbon-900 border border-carbon-800 hover:border-carbon-700/80 rounded-lg p-3 transition-colors flex flex-col md:flex-row gap-3.5 items-start text-xs shadow-2xs">
      {/* 1. Comparison Thumbnails */}
      <div
        onClick={onInspect}
        className="flex items-center gap-2 shrink-0 cursor-pointer group/inspect relative"
        title="Click to inspect large side-by-side comparison"
      >
        {/* Original photo */}
        <div className="w-20 h-20 rounded-md overflow-hidden border border-carbon-800 group-hover/inspect:border-accent-500/60 relative bg-carbon-950 transition-colors">
          <Thumbnail
            src={m.image_thumbnail_url || `/api/photos/${m.image_id}/thumbnail`}
            alt={m.image_filename || 'Original'}
            className="w-full h-full"
          />
          <span className="absolute bottom-0.5 left-0.5 px-1 py-0.2 rounded text-[8px] bg-black/80 font-mono text-carbon-400">
            Original
          </span>
          <div className="absolute inset-0 bg-carbon-950/40 opacity-0 group-hover/inspect:opacity-100 flex items-center justify-center transition-opacity">
            <Maximize2 className="w-3.5 h-3.5 text-white drop-shadow" />
          </div>
        </div>

        {/* Found remote preview */}
        {m.candidate_image_url && (
          <div className="w-20 h-20 rounded-md overflow-hidden border border-carbon-800 group-hover/inspect:border-accent-500/60 relative bg-carbon-950 transition-colors">
            <Thumbnail
              src={m.candidate_image_url}
              alt="Candidate preview"
              isRemote={true}
              className="w-full h-full"
            />
            <span className="absolute bottom-0.5 left-0.5 px-1 py-0.2 rounded text-[8px] bg-black/80 font-mono text-carbon-400">
              Found
            </span>
          </div>
        )}
      </div>

      {/* 2. Metadata Middle Cluster */}
      <div className="flex-1 min-w-0 space-y-1 w-full">
        <div className="flex flex-wrap items-center gap-1.5">
          {/* Domain */}
          <div className="flex items-center gap-1 font-semibold text-white text-xs">
            <Globe className="w-3 h-3 text-carbon-400" />
            <span>{m.domain}</span>
          </div>

          {/* Match Type */}
          <span className="px-1.5 py-0.2 rounded text-[9px] font-mono uppercase bg-carbon-800 text-carbon-300 border border-carbon-700">
            {m.match_type} Match
          </span>

          {/* Asset-only badge if no page context */}
          {m.source_kind === 'ASSET_ONLY' && (
            <span className="px-1.5 py-0.2 rounded text-[9px] font-mono uppercase bg-amber-500/10 text-amber-300 border border-amber-500/30">
              Asset Only
            </span>
          )}

          {/* New Badge */}
          {m.is_new && (
            <span className="px-1.5 py-0.2 rounded text-[9px] font-bold bg-accent-500/20 text-accent-300 border border-accent-500/30">
              NEW
            </span>
          )}

          {/* Rule applied badge */}
          {m.auto_classified_by_rule_id && (
            <span className="px-1.5 py-0.2 rounded text-[9px] font-medium bg-purple-500/20 text-purple-300 border border-purple-500/30">
              Rule Applied
            </span>
          )}
        </div>

        {/* Page Title */}
        <h4
          className="text-xs font-medium text-carbon-100 line-clamp-1"
          title={m.page_title || m.page_url || m.candidate_image_url || 'Discovered Asset'}
        >
          {m.page_title || (m.source_kind === 'ASSET_ONLY' ? 'Standalone Image Asset' : 'Untitled Web Page')}
        </h4>

        {/* Page URL & Open Tab */}
        <div className="flex items-center gap-2 text-[11px] font-mono text-carbon-400 truncate">
          {m.page_url ? (
            <a
              href={m.page_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-accent-400 hover:text-accent-300 hover:underline truncate inline-flex items-center gap-1"
            >
              <span>{m.page_url}</span>
              <ExternalLink className="w-2.5 h-2.5 shrink-0" />
            </a>
          ) : m.candidate_image_url ? (
            <a
              href={m.candidate_image_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-accent-400 hover:text-accent-300 hover:underline truncate inline-flex items-center gap-1"
            >
              <span>Direct Image Asset: {m.candidate_image_url}</span>
              <ExternalLink className="w-2.5 h-2.5 shrink-0" />
            </a>
          ) : (
            <span className="text-carbon-500 italic">No web URL provided</span>
          )}
        </div>

        {/* Timestamps & Photo Ref */}
        <div className="flex items-center gap-3 text-[10px] font-mono text-carbon-400 tabular-nums pt-0.5">
          <span>First: {new Date(m.first_seen_at).toLocaleDateString()}</span>
          <span>Last: {new Date(m.last_seen_at).toLocaleDateString()}</span>
          {m.image_filename && <span className="truncate">Photo: {m.image_filename}</span>}
          {m.image_project && (
            <ProjectBadge
              project={m.image_project}
              truncate
              className="border-carbon-700"
            />
          )}
        </div>

        {/* Inline Note */}
        <div className="pt-1 flex items-center gap-2">
          <input
            type="text"
            placeholder="Add an inline note..."
            value={editingNote !== undefined ? editingNote : m.notes || ''}
            onChange={(e) => onNoteChange(e.target.value)}
            onBlur={onSaveNotes}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.currentTarget.blur();
              }
            }}
            className="flex-1 bg-carbon-950 border border-carbon-800 rounded px-2 py-1 text-xs text-carbon-200 placeholder-carbon-500 focus:outline-none focus:border-accent-500"
          />
          {noteSaveState === 'saving' && (
            <span className="text-[10px] font-mono text-carbon-400 shrink-0">Saving...</span>
          )}
          {noteSaveState === 'saved' && (
            <span className="text-[10px] font-mono text-emerald-400 shrink-0" data-testid="note-saved-indicator">
              Saved
            </span>
          )}
          {noteSaveState === 'error' && (
            <span className="text-[10px] font-mono text-rose-400 shrink-0">Save failed</span>
          )}
        </div>
      </div>

      {/* 3. Classification Keypad / Right Column */}
      <div className="flex flex-col gap-1.5 shrink-0 w-full md:w-48 pt-1 md:pt-0">
        <div className="flex items-center justify-between">
          <span className="text-[9px] font-mono uppercase tracking-wider text-carbon-400">
            Decision
          </span>
          <button
            onClick={onInspect}
            className="text-[10px] font-mono text-accent-400 hover:text-accent-300 flex items-center gap-0.5"
          >
            <Maximize2 className="w-2.5 h-2.5" />
            <span>Inspect</span>
          </button>
        </div>

        {/* Primary Decisions (Prominent) */}
        <div className="grid grid-cols-3 gap-1">
          <button
            onClick={() => onClassify('APPROVED')}
            className={`px-1.5 py-1.5 rounded text-xs font-medium border flex flex-col items-center justify-center gap-0.5 transition-colors duration-200 ${
              isApproved
                ? 'bg-emerald-500 border-emerald-400 text-carbon-950 shadow-xs'
                : 'bg-carbon-950 border-carbon-800 text-carbon-300 hover:text-white hover:border-emerald-500/40'
            }`}
            title="Approve as legitimate use"
          >
            <CheckCircle className={`w-3.5 h-3.5 ${isApproved ? 'text-carbon-950' : 'text-emerald-400'}`} />
            <span className="text-[11px]">Approved</span>
          </button>

          <button
            onClick={() => onClassify('UNAUTHORIZED')}
            className={`px-1.5 py-1.5 rounded text-xs font-medium border flex flex-col items-center justify-center gap-0.5 transition-colors duration-200 ${
              isUnauthorized
                ? 'bg-rose-500 border-rose-400 text-white shadow-xs'
                : 'bg-carbon-950 border-carbon-800 text-carbon-300 hover:text-white hover:border-rose-500/40'
            }`}
            title="Flag as unauthorized or infringing reuse"
          >
            <AlertOctagon className={`w-3.5 h-3.5 ${isUnauthorized ? 'text-white' : 'text-rose-400'}`} />
            <span className="text-[11px]">Infringing</span>
          </button>

          <button
            onClick={() => onClassify('IRRELEVANT')}
            className={`px-1.5 py-1.5 rounded text-xs font-medium border flex flex-col items-center justify-center gap-0.5 transition-colors duration-200 ${
              isIrrelevant
                ? 'bg-carbon-700 border-carbon-600 text-white shadow-xs'
                : 'bg-carbon-950 border-carbon-800 text-carbon-300 hover:text-white hover:border-carbon-600'
            }`}
            title="Mark as irrelevant discovery"
          >
            <EyeOff className={`w-3.5 h-3.5 ${isIrrelevant ? 'text-white' : 'text-carbon-400'}`} />
            <span className="text-[11px]">Irrelevant</span>
          </button>
        </div>

        {/* Secondary Actions (Reset & Domain Rule) */}
        <div className="flex items-center justify-between gap-1 pt-0.5 text-[10px] text-carbon-400">
          <button
            onClick={() => onClassify('UNREVIEWED')}
            className={`px-1.5 py-0.5 rounded font-medium flex items-center gap-1 transition-colors duration-200 ${
              isUnreviewed
                ? 'text-amber-400 bg-amber-500/10'
                : 'text-carbon-500 hover:text-carbon-300 hover:bg-carbon-850'
            }`}
            title="Reset classification back to unreviewed"
          >
            <RotateCcw className="w-2.5 h-2.5" />
            <span>Reset</span>
          </button>

          <button
            onClick={() => onRequestRuleModal(m.domain)}
            className="hover:text-carbon-200 flex items-center gap-1 py-0.5 px-1.5 rounded hover:bg-carbon-850"
            title={`Create auto-rule for domain ${m.domain}`}
          >
            <Filter className="w-2.5 h-2.5" />
            <span>Rule</span>
          </button>
        </div>
      </div>
    </div>
  );
};
