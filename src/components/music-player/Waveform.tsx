import { useEffect, useRef } from "react";
import { FileMetadata } from "@/services/metadata";

interface WaveformProps {
  metadata: FileMetadata | null;
  progress: number;
  duration: number;
  onSeek: (ratio: number) => void;
  isExpanded: boolean;
}

export function Waveform({ metadata, progress, duration, onSeek, isExpanded }: WaveformProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const width = canvas.width;
    const height = canvas.height;
    ctx.clearRect(0, 0, width, height);

    const rootStyles = getComputedStyle(document.documentElement);
    const primaryVal = rootStyles.getPropertyValue("--primary").trim();
    const mutedVal = rootStyles.getPropertyValue("--muted-foreground").trim();
    
    const primaryColor = `hsl(${primaryVal})`;
    const mutedColor = `hsla(${mutedVal.split(" ").join(",")}, 0.3)`;

    if (!metadata?.waveform_peaks || metadata.waveform_peaks.length === 0) {
      ctx.fillStyle = `hsla(${mutedVal.split(" ").join(",")}, 0.2)`;
      ctx.fillRect(0, height / 2 - 1, width, 2);
      
      const progressWidth = (progress / (duration || 1)) * width;
      ctx.fillStyle = primaryColor;
      ctx.fillRect(0, height / 2 - 1, progressWidth, 2);
      return;
    }

    const peaks = metadata.waveform_peaks;
    const barWidth = 3;
    const gap = 1;
    const totalBars = Math.floor(width / (barWidth + gap));
    const step = Math.ceil(peaks.length / totalBars);
    const currentRatio = progress / (duration || 1);

    for (let i = 0; i < totalBars; i++) {
      const peakIndex = Math.floor(i * step);
      const value = peaks[peakIndex] || 0;
      const barHeight = Math.max(value * height * 0.8, 2);
      const x = i * (barWidth + gap);
      const y = (height - barHeight) / 2;

      if (x / width < currentRatio) {
        ctx.fillStyle = primaryColor;
      } else {
        ctx.fillStyle = mutedColor;
      }

      ctx.fillRect(x, y, barWidth, barHeight);
    }
  }, [metadata, progress, isExpanded, duration]);

  return (
    <div 
      className="absolute -top-4 left-0 right-0 h-8 cursor-pointer group z-20 flex items-end"
      onClick={(e) => {
        const rect = e.currentTarget.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const ratio = x / rect.width;
        onSeek(ratio);
      }}
    >
      <canvas
        ref={canvasRef}
        width={1000}
        height={32}
        className="w-full h-full block opacity-80 hover:opacity-100 transition-opacity"
      />
    </div>
  );
}
