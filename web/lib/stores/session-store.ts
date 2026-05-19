import { create } from 'zustand';
import type { 
  Session, 
  SessionEvent, 
  VerdictTimelineSnapshot, 
  RapidAlert 
} from '../types/session';

interface SessionStoreState {
  session: Session | null;
  currentT: number;
  isPlaying: boolean;
  playbackSpeed: number;
  visibleEvents: SessionEvent[];
  currentVerdict: VerdictTimelineSnapshot | null;
  activeRapidAlerts: RapidAlert[];
  visualContextRevealed: boolean;
}

interface SessionStoreActions {
  loadSession: (session: Session) => void;
  setCurrentT: (t: number) => void;
  tick: (deltaSec: number) => void;
  play: () => void;
  pause: () => void;
  togglePlay: () => void;
  setSpeed: (speed: 1 | 2 | 4 | 10) => void;
  reset: () => void;
}

type SessionStore = SessionStoreState & SessionStoreActions;

const INITIAL_STATE: SessionStoreState = {
  session: null,
  currentT: 0,
  isPlaying: false,
  playbackSpeed: 1,
  visibleEvents: [],
  currentVerdict: null,
  activeRapidAlerts: [],
  visualContextRevealed: false,
};

function getMaxT(session: Session): number {
  let maxT = 0;
  if (session.events.length > 0) {
    const lastEvent = session.events[session.events.length - 1];
    if (lastEvent.t > maxT) {
      maxT = lastEvent.t;
    }
  }
  if (session.verdict_timeline.length > 0) {
    const lastSnapshot = session.verdict_timeline[session.verdict_timeline.length - 1];
    if (lastSnapshot.at_t > maxT) {
      maxT = lastSnapshot.at_t;
    }
  }
  return maxT;
}

function recomputeDerivedState(session: Session, currentT: number): Pick<SessionStoreState, 'visibleEvents' | 'currentVerdict' | 'activeRapidAlerts' | 'visualContextRevealed'> {
  const visibleEvents = session.events.filter(e => e.t <= currentT);
  
  let currentVerdict: VerdictTimelineSnapshot | null = null;
  for (const snapshot of session.verdict_timeline) {
    if (snapshot.at_t <= currentT) {
      currentVerdict = snapshot;
    } else {
      break;
    }
  }
  
  const activeRapidAlerts = session.rapid_alerts.filter(alert => 
    alert.t_utterance <= currentT && (currentT - alert.t_utterance) <= 8
  );
  
  const visualContextRevealed = visibleEvents.some(e => e.kind === 'visual_context_ready');
  
  return {
    visibleEvents,
    currentVerdict,
    activeRapidAlerts,
    visualContextRevealed,
  };
}

export const useSessionStore = create<SessionStore>()((set, get) => ({
  ...INITIAL_STATE,

  loadSession: (session: Session) => {
    // Defensively sort events and timeline
    const sortedEvents = [...session.events].sort((a, b) => a.t - b.t);
    const sortedTimeline = [...session.verdict_timeline].sort((a, b) => a.at_t - b.at_t);
    
    const sortedSession = {
      ...session,
      events: sortedEvents,
      verdict_timeline: sortedTimeline,
    };

    set({
      session: sortedSession,
      currentT: 0,
      isPlaying: false,
      ...recomputeDerivedState(sortedSession, 0),
    });
  },

  setCurrentT: (t: number) => {
    const { session } = get();
    if (!session) return;
    
    const maxT = getMaxT(session);
    const clampedT = Math.max(0, Math.min(t, maxT));
    
    set({
      currentT: clampedT,
      ...recomputeDerivedState(session, clampedT),
    });
  },

  tick: (deltaSec: number) => {
    const { session, currentT, playbackSpeed, isPlaying } = get();
    if (!session || !isPlaying) return;
    
    const maxT = getMaxT(session);
    const nextT = currentT + (deltaSec * playbackSpeed);
    
    if (nextT >= maxT) {
      set({
        currentT: maxT,
        isPlaying: false,
        ...recomputeDerivedState(session, maxT),
      });
    } else {
      set({
        currentT: nextT,
        ...recomputeDerivedState(session, nextT),
      });
    }
  },

  play: () => set({ isPlaying: true }),
  
  pause: () => set({ isPlaying: false }),
  
  togglePlay: () => set((state) => ({ isPlaying: !state.isPlaying })),
  
  setSpeed: (speed: 1 | 2 | 4 | 10) => {
    if ([1, 2, 4, 10].includes(speed)) {
      set({ playbackSpeed: speed });
    }
  },

  reset: () => {
    const { session, playbackSpeed } = get();
    if (!session) {
      set({ ...INITIAL_STATE, playbackSpeed });
      return;
    }
    
    set({
      currentT: 0,
      isPlaying: false,
      ...recomputeDerivedState(session, 0),
    });
  },
}));
