"use client";

import Link from 'next/link';
import { Camera } from 'lucide-react';
import { severityColor, formatVerdict } from '../../lib/format/rule-subject';

interface DemoWithStats {
  id: string;
  featured: boolean;
  title: string;
  jurisdiction: string;
  flag: string;
  blurb: string;
  badge: string;
  stats: {
    rapidAlerts: number;
    deepViolations: number;
    rebuttals: number;
    overallVerdict: string;
    overallSeverity: string;
  };
}

export function DemoCard({ demo }: { demo: DemoWithStats }) {
  // Extract severity type safely
  const sevType: any = demo.stats.overallSeverity || 'none';

  return (
    <Link href={`/demo/${demo.id}?speed=10`} className="group block rounded-xl border border-white/[0.06] bg-white/[0.03] overflow-hidden hover:border-emerald-500/30 hover:bg-white/[0.05] transition-colors">
      <div className="aspect-video bg-slate-950 relative overflow-hidden border-b border-slate-800 flex items-center justify-center">
        {/* We use standard error fallback pattern here */}
        <video 
          src={demo.id.startsWith('us_') ? `/videos/${demo.id}.mp4` : `/media/${demo.id}.mp4`} 
          muted 
          autoPlay 
          loop 
          playsInline 
          preload="metadata"
          className="absolute inset-0 w-full h-full object-cover opacity-90 group-hover:opacity-100 transition-opacity"
          onError={(e) => {
            // Hide video if error (e.g. 404), showing background fallback
            (e.target as HTMLVideoElement).style.display = 'none';
          }}
        />
        <div className="-z-10 absolute inset-0 bg-gradient-to-br from-slate-900 to-slate-950 flex flex-col justify-center items-center">
          <Camera className="h-8 w-8 text-slate-700 mb-2" />
        </div>
        <div className="absolute top-3 right-3">
          <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-black/60 border border-slate-800 ${severityColor(sevType)}`}>
            {formatVerdict(demo.stats.overallVerdict)}
          </span>
        </div>
      </div>
      
      <div className="p-5">
        <div className="flex items-center gap-1.5 text-xs text-slate-500">
          <span>{demo.flag}</span>
          <span>{demo.jurisdiction}</span>
        </div>
        
        <h3 className="text-base font-semibold text-white mt-2 leading-tight">
          {demo.title}
        </h3>
        
        <p className="text-xs text-slate-400 line-clamp-2 mt-2 leading-relaxed">
          {demo.blurb}
        </p>
        
        <div className="mt-4 flex items-center gap-3 text-xs text-slate-500">
          {demo.stats.rapidAlerts === 0 && demo.stats.deepViolations === 0 && demo.stats.rebuttals === 0 ? (
            <span className="bg-slate-800/50 text-slate-400 px-2 py-1 rounded">Verdict-only audit &middot; 3 snapshots</span>
          ) : (
            <>
              <span>{demo.stats.rapidAlerts === 0 ? '—' : demo.stats.rapidAlerts} alerts</span>
              <span className="text-slate-700">&middot;</span>
              <span>{demo.stats.deepViolations === 0 ? '—' : demo.stats.deepViolations} violations</span>
              <span className="text-slate-700">&middot;</span>
              <span>{demo.stats.rebuttals === 0 ? '—' : demo.stats.rebuttals} rebuttals</span>
            </>
          )}
        </div>
      </div>
    </Link>
  );
}
