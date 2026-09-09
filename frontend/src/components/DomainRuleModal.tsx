import React, { useState } from 'react';
import { Filter, X, Check } from 'lucide-react';
import { ClassificationType } from '../types';

interface DomainRuleModalProps {
  initialDomain: string;
  onSave: (domain: string, classification: ClassificationType, notes?: string) => Promise<void>;
  onClose: () => void;
}

export const DomainRuleModal: React.FC<DomainRuleModalProps> = ({
  initialDomain,
  onSave,
  onClose,
}) => {
  const [domain, setDomain] = useState(initialDomain);
  const [classification, setClassification] = useState<ClassificationType>('APPROVED');
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!domain.trim()) return;
    setSaving(true);
    try {
      await onSave(domain.trim(), classification, notes.trim() || undefined);
      onClose();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-xs animate-fade-in">
      <div className="bg-carbon-900 border border-carbon-800 rounded-xl w-full max-w-sm shadow-2xl overflow-hidden text-carbon-100 text-xs animate-scale-up">
        <div className="px-4 py-3 border-b border-carbon-800 flex items-center justify-between bg-carbon-950/60">
          <div className="flex items-center gap-1.5">
            <Filter className="w-4 h-4 text-accent-400" />
            <h3 className="font-semibold text-white text-xs">Create Domain Rule</h3>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded text-carbon-400 hover:text-white hover:bg-carbon-800 transition-colors"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-4 space-y-3">
          <div className="space-y-1">
            <label className="block text-carbon-400 text-[11px]">Domain Pattern</label>
            <input
              type="text"
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
              required
              className="w-full bg-carbon-950 border border-carbon-800 rounded px-2.5 py-1 text-white font-mono text-xs focus:outline-none focus:border-accent-500"
              placeholder="portfolio.com"
            />
            <p className="text-[10px] text-carbon-500">
              Applies to exact domain and all subdomains.
            </p>
          </div>

          <div className="space-y-1">
            <label className="block text-carbon-400 text-[11px]">Auto Classification</label>
            <div className="grid grid-cols-3 gap-1.5">
              <button
                type="button"
                onClick={() => setClassification('APPROVED')}
                className={`py-1.5 px-2 rounded border text-center font-medium transition-all text-xs ${
                  classification === 'APPROVED'
                    ? 'bg-emerald-500/20 border-emerald-500/50 text-emerald-300'
                    : 'bg-carbon-950 border-carbon-800 text-carbon-400 hover:text-white'
                }`}
              >
                Approved
              </button>
              <button
                type="button"
                onClick={() => setClassification('IRRELEVANT')}
                className={`py-1.5 px-2 rounded border text-center font-medium transition-all text-xs ${
                  classification === 'IRRELEVANT'
                    ? 'bg-carbon-600/30 border-carbon-500 text-carbon-200'
                    : 'bg-carbon-950 border-carbon-800 text-carbon-400 hover:text-white'
                }`}
              >
                Irrelevant
              </button>
              <button
                type="button"
                onClick={() => setClassification('UNAUTHORIZED')}
                className={`py-1.5 px-2 rounded border text-center font-medium transition-all text-xs ${
                  classification === 'UNAUTHORIZED'
                    ? 'bg-rose-500/20 border-rose-500/50 text-rose-300'
                    : 'bg-carbon-950 border-carbon-800 text-carbon-400 hover:text-white'
                }`}
              >
                Infringing
              </button>
            </div>
          </div>

          <div className="space-y-1">
            <label className="block text-carbon-400 text-[11px]">Note (Optional)</label>
            <input
              type="text"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="e.g. Authorized client portfolio"
              className="w-full bg-carbon-950 border border-carbon-800 rounded px-2.5 py-1 text-white text-xs focus:outline-none focus:border-accent-500"
            />
          </div>

          <div className="pt-2 flex justify-end gap-2 border-t border-carbon-800">
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1.5 rounded text-carbon-300 hover:text-white hover:bg-carbon-850 text-xs"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="flex items-center gap-1 px-3.5 py-1.5 rounded bg-accent-600 hover:bg-accent-500 text-white font-medium shadow-xs transition-all active:scale-98 text-xs"
            >
              <Check className="w-3.5 h-3.5" />
              <span>{saving ? 'Saving...' : 'Apply Rule'}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
