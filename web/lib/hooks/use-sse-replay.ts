import { useEffect, useRef } from 'react';
import { useSessionStore } from '../stores/session-store';

export function useSseReplay(): void {
  const rafRef = useRef<number>(0);
  const prevTimeRef = useRef<number>(0);

  useEffect(() => {
    const loop = (time: number) => {
      const state = useSessionStore.getState();
      
      if (!state.isPlaying) {
        prevTimeRef.current = 0;
      } else {
        if (prevTimeRef.current !== 0) {
          const deltaMs = time - prevTimeRef.current;
          const deltaSec = deltaMs / 1000;
          
          if (deltaSec <= 1) {
            state.tick(deltaSec);
          }
        }
        prevTimeRef.current = time;
      }
      
      rafRef.current = requestAnimationFrame(loop);
    };

    // Start the loop
    rafRef.current = requestAnimationFrame(loop);

    return () => {
      // Cleanup on unmount
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current);
      }
    };
  }, []); // Empty deps: mount once
}
