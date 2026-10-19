# Player experience principles

Build for MapleStory players and viewers. The tracker should feel alive, friendly
and game-like, with useful approximate information even when some readings fail.

- Put character, level, progress and a readable recent pace first. Reuse the current
  warm, compact design; avoid turning the product into an analytics console.
- Keep validation rigorous internally. Preserve raw evidence, quarantine, timestamps,
  provenance, character/session boundaries and exact arithmetic. A friendlier label
  never makes uncertain data trusted.
- Use one subtle estimate cue (`~` or `≈`). Keep sources and mathematical caveats
  in tooltips, a small information area and Advanced, rather than permanent symbols
  on every level or repeated warning paragraphs.
- Retain useful last-known information. State its age or paused status; never make
  an old reading or rate look freshly observed. Missing values are not zero.
- Start tentative pace promptly from defensible endpoints, then use more eligible
  recent evidence. Keep early estimates separate from complete-window rankings.
- One selected recent period should control both pace and tracked progress. Keep
  four stable summary cards; unavailable next-level estimates use a placeholder.
- Prefer full comma-separated EXP numbers where the component fits them; use K/M/B
  for genuinely compact spaces. Do not add fractional precision to approximate values.
  Percentage changes remain a fallback; conversion assumptions belong in tooltips.
- Keep useful completed-capture summaries dated, with their actual observed span.
  Chart values should be inspectable by pointer, keyboard and touch without exposing
  raw debugging details or hiding missing data behind zero.
- Recent pace may use net cumulative endpoint changes across missing captures,
  including their actual elapsed time. Invent no intermediate observations; retain
  independent valid intervals around unsafe boundaries. Keep chart gaps separate.
- Missing captures hold a dated last-observed rate, rather than implying zero gain.
  Expire old intervals by time and preserve the distinction from a current estimate.
- Keep a supported next-level duration as a dated, static historical estimate when
  live pace pauses; identify its window basis instead of clearing the card on OCR gaps.
- Twitch broadcast status and local capture health are separate facts. Unknown
  API status never means offline; an old reading never proves active capture.
- Favor game-like orange EXP bars on fixed time axes, with a secondary level-%
  chart. Missing coverage is unknown, never a zero bar or invented daily/session total.
- Call partial-coverage sums “EXP tracked”, with captured coverage in secondary
  detail. A rolling 24-hour view follows the real clock even when capture stops.
- Selected periods include all supported levels by default. Sum independent EXP
  intervals with each level's requirement; never sum percentage changes across
  levels. Offer a current-level-only filter without changing the time axis or 24h total.
- Celebrate corroborated level-ups and mark percentage resets. Leave transition
  gains unknown unless supported, and use the current level's remaining EXP for ETA.
- Reserve visible warnings for changes that affect interpretation: unresolved large
  jumps, connection problems, stale information and possible identity changes.
- Prefer a working on-screen prototype, then refine it with real use. Test actual
  persisted data and browser updates; avoid another research subsystem by default.

The public prototype remains local/read-only. Presentation estimates never enter
trusted Store accounting. Advanced retains technical evidence and historical views.
