# SENTINEL Design Guide

## Tone: Corporate-restrained
This is a B2B product for police departments, prosecutors, civil rights firms,
and EU regulators. Not a hackathon toy. Visual reference points:
- **Stripe Atlas** — calm density, restrained color
- **Linear** — keyboard-first feel, dark elegance
- **Vercel dashboard** — high-contrast type, generous whitespace
NOT references: Vercel marketing site (too playful), any AI startup (Anthropic
console, OpenAI, Perplexity — too neon-y), gaming UIs.

## Color philosophy
Deep graphite base (almost-black with green undertone). Emerald is the brand
but used SPARINGLY — only on:
- Logo wordmark
- Primary CTA buttons
- "officer_justified" verdict accent
- Live indicator dot in nav

For everything else: high-contrast white-on-graphite text, restrained neutrals.
Role colors (prosecution red, defense blue, judge gold) are MUTED — saturated
80-90%, not vivid.

## Palette

/* Surfaces */
--color-bg: oklch(0.14 0.012 155); /* deep graphite */
--color-surface: oklch(0.18 0.014 155); /* cards */
--color-surface-2: oklch(0.22 0.016 155); /* elevated */
--color-border: oklch(0.30 0.012 155); /* hairlines */
--color-border-glass: oklch(0.85 0.04 155 / 0.10);

/* Text */
--color-fg: oklch(0.96 0.005 155); /* primary */
--color-fg-muted: oklch(0.68 0.012 155); /* labels, captions */
--color-fg-subtle: oklch(0.48 0.010 155); /* timestamps, meta */

/* Brand */
--color-primary: oklch(0.70 0.18 155); /* muted emerald, NOT neon */
--color-primary-fg: oklch(0.99 0.005 155);
--color-primary-soft: oklch(0.70 0.18 155 / 0.12);

/* Roles — all muted (chroma ≤ 0.16) */
--color-prosecution: oklch(0.62 0.16 25); /* burgundy red */
--color-defense: oklch(0.62 0.14 240); /* steel blue */
--color-judge: oklch(0.72 0.12 85); /* old gold */
--color-vision: oklch(0.70 0.14 195); /* teal */

/* Severity */
--color-sev-none: oklch(0.50 0.02 155);
--color-sev-low: oklch(0.72 0.12 100);
--color-sev-medium: oklch(0.70 0.16 65);
--color-sev-high: oklch(0.62 0.18 25);
--color-sev-critical: oklch(0.55 0.22 15);

## Type scale
- Display H1: 56px / 1.05 / Geist Semibold, -0.02em tracking
- H2 section: 36px / 1.15 / Geist Semibold
- H3 card: 20px / 1.3 / Geist Medium
- Body: 15px / 1.55 / Geist Regular
- Mono small: 12px / 1.4 / Geist Mono (timestamps, rule_id)

## Glass — strictly limited
ONLY these surfaces use `.glass-strong` or `.glass-light`:
1. Sticky nav bar (glass-light)
2. VerdictCard (glass-strong)
3. LiveBanner (glass-strong)
4. RulingDrilldown modal (glass-strong)
5. Sponsor tooltips (glass-light)

Everywhere else: solid `--color-surface` cards with `--color-border` hairlines.
Transcript, alerts feed, deep scan feed, trace stream — ALL solid.

## Motion
- Page enter: opacity fade 200ms ease-out (no slide)
- Component enter: opacity + y(8→0) spring(200, 22)
- LiveBanner: y(-100→0) spring, 6s visible, exit y(-100)
- VerdictCard flip on final: rotateY 180° 600ms ease-spring
- Sentiment color change on utterance: 400ms ease
- Hover: 150ms only, never longer
- NO infinite glow pulses except active alert (subtle, 2s loop)

## Component density
Generous padding, low information density per card. Closer to Stripe than
Bloomberg Terminal. 16-24px padding minimum. Cards have 12-16px gap between
sections inside.
