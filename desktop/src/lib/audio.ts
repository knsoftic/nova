/** Perceptual 0..1 loudness from raw PCM samples (-1..1). Normal speech lands around 0.3-0.7. */
export function computeLevel(samples: ArrayLike<number>): number {
  if (samples.length === 0) return 0;
  let sum = 0;
  for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
  const rms = Math.sqrt(sum / samples.length);
  // sqrt compresses the range so quiet speech is still visible on the meter.
  return Math.min(1, Math.sqrt(rms * 4));
}

/** Exponential smoothing so the meter does not flicker frame to frame. */
export function smoothLevel(previous: number, next: number, attack = 0.6, release = 0.15): number {
  const k = next > previous ? attack : release;
  return previous + (next - previous) * k;
}
