import { useEffect, useRef, type RefObject } from "react";

/** Live oscilloscope of the microphone signal. Draws a flat line when there is no analyser. */
export function Waveform({ analyserRef, active }: { analyserRef: RefObject<AnalyserNode | null>; active: boolean }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    let raf = 0;
    let buffer: Float32Array<ArrayBuffer> | null = null;

    const draw = () => {
      const { width, height } = canvas;
      ctx.clearRect(0, 0, width, height);
      ctx.lineWidth = 2;
      ctx.strokeStyle = active ? "#34d399" : "rgba(148,163,184,0.4)";
      ctx.beginPath();
      const analyser = analyserRef.current;
      if (active && analyser) {
        if (!buffer || buffer.length !== analyser.fftSize) buffer = new Float32Array(analyser.fftSize);
        analyser.getFloatTimeDomainData(buffer);
        const step = buffer.length / width;
        for (let x = 0; x < width; x++) {
          const y = height / 2 + buffer[Math.floor(x * step)] * height * 1.6;
          if (x === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
      } else {
        ctx.moveTo(0, height / 2);
        ctx.lineTo(width, height / 2);
      }
      ctx.stroke();
      if (active) raf = requestAnimationFrame(draw);
    };
    draw();
    return () => cancelAnimationFrame(raf);
  }, [active, analyserRef]);

  return <canvas ref={canvasRef} width={120} height={28} className="h-7 w-[120px]" aria-hidden />;
}
