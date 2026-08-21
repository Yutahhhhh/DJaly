interface VocalTrackProps {
  vocal: number[] | null;
  width: number;
  height: number;
}

/** Renders PVDI vocal confidence (0-4 per frame) as a filled area chart. */
export function VocalTrack({ vocal, width, height }: VocalTrackProps) {
  if (!vocal || !vocal.length) {
    return <div className="vocal-track vocal-track--empty" style={{ width, height }} />;
  }

  const step = width / vocal.length;
  const maxVal = 4;

  const points = vocal
    .map((v, i) => {
      const x = i * step;
      const y = height - (Math.min(v, maxVal) / maxVal) * height;
      return `${x},${y}`;
    })
    .join(" ");

  const areaPoints = `0,${height} ${points} ${width},${height}`;

  return (
    <svg width={width} height={height} className="vocal-track" preserveAspectRatio="none">
      <polygon points={areaPoints} className="vocal-track__area" />
      <polyline points={points} className="vocal-track__line" fill="none" />
    </svg>
  );
}
