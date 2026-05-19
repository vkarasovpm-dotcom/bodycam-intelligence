"use client";

import { useEffect } from 'react';
import { Session } from '../../../lib/types/session';
import { useSessionStore } from '../../../lib/stores/session-store';
import { useSseReplay } from '../../../lib/hooks/use-sse-replay';
import { TranscriptPane } from '../../../components/demo/transcript-pane';
import { VerdictCard } from '../../../components/demo/verdict-card';
import { LiveBanner } from '../../../components/demo/live-banner';
import { BodycamPlayer } from '../../../components/demo/bodycam-player';
import { AlertsFeed } from '../../../components/demo/alerts-feed';
import { DeepScanFeed } from '../../../components/demo/deep-scan-feed';
import { Play, Pause, RotateCcw } from 'lucide-react';

interface DemoReplayClientProps {
  session: Session;
  sessionId: string;
  initialSpeed: 1 | 2 | 4 | 10;
  initialT?: number;
}

export default function DemoReplayClient({ session, sessionId, initialSpeed, initialT = 0 }: DemoReplayClientProps) {
  // Setup store on mount
  useEffect(() => {
    const store = useSessionStore.getState();
    store.loadSession(session);
    if (initialT > 0) {
      store.setCurrentT(initialT);
    }
    store.setSpeed(initialSpeed);
    store.play();
  }, [session, initialSpeed, initialT]);

  // Start the rAF loop
  useSseReplay();

  // Reactive store subscriptions
  const currentT = useSessionStore(state => state.currentT);
  const isPlaying = useSessionStore(state => state.isPlaying);
  const playbackSpeed = useSessionStore(state => state.playbackSpeed);
  const visibleEvents = useSessionStore(state => state.visibleEvents);
  const currentVerdict = useSessionStore(state => state.currentVerdict);
  const activeRapidAlerts = useSessionStore(state => state.activeRapidAlerts);

  const rapidAlertCount = visibleEvents.filter(e => e.kind === 'rapid_alert').length;
  const deepScanCount = visibleEvents.filter(e => e.kind === 'deep_scan_completed').length;

  const maxT = session.events.length > 0 ? session.events[session.events.length - 1].t : 0;

  const handlePlayPause = () => useSessionStore.getState().togglePlay();
  const handleReset = () => useSessionStore.getState().reset();
  const handleSetSpeed = (s: 1 | 2 | 4 | 10) => useSessionStore.getState().setSpeed(s);

  return (
    <>
      {/* Mobile overlay */}
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950 p-6 xl:hidden">
        <div className="max-w-sm rounded-lg border border-slate-800 bg-slate-900 p-6 text-center text-slate-300">
          <h1 className="text-lg font-semibold tracking-tight text-white mb-1">SENTINEL</h1>
          <p className="text-xs text-slate-500 mb-5 uppercase tracking-wider">Adversarial audit layer</p>
          <p>
            SENTINEL Demo requires a desktop browser (≥1280px). Open 
            <span className="block mt-2 font-mono text-emerald-500">sentinel-audit.co/demo/{sessionId}</span>
            on desktop.
          </p>
        </div>
      </div>

      {/* Desktop Layout */}
      <div className="hidden xl:flex h-screen flex-col bg-transparent text-slate-300">
        {/* Top bar */}
        <header className="flex h-12 bg-transparent backdrop-blur-sm sticky top-0 z-50 items-center justify-between border-b border-white/[0.04] px-6 shrink-0">
          <div className="flex items-center space-x-4">
            <span className="text-sm font-semibold tracking-tight text-white">SENTINEL</span>
            <div className="h-4 w-px bg-slate-600" />
            <div className="flex items-center space-x-2 rounded-full bg-slate-900 border border-slate-800 px-3 py-1">
              <div className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-xs font-medium text-slate-400">
                Replay &middot; pre-computed session &middot; sentinel-audit.co
              </span>
            </div>
          </div>
          <div className="flex items-center space-x-3 text-sm font-mono">
            <div className="flex items-center space-x-1.5">
              {isPlaying ? (
                <>
                  <div className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  <span className="text-emerald-400">LIVE</span>
                </>
              ) : (
                <>
                  <div className="h-1.5 w-1.5 rounded-full bg-slate-500" />
                  <span className="text-slate-500">PAUSED</span>
                </>
              )}
            </div>
            <span className="rounded bg-slate-900 border border-slate-800 px-2 py-0.5">{playbackSpeed}×</span>
          </div>
        </header>

        {/* Main grid */}
        <main className="flex-1 overflow-hidden">
          <div className="grid h-full grid-cols-12 gap-6 p-6">
            {/* Left Column */}
            <div className="col-span-7 flex flex-col gap-6 min-h-0">
              <div className="flex-none max-h-[400px]">
                <BodycamPlayer sessionId={sessionId} />
              </div>
              <div className="flex-1 min-h-0">
                <TranscriptPane />
              </div>
            </div>

            {/* Right Column */}
            <div className="col-span-5 flex flex-col gap-6 min-h-0">
              <div className="flex-none">
                <LiveBanner />
                <VerdictCard />
              </div>
              <div className="flex-1 min-h-0 overflow-hidden">
                <AlertsFeed />
              </div>
              <div className="flex-1 min-h-0 overflow-hidden">
                <DeepScanFeed />
              </div>
            </div>
          </div>
        </main>

        {/* Bottom bar */}
        <footer className="flex h-14 items-center justify-between border-t border-slate-800 px-6 shrink-0 bg-transparent">
          <div className="flex items-center space-x-4">
            <button 
              onClick={handlePlayPause}
              className="flex items-center space-x-1.5 rounded bg-emerald-500/10 border border-emerald-500/30 px-4 py-1.5 text-sm font-medium text-emerald-300 hover:bg-emerald-500/20 transition-colors"
            >
              {isPlaying ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
              <span>{isPlaying ? 'Pause' : 'Play'}</span>
            </button>
            <button 
              onClick={handleReset}
              className="flex items-center space-x-1.5 rounded bg-slate-800 px-4 py-1.5 text-sm font-medium hover:bg-slate-700 transition-colors text-slate-300"
            >
              <RotateCcw className="h-4 w-4" />
              <span>Reset</span>
            </button>
          </div>
          
          <div className="flex items-center space-x-4">
            <div className="flex items-center space-x-2">
              <span className="text-sm text-slate-500 mr-2">Speed:</span>
              {([1, 2, 4, 10] as const).map((s) => (
                <button
                  key={s}
                  onClick={() => handleSetSpeed(s)}
                  className={`rounded px-3 py-1 text-sm font-mono transition-colors ${
                    playbackSpeed === s 
                      ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 ring-1 ring-emerald-400/50' 
                      : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
                  }`}
                >
                  {s}×
                </button>
              ))}
            </div>
            <div className="pl-4 border-l border-slate-800">
              <span className="text-[10px] text-slate-700 uppercase tracking-wider">audited by SENTINEL &middot; v0.1</span>
            </div>
          </div>
        </footer>
      </div>
    </>
  );
}
