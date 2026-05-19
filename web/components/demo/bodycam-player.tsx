"use client";

import { useRef, useEffect, useState } from 'react';
import { useSessionStore } from '../../lib/stores/session-store';
import { Camera } from 'lucide-react';
import { formatTime } from '../../lib/format/time';

interface BodycamPlayerProps {
  sessionId: string;
}

export function BodycamPlayer({ sessionId }: BodycamPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [videoFailed, setVideoFailed] = useState(false);
  
  const currentT = useSessionStore(state => state.currentT);
  const isPlaying = useSessionStore(state => state.isPlaying);
  const playbackSpeed = useSessionStore(state => state.playbackSpeed);
  const session = useSessionStore(state => state.session);

  const maxT = session?.events.length ? session.events[session.events.length - 1].t : 0;
  const progressPct = maxT > 0 ? Math.min(100, Math.max(0, (currentT / maxT) * 100)) : 0;

  const [isMuted, setIsMuted] = useState(true);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || videoFailed) return;

    video.muted = isMuted;

    if (isPlaying) {
      video.play().catch(e => {
        console.warn("Autoplay blocked or playback failed:", e);
      });
    } else {
      video.pause();
    }
  }, [isPlaying, isMuted, videoFailed]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || videoFailed) return;
    
    // Browsers theoretically support up to 16x; capping cleanly at 10 to support rapid tests
    video.playbackRate = Math.min(playbackSpeed, 10);
  }, [playbackSpeed, videoFailed]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || videoFailed) return;
    
    // Only seek if we drift by more than 0.5s to avoid frame-by-frame stuttering
    const drift = Math.abs(video.currentTime - currentT);
    if (drift > 0.5) {
      video.currentTime = currentT;
    }
  }, [currentT, videoFailed]);

  return (
    <div className="relative rounded-xl border border-white/[0.06] overflow-hidden bg-black aspect-video flex-none group">
      {!videoFailed ? (
        <>
          <video 
            ref={videoRef}
            src={sessionId.startsWith('us_') ? `/videos/${sessionId}.mp4` : `/media/${sessionId}.mp4`}
            className="w-full h-full object-cover"
            playsInline
            autoPlay={false}
            onError={() => setVideoFailed(true)}
          />
          <button 
            onClick={() => setIsMuted(!isMuted)}
            className="absolute top-4 right-28 z-20 bg-black/60 hover:bg-black/80 text-white rounded-full p-2 transition-all opacity-0 group-hover:opacity-100"
          >
            {isMuted ? (
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon><line x1="23" y1="9" x2="17" y2="15"></line><line x1="17" y1="9" x2="23" y2="15"></line></svg>
            ) : (
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon><path d="M15.54 8.46a5 5 0 0 1 0 7.07"></path><path d="M19.07 4.93a10 10 0 0 1 0 14.14"></path></svg>
            )}
          </button>
        </>
      ) : (
        <div className="absolute inset-0 bg-gradient-to-br from-slate-900 to-slate-950 flex flex-col justify-center items-center">
          <Camera className="h-12 w-12 text-slate-700 mb-2" />
          <span className="text-xs text-slate-600 font-medium uppercase tracking-wider">Bodycam feed</span>
        </div>
      )}

      {/* Overlay: Top Left (Subject ID) */}
      <div className="absolute top-4 left-4 rounded bg-black/60 px-2 py-0.5 text-xs text-white/80">
        Body camera &middot; Officer 1
      </div>

      {/* Overlay: Top Right (Recording indicator) */}
      <div className="absolute top-4 right-4 flex items-center space-x-1.5 rounded bg-slate-950/50 px-2 py-1">
        <div className="h-1.5 w-1.5 rounded-full bg-red-500 animate-pulse" />
        <span className="text-[10px] font-bold text-red-500 tracking-wider">RECORDING</span>
      </div>

      {/* Overlay: Bottom (Timeline + Progress) */}
      <div className="absolute bottom-4 left-4 right-4">
        <div className="mb-1 text-center font-mono text-xs text-slate-300 drop-shadow-md">
          {formatTime(currentT)} / {formatTime(maxT)}
        </div>
        <div className="h-1 w-full bg-slate-800/80 rounded-full overflow-hidden">
          <div className="h-full bg-emerald-500/80" style={{ width: `${progressPct}%` }} />
        </div>
      </div>
    </div>
  );
}
