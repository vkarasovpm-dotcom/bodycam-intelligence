import Link from 'next/link';
import { Zap, Shield, Scale, FileSearch, Building2, GraduationCap } from 'lucide-react';
import { readFile } from 'fs/promises';
import { join } from 'path';
import { GlassCard } from '@/components/ui/glass-card';

async function getHeroStats() {
  try {
    const filePath = join(process.cwd(), 'public', 'samples', 'us_video2_vision_session.json');
    const fileContent = await readFile(filePath, 'utf-8');
    const session = JSON.parse(fileContent);
    return {
      rapidAlerts: session.rapid_alerts?.length || 0,
      deepViolations: session.deep_violations?.length || 0,
      overallVerdict: session.final_verdict?.overall_verdict || 'unknown',
    };
  } catch (err) {
    return { rapidAlerts: 0, deepViolations: 0, overallVerdict: 'error' };
  }
}

export default async function LandingPage() {
  const stats = await getHeroStats();

  return (
    <>
      <div className="flex flex-col font-mono text-slate-300">
        {/* Top bar */}
        <header className="h-12 bg-transparent backdrop-blur-sm sticky top-0 z-50 border-b border-white/[0.04] flex items-center justify-between px-6 shrink-0">
        <div className="flex items-center">
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-400 mr-2 align-middle" />
          <span className="text-sm font-semibold tracking-tight text-white">SENTINEL</span>
        </div>
        <Link 
          href="/demo" 
          className="text-xs text-slate-400 hover:text-emerald-400 transition-colors focus:outline-none"
        >
          demo gallery &rarr;
        </Link>
      </header>

      {/* Hero section */}
      <section className="min-h-[calc(100vh-3.5rem)] flex flex-col justify-center items-center text-center pt-[6vh] pb-16 px-6">
        <div className="max-w-5xl mx-auto">
          <div className="text-xs uppercase tracking-[0.2em] text-emerald-400/80 font-semibold mb-8">
            EVIDENCE INTEGRITY &middot; PUBLIC SAFETY
          </div>
          <h1 className="text-6xl md:text-7xl lg:text-8xl font-bold tracking-tight text-center leading-[1.05] text-white mb-8">
            Every bodycam recording, <span className="text-emerald-400">audited.</span>
          </h1>
          <p className="max-w-2xl mx-auto text-center text-slate-400 text-lg leading-relaxed mb-12">
            An adversarial review layer for bodycam evidence. Three independent reasoning passes produce a defensible verdict suitable for internal affairs review, insurance adjudication, and prosecutorial workflow.
          </p>
          <div className="flex flex-col items-center justify-center gap-6">
            <div className="flex justify-center gap-4 mt-10">
              <Link 
                href="/demo"
                className="rounded-lg bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-semibold px-6 py-3 transition-colors text-sm shadow-lg shadow-emerald-500/10"
              >
                Watch a live audit &rarr;
              </Link>
              <a 
                href="#architecture"
                className="rounded-lg border border-slate-700 hover:bg-slate-900/50 text-slate-300 font-semibold px-6 py-3 transition-colors text-sm"
              >
                View architecture
              </a>
            </div>
            <div className="text-xs text-slate-500 font-medium">
              Deterministic replay &middot; Audit trail preserved &middot; Sub-3-minute turnaround
            </div>
          </div>
          <Link href="/demo/us_video2_vision?speed=4&start=20" className="block max-w-3xl mx-auto mt-16 group text-left">
            <GlassCard className="transition-transform duration-500 group-hover:scale-[1.02]">
              <div className="aspect-video relative bg-black">
                <video 
                  src="/videos/us_video2_vision.mp4" 
                  autoPlay 
                  muted 
                  loop 
                  playsInline 
                  preload="metadata"
                  className="w-full h-full object-cover" 
                />
                <div className="absolute bottom-4 left-4">
                  <span className="text-xs text-emerald-400 bg-black/40 backdrop-blur-sm px-2 py-1 rounded font-semibold uppercase tracking-wider">
                    LIVE DEMO &middot; US BODYCAM
                  </span>
                </div>
              </div>
              <div className="px-6 py-4 flex items-center justify-between border-t border-white/[0.08] bg-black/20">
                <div className="flex items-center gap-6">
                  <div className="flex flex-col">
                    <span className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold">Rapid Alerts</span>
                    <span className="text-sm text-slate-300 font-mono">{stats.rapidAlerts}</span>
                  </div>
                  <div className="flex flex-col">
                    <span className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold">Deep Violations</span>
                    <span className="text-sm text-slate-300 font-mono">{stats.deepViolations}</span>
                  </div>
                  <div className="flex flex-col">
                    <span className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold">Verdict</span>
                    <span className="text-sm text-slate-300 font-mono capitalize">{stats.overallVerdict.replace(/_/g, ' ')}</span>
                  </div>
                </div>
                <div className="text-sm text-emerald-400 font-semibold group-hover:text-emerald-300 transition-colors">
                  Open Audit &rarr;
                </div>
              </div>
            </GlassCard>
          </Link>
        </div>
      </section>

      {/* Three-layer architecture */}
      <section id="architecture" className="py-20 max-w-6xl mx-auto px-6 w-full scroll-mt-24">
        <div className="mb-12 text-center md:text-left">
          <div className="text-xs uppercase tracking-wider text-emerald-400 font-semibold mb-2">PIPELINE</div>
          <h2 className="text-3xl font-semibold text-white">Four layers, one verdict</h2>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          {/* Layer 1 */}
          <div className="relative overflow-hidden rounded-xl border border-white/[0.06] bg-white/[0.03] p-6 flex flex-col hover:border-emerald-500/30 hover:bg-white/[0.05] transition-colors duration-300">
            <div className="text-6xl font-bold text-white/[0.05] absolute top-4 right-6 leading-none select-none z-0">01</div>
            <div className="h-12 w-12 rounded-lg bg-emerald-500/10 ring-1 ring-emerald-500/20 flex items-center justify-center mb-6 z-10">
              <Zap className="h-6 w-6 text-emerald-400" />
            </div>
            <div className="text-xs uppercase tracking-wider text-slate-500 font-semibold mb-2 z-10">LAYER 1</div>
            <h3 className="text-xl font-semibold text-white mb-2 z-10">Rapid Alerts</h3>
            <div className="inline-block px-2 py-1 rounded bg-slate-950 border border-slate-800 text-[10px] text-slate-400 mb-4 w-fit z-10">
              Featherless &middot; keyword fastpath &middot; ~5ms
            </div>
            <p className="text-sm text-slate-400 leading-relaxed mt-auto z-10">
              Catches armed-subject moments and force commands as the officer speaks.
            </p>
          </div>

          {/* Layer 2 */}
          <div className="relative overflow-hidden rounded-xl border border-white/[0.06] bg-white/[0.03] p-6 flex flex-col hover:border-emerald-500/30 hover:bg-white/[0.05] transition-colors duration-300">
            <div className="text-6xl font-bold text-white/[0.05] absolute top-4 right-6 leading-none select-none z-0">02</div>
            <div className="h-12 w-12 rounded-lg bg-emerald-500/10 ring-1 ring-emerald-500/20 flex items-center justify-center mb-6 z-10">
              <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-6 w-6 text-emerald-400"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"></path><circle cx="12" cy="12" r="3"></circle></svg>
            </div>
            <div className="text-xs uppercase tracking-wider text-slate-500 font-semibold mb-2 z-10">LAYER 2</div>
            <h3 className="text-xl font-semibold text-white mb-2 z-10">Visual Context</h3>
            <div className="inline-block px-2 py-1 rounded bg-slate-950 border border-slate-800 text-[10px] text-slate-400 mb-4 w-fit z-10">
              Gemini 3.1 Pro &middot; multimodal video
            </div>
            <p className="text-sm text-slate-400 leading-relaxed mt-auto z-10">
              Watches the footage frame-by-frame: restraints, weapons drawn, force, subject compliance.
            </p>
          </div>

          {/* Layer 3 */}
          <div className="relative overflow-hidden rounded-xl border border-white/[0.06] bg-white/[0.03] p-6 flex flex-col hover:border-emerald-500/30 hover:bg-white/[0.05] transition-colors duration-300">
            <div className="text-6xl font-bold text-white/[0.05] absolute top-4 right-6 leading-none select-none z-0">03</div>
            <div className="h-12 w-12 rounded-lg bg-emerald-500/10 ring-1 ring-emerald-500/20 flex items-center justify-center mb-6 z-10">
              <Shield className="h-6 w-6 text-emerald-400" />
            </div>
            <div className="text-xs uppercase tracking-wider text-slate-500 font-semibold mb-2 z-10">LAYER 3</div>
            <h3 className="text-xl font-semibold text-white mb-2 z-10">Deep Scan</h3>
            <div className="inline-block px-2 py-1 rounded bg-slate-950 border border-slate-800 text-[10px] text-slate-400 mb-4 w-fit z-10">
              Featherless &middot; prosecution vs defense &middot; 60s cadence
            </div>
            <p className="text-sm text-slate-400 leading-relaxed mt-auto z-10">
              Adversarial review: prosecution finds violations, defense rebuts each one.
            </p>
          </div>

          {/* Layer 4 */}
          <div className="relative overflow-hidden rounded-xl border border-white/[0.06] bg-white/[0.03] p-6 flex flex-col hover:border-emerald-500/30 hover:bg-white/[0.05] transition-colors duration-300">
            <div className="text-6xl font-bold text-white/[0.05] absolute top-4 right-6 leading-none select-none z-0">04</div>
            <div className="h-12 w-12 rounded-lg bg-emerald-500/10 ring-1 ring-emerald-500/20 flex items-center justify-center mb-6 z-10">
              <Scale className="h-6 w-6 text-emerald-400" />
            </div>
            <div className="text-xs uppercase tracking-wider text-slate-500 font-semibold mb-2 z-10">LAYER 4</div>
            <h3 className="text-xl font-semibold text-white mb-2 z-10">Verdict</h3>
            <div className="inline-block px-2 py-1 rounded bg-slate-950 border border-slate-800 text-[10px] text-slate-400 mb-4 w-fit z-10">
              Google Gemini 3.1 Pro &middot; final adjudication
            </div>
            <p className="text-sm text-slate-400 leading-relaxed mt-auto z-10">
              Weighs evidence, rebuttals, and visual facts. Issues a defensible verdict.
            </p>
          </div>
        </div>
      </section>

      {/* Built for / Use cases */}
      <section id="use-cases" className="py-20 max-w-6xl mx-auto px-6 w-full scroll-mt-24">
        <div className="mb-12 text-center md:text-left">
          <div className="text-xs uppercase tracking-wider text-emerald-400 font-semibold mb-2">DEPLOYMENT CONTEXTS</div>
          <h2 className="text-3xl font-bold text-white">Built for the people who review the footage</h2>
          <p className="text-sm text-slate-400 max-w-2xl mt-4 leading-relaxed">
            SENTINEL produces a structured verdict package — transcript, layered findings, adversarial rebuttals, and final adjudication — that fits existing review workflows.
          </p>
        </div>

        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4 mt-12">
          <div className="bg-white/[0.03] border border-white/[0.06] hover:border-emerald-500/30 hover:bg-white/[0.05] transition-colors rounded-xl p-6 flex flex-col">
            <Shield className="h-6 w-6 text-emerald-400/70 mb-4" />
            <h3 className="text-base font-semibold text-slate-100 mb-2">Internal Affairs Review</h3>
            <p className="text-sm text-slate-400 leading-relaxed">
              Standardized first-pass review for use-of-force incidents and citizen complaints. Reduces backlog and surfaces edge cases for human escalation.
            </p>
          </div>
          <div className="bg-white/[0.03] border border-white/[0.06] hover:border-emerald-500/30 hover:bg-white/[0.05] transition-colors rounded-xl p-6 flex flex-col">
            <Scale className="h-6 w-6 text-emerald-400/70 mb-4" />
            <h3 className="text-base font-semibold text-slate-100 mb-2">Prosecutorial Case Prep</h3>
            <p className="text-sm text-slate-400 leading-relaxed">
              Evidence summarization with adversarial pre-rebuttal. Identifies weak points before opposing counsel does.
            </p>
          </div>
          <div className="bg-white/[0.03] border border-white/[0.06] hover:border-emerald-500/30 hover:bg-white/[0.05] transition-colors rounded-xl p-6 flex flex-col">
            <FileSearch className="h-6 w-6 text-emerald-400/70 mb-4" />
            <h3 className="text-base font-semibold text-slate-100 mb-2">Civilian Oversight</h3>
            <p className="text-sm text-slate-400 leading-relaxed">
              Independent verdict layer with full provenance. Designed for boards that lack in-house ML capacity.
            </p>
          </div>
          <div className="bg-white/[0.03] border border-white/[0.06] hover:border-emerald-500/30 hover:bg-white/[0.05] transition-colors rounded-xl p-6 flex flex-col lg:col-span-1 md:col-span-1">
            <Building2 className="h-6 w-6 text-emerald-400/70 mb-4" />
            <h3 className="text-base font-semibold text-slate-100 mb-2">Insurance Adjudication</h3>
            <p className="text-sm text-slate-400 leading-relaxed">
              Liability assessment for departments and municipal carriers. Quantifies severity and procedural compliance.
            </p>
          </div>
          <div className="bg-white/[0.03] border border-white/[0.06] hover:border-emerald-500/30 hover:bg-white/[0.05] transition-colors rounded-xl p-6 flex flex-col lg:col-span-2 md:col-span-2">
            <GraduationCap className="h-6 w-6 text-emerald-400/70 mb-4" />
            <h3 className="text-base font-semibold text-slate-100 mb-2">Training & Policy QA</h3>
            <p className="text-sm text-slate-400 leading-relaxed">
              Replay archive analysis for academy curriculum and post-incident review.
            </p>
          </div>
        </div>
      </section>


      {/* Footer */}
      <footer className="text-xs text-slate-500 text-center mt-auto py-8 border-t border-white/[0.04]">
        Powered by Vultr &middot; Google Gemini &middot; Featherless &middot; Speechmatics
      </footer>
      </div>
    </>
  );
}
