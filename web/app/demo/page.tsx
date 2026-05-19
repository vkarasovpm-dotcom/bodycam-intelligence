import { readFile } from 'fs/promises';
import { join } from 'path';
import Link from 'next/link';
import { ArrowRight, Camera } from 'lucide-react';
import { Session } from '../../lib/types/session';
import { formatVerdict, severityColor } from '../../lib/format/rule-subject';
import { DemoCard } from '../../components/demo-picker/demo-card';
import { GlassCard } from '@/components/ui/glass-card';

const DEMOS = [
  {
    id: 'es_robbery_shootout',
    featured: true,
    title: 'Armed robbery · tactical engagement audit',
    jurisdiction: 'ES · Police',
    flag: '🇪🇸',
    blurb: 'High-tension tactical entry involving active fire and Magnum rounds. Explores intense Layer 1 action with 23 rapid alerts, resolved under strict ECHR proportionality tracking.',
    badge: 'Lethal engagement · 23 alerts',
  },
  {
    id: 'it_carabinieri_arrest',
    featured: false,
    title: 'Carabinieri stop · procedural compliance',
    jurisdiction: 'IT · Carabinieri',
    flag: '🇮🇹',
    blurb: 'Night apprehension of a suspect on the street. Evaluates fine-grained Italian procedure under Codice di Procedura Penale and de-escalation protocols.',
    badge: 'Mixed · Medium severity',
  },
  {
    id: 'us_video1',
    featured: false,
    title: 'Routine stop · tactical escalation defused',
    jurisdiction: 'US · Police',
    flag: '🇺🇸',
    blurb: 'Sudden knife encounter with extensive warning logs. Adversarial review tests less-lethal force limits under Graham v. Connor objective parameters.',
    badge: 'Officer justified',
  },
  {
    id: 'us_video3',
    featured: false,
    title: 'Filming officers — public space access',
    jurisdiction: 'US · Police',
    flag: '🇺🇸',
    blurb: 'Citizen recording a patrol in a public park. Analyzes First Amendment documentation protections against Fourth Amendment field containment actions.',
    badge: 'Mixed · Low severity',
  },
  {
    id: 'us_video2_vision',
    featured: false,
    title: 'Traffic stop · vehicle search validation',
    jurisdiction: 'US · Police',
    flag: '🇺🇸',
    blurb: 'Warrantless personal search challenged by prosecution. Vindicated after vehicle center console inspection reveals significant hidden narcotics.',
    badge: 'Officer justified',
  },
  {
    id: 'nl_politie_inval',
    featured: false,
    title: 'Tactical entry · room clearing audit',
    jurisdiction: 'NL · Politie',
    flag: '🇳🇱',
    blurb: 'Split-second room shifting entry triggering critical ECHR life protections. Multimodal vision parsing successfully extracts a hidden handgun threat.',
    badge: 'Officer justified',
  },
  {
    id: 'us_aggression',
    featured: false,
    title: 'Fleeing vehicle stop · jail threat scrutinized',
    jurisdiction: 'US · Police',
    flag: '🇺🇸',
    blurb: 'Suspect flees a vape shop and resists exiting the car. Layer 1 flags a critical "you\'re going to jail" warning; defense invokes Pennsylvania v. Mimms and the fleeing-suspect doctrine to dismiss all charges.',
    badge: 'Officer justified · 1 → 0',
  },
];

async function getDemoStats(id: string) {
  try {
    const filePath = join(process.cwd(), 'public', 'samples', `${id}_session.json`);
    const fileContent = await readFile(filePath, 'utf-8');
    const session = JSON.parse(fileContent) as Session;
    return {
      rapidAlerts: session.rapid_alerts?.length || 0,
      deepViolations: session.deep_violations?.length || 0,
      rebuttals: session.rebuttals?.length || 0,
      overallVerdict: session.final_verdict?.overall_verdict || 'unknown',
      overallSeverity: session.final_verdict?.overall_severity || 'none',
      verdictSnapshots: session.verdict_timeline?.length || 0,
    };
  } catch (err) {
    return {
      rapidAlerts: 0,
      deepViolations: 0,
      rebuttals: 0,
      overallVerdict: 'error',
      overallSeverity: 'none',
      verdictSnapshots: 0,
    };
  }
}

