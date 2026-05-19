export function AmbientBackground() {
  return (
    <div className="pointer-events-none fixed inset-0 z-0 overflow-hidden bg-black" aria-hidden>
      {/* Emerald glow — top-left */}
      <div
        className="absolute -top-[20%] -left-[30%] sm:-left-[15%] w-[80%] sm:w-[55%] h-[70%] rounded-full blur-[120px] opacity-70"
        style={{
          background:
            "radial-gradient(circle at 30% 30%, rgba(52,211,153,0.55) 0%, rgba(255,255,255,0.18) 35%, rgba(0,0,0,0) 70%)",
        }}
      />
      {/* Diagonal light streak */}
      <div
        className="absolute top-[8%] -left-[10%] w-[70%] h-[1px] rotate-[28deg] opacity-40"
        style={{
          background:
            "linear-gradient(90deg, rgba(255,255,255,0) 0%, rgba(255,255,255,0.6) 50%, rgba(255,255,255,0) 100%)",
        }}
      />
      {/* Soft secondary white haze near the glow */}
      <div
        className="absolute top-[5%] left-[10%] w-[35%] h-[25%] rounded-full blur-[100px] opacity-25"
        style={{ background: "rgba(255,255,255,0.35)" }}
      />
    </div>
  );
}