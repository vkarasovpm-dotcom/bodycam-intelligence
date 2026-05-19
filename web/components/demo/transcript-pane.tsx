"use client";

import { useRef, useEffect } from 'react';
import { useSessionStore } from '../../lib/stores/session-store';
import { SessionEvent, UtteranceEvent } from '../../lib/types/session';
import { formatTime } from '../../lib/format/time';
import { Tooltip, TooltipContent, TooltipTrigger } from '../ui/tooltip';
import { HelpCircle } from 'lucide-react';

function isUtterance(e: SessionEvent): e is UtteranceEvent {
  return e.kind === 'utterance';
}

function getSpeakerColor(speaker: string) {
  switch (speaker) {
    case 'S1':
      return 'bg-emerald-500/15 text-emerald-300';
    case 'S2':
      return 'bg-amber-500/15 text-amber-300';
    case 'S3':
      return 'bg-sky-500/15 text-sky-300';
    default:
      return 'bg-slate-500/15 text-slate-300';
  }
}

export function TranscriptPane() {
  const visibleEvents = useSessionStore(state => state.visibleEvents);
  const utterances = visibleEvents.filter(isUtterance);
  
  const scrollRef = useRef<HTMLDivElement>(null);
  const activeRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (activeRef.current) {
      activeRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }, [utterances.length]);

  return (
    <div className="flex h-full flex-col rounded-xl border border-white/[0.06] bg-white/[0.03] hover:border-emerald-500/30 hover:bg-white/[0.05] transition-colors p-5">
      <div className="sticky top-0 z-10 flex items-center justify-between border-b border-slate-800/50 pb-3 mb-4 bg-transparent">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-slate-200">Transcript</h2>
          <span className="text-xs text-slate-500">({utterances.length} utterances)</span>
        </div>
        <Tooltip>
          <TooltipTrigger>
            <HelpCircle className="h-4 w-4 text-slate-500 hover:text-slate-400" />
          </TooltipTrigger>
          <TooltipContent className="max-w-[250px] bg-slate-800 text-slate-200 border-slate-700">
            <p>Transcribed in real-time via Speechmatics.<br/>Speaker diarization, sentiment analysis, IT→EN translation in a single streaming pipeline.</p>
          </TooltipContent>
        </Tooltip>
      </div>

      <div className="flex-1 overflow-y-auto pr-2 space-y-1" ref={scrollRef}>
        {utterances.map((utt, idx) => {
          const isActive = idx === utterances.length - 1;
          
          return (
            <div 
              key={utt.utt_index}
              ref={isActive ? activeRef : null}
              className={`flex gap-3 rounded-lg py-2 px-3 transition-colors ${
                isActive 
                  ? 'border-l-2 border-emerald-400 bg-slate-900/60' 
                  : 'text-slate-400'
              }`}
            >
              <div className={`flex h-8 w-8 mt-0.5 shrink-0 items-center justify-center rounded font-mono text-xs font-medium ${getSpeakerColor(utt.speaker)}`}>
                {utt.speaker}
              </div>
              
              <div className="flex flex-col pt-0.5">
                <p className={`leading-snug ${isActive ? 'text-sm text-slate-200' : 'text-[13px] text-slate-400'}`}>
                  {utt.text}
                </p>
                <div className="flex items-center gap-2 text-xs text-slate-500 font-mono mt-1">
                  <span>{formatTime(utt.t_start)}</span>
                  {/* Sentiment chip would go here if provided in data */}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