export default async function DemoPickerPage() {
  const demosWithStats = await Promise.all(
    DEMOS.map(async (demo) => {
      const stats = await getDemoStats(demo.id);
      return { ...demo, stats };
    })
  );

  const featured = demosWithStats.find(d => d.featured);
  const remaining = demosWithStats.filter(d => !d.featured);

  return (
    <div className="flex flex-col text-slate-300">
      {/* Header */}
      <header className="h-12 bg-transparent backdrop-blur-sm sticky top-0 z-50 border-b border-white/[0.04] flex items-center px-6 shrink-0">
        <div className="flex items-center flex-1">
          <span className="text-sm font-semibold tracking-tight text-white">SENTINEL</span>
          <div className="h-4 w-px bg-slate-600 mx-4" />
          <span className="text-xs text-slate-500">/ demo gallery</span>
        </div>
        <div className="text-xs text-slate-700">sentinel-audit.co</div>
      </header>

      {/* Hero */}
      <div className="mt-12 max-w-6xl mx-auto px-6 text-center">
        <div className="text-xs uppercase tracking-widest text-emerald-400/70 font-semibold">
          Adversarial audit &middot; pre-computed sessions
        </div>
        <h1 className="text-4xl font-semibold text-white mt-3">
          Choose a case to audit
        </h1>
        <p className="text-base text-slate-400 mt-4 max-w-2xl mx-auto leading-relaxed">
          Each demo replays a real recording through the SENTINEL pipeline — Speechmatics transcription, Featherless rapid prosecution and deep scan, Gemini adjudication. Pick a case to watch the full audit unfold.
        </p>
      </div>

      {/* Featured Demo */}
      {featured && (
        <div className="mt-10 mx-auto max-w-6xl px-6 w-full">
          <GlassCard className="h-full p-6 shadow-2xl">
            <div className="grid grid-cols-12 gap-6">
              {/* Left Video */}
              <div className="col-span-7 flex flex-col gap-3">
                <div className="aspect-video rounded-xl overflow-hidden border border-slate-800 relative">
                  <div className="absolute top-3 left-3 z-10">
                    <span className="bg-black/60 text-white text-xs rounded px-2 py-1 font-medium">
                      &#9654; Preview
                    </span>
                  </div>
                  <video 
                    src={featured.id.startsWith('us_') ? `/videos/${featured.id}.mp4` : `/media/${featured.id}.mp4`} 
                    muted 
                    autoPlay 
                    loop 
                    playsInline 
                    preload="metadata"
                    className="w-full h-full object-cover" 
                  />
                </div>
              </div>

              {/* Right Content */}
              <div className="col-span-5 flex flex-col justify-center py-2">
                <div>
                  <span className="text-xs uppercase tracking-widest text-emerald-400 font-bold bg-emerald-500/10 px-2 py-1 rounded">
                    ★ FEATURED
                  </span>
                </div>
                <h2 className="text-3xl font-semibold text-white mt-4 leading-tight">
                  {featured.title}
                </h2>
                <div className="flex items-center gap-2 text-sm text-slate-500 mt-3 font-medium">
                  <span>{featured.flag}</span>
                  <span>{featured.jurisdiction}</span>
                </div>
                <p className="text-sm text-slate-400 mt-4 leading-relaxed">
                  {featured.blurb}
                </p>

                {/* Stats Grid */}
                <div className="grid grid-cols-2 gap-3 mt-6">
                  <div className="bg-white/[0.03] border border-white/[0.06] rounded-lg p-4">
                    <div className={`text-3xl font-bold ${featured.stats.rapidAlerts > 0 ? 'text-emerald-400' : 'text-slate-400'}`}>
                      {featured.stats.rapidAlerts}
                    </div>
                    <div className="text-xs uppercase tracking-wide text-slate-500 mt-1">Rapid Alerts</div>
                  </div>
                  <div className="bg-white/[0.03] border border-white/[0.06] rounded-lg p-4">
                    <div className={`text-3xl font-bold ${featured.stats.deepViolations > 0 ? 'text-amber-400' : 'text-slate-400'}`}>
                      {featured.stats.deepViolations}
                    </div>
                    <div className="text-xs uppercase tracking-wide text-slate-500 mt-1">Deep Violations</div>
                  </div>
                  <div className="bg-white/[0.03] border border-white/[0.06] rounded-lg p-4">
                    <div className={`text-3xl font-bold ${featured.stats.overallVerdict === 'officer_justified' ? 'text-emerald-400' : featured.stats.overallVerdict === 'mixed' ? 'text-amber-400' : 'text-red-400'} leading-tight`}>
                      {formatVerdict(featured.stats.overallVerdict)}
                    </div>
                    <div className="text-xs uppercase tracking-wide text-slate-500 mt-1">Verdict</div>
                  </div>
                  <div className="bg-white/[0.03] border border-white/[0.06] rounded-lg p-4">
                    <div className="text-3xl font-bold text-slate-200">
                      ~6 min
                    </div>
                    <div className="text-xs uppercase tracking-wide text-slate-500 mt-1">Duration</div>
                  </div>
                </div>

                <div className="mt-8">
                  <Link 
                    href={`/demo/${featured.id}?speed=4&start=20`}
                    className="inline-flex items-center gap-2 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-semibold px-6 py-3 transition-colors text-sm shadow-lg shadow-emerald-500/20"
                  >
                    Open audit <ArrowRight className="h-4 w-4" />
                  </Link>
                </div>
              </div>
            </div>
          </GlassCard>
        </div>
      )}

      {/* Grid of remaining demos */}
      <div className="mt-16 max-w-6xl mx-auto px-6 w-full">
        <div className="text-xs uppercase tracking-widest text-slate-500 font-semibold mb-6 border-b border-slate-800/50 pb-2">
          More cases
        </div>
        <div className="grid grid-cols-3 gap-6">
          {remaining.map(demo => (
            <DemoCard key={demo.id} demo={demo} />
          ))}
        </div>
      </div>

      {/* Footer */}
      <footer className="text-xs text-slate-500 text-center mt-auto py-8 border-t border-white/[0.04]">
        Powered by Vultr &middot; Google Gemini &middot; Featherless &middot; Speechmatics
      </footer>
    </div>
  );
}
