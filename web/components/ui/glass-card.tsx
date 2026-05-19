import { ReactNode } from "react";

interface GlassCardProps {
  children: ReactNode;
  className?: string;
}

export function GlassCard({ children, className = "" }: GlassCardProps) {
  return (
    <div className={`relative rounded-2xl overflow-hidden ${className}`}>
      {/* Frosted glass base */}
      <div
        className="absolute inset-0 backdrop-blur-2xl bg-white/[0.03]"
        aria-hidden
      />
      {/* Light leak from top-left (mimics emerald glow bleeding through glass) */}
      <div
        className="absolute inset-0 opacity-80 pointer-events-none"
        style={{
          background:
            "radial-gradient(ellipse 60% 50% at 0% 0%, rgba(52,211,153,0.18) 0%, rgba(255,255,255,0.08) 30%, rgba(0,0,0,0) 65%)",
        }}
        aria-hidden
      />
      {/* Top-left bright edge highlight */}
      <div
        className="absolute top-0 left-0 w-1/2 h-px opacity-70 pointer-events-none"
        style={{
          background:
            "linear-gradient(90deg, rgba(255,255,255,0.5) 0%, rgba(255,255,255,0) 100%)",
        }}
        aria-hidden
      />
      <div
        className="absolute top-0 left-0 w-px h-1/2 opacity-50 pointer-events-none"
        style={{
          background:
            "linear-gradient(180deg, rgba(255,255,255,0.4) 0%, rgba(255,255,255,0) 100%)",
        }}
        aria-hidden
      />
      {/* Outer border */}
      <div
        className="absolute inset-0 rounded-2xl border border-white/[0.08] pointer-events-none"
        aria-hidden
      />
      {/* Content */}
      <div className="relative z-10">{children}</div>
    </div>
  );
}