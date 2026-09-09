import type {
  PerformanceCuePoint,
  PerformanceLoop,
  PerformanceMetadata,
  PerformanceMetadataWrite,
} from "../types/performance-metadata.ts";

export interface PerformanceMetadataRepository {
  get(trackId: number): Promise<PerformanceMetadata>;
  replace(
    trackId: number,
    metadata: PerformanceMetadataWrite,
  ): Promise<PerformanceMetadata>;
}

const MAX_CONFLICT_RETRIES = 3;

export class PerformanceMetadataConflictError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PerformanceMetadataConflictError";
  }
}

function isConflict(error: unknown): boolean {
  return typeof error === "object"
    && error !== null
    && "status" in error
    && error.status === 409;
}

function writeFrom(metadata: PerformanceMetadata): PerformanceMetadataWrite {
  return {
    revision: metadata.revision,
    cue_points: metadata.cue_points.map((cue) => ({ ...cue })),
    loops: metadata.loops.map((loop) => ({ ...loop })),
    beat_grid: metadata.beat_grid === null ? null : { ...metadata.beat_grid },
  };
}

function cueAt(metadata: PerformanceMetadata, slot: number): PerformanceCuePoint | undefined {
  return metadata.cue_points.find((cue) => cue.slot === slot);
}

function cuesEqual(
  left: PerformanceCuePoint | undefined,
  right: PerformanceCuePoint | undefined,
): boolean {
  return left === undefined
    ? right === undefined
    : right !== undefined
      && left.position_ms === right.position_ms
      && left.label === right.label
      && left.color === right.color;
}

function loopById(metadata: PerformanceMetadata, id: string): PerformanceLoop | undefined {
  return metadata.loops.find((loop) => loop.id === id);
}

function loopsEqual(
  left: PerformanceLoop | undefined,
  right: PerformanceLoop | undefined,
): boolean {
  return left === undefined
    ? right === undefined
    : right !== undefined
      && left.start_ms === right.start_ms
      && left.end_ms === right.end_ms
      && left.label === right.label;
}

function cueWrite(
  metadata: PerformanceMetadata,
  slot: number,
  positionMs: number | null,
): PerformanceMetadataWrite {
  const write = writeFrom(metadata);
  const existing = cueAt(metadata, slot);
  write.cue_points = write.cue_points.filter((cue) => cue.slot !== slot);
  if (positionMs !== null) {
    write.cue_points.push({
      slot,
      position_ms: positionMs,
      label: existing?.label ?? String.fromCharCode(65 + slot),
      color: existing?.color ?? null,
    });
    write.cue_points.sort((left, right) => left.slot - right.slot);
  }
  return write;
}

function loopWrite(
  metadata: PerformanceMetadata,
  loop: PerformanceLoop,
): PerformanceMetadataWrite {
  const write = writeFrom(metadata);
  const index = write.loops.findIndex((candidate) => candidate.id === loop.id);
  if (index === -1) write.loops.push({ ...loop });
  else write.loops[index] = { ...loop };
  return write;
}

async function persistWithRebase(
  repo: PerformanceMetadataRepository,
  trackId: number,
  baseline: PerformanceMetadata,
  targetDescription: string,
  targetUnchanged: (latest: PerformanceMetadata) => boolean,
  buildWrite: (metadata: PerformanceMetadata) => PerformanceMetadataWrite,
): Promise<PerformanceMetadata> {
  let source = baseline;
  for (let conflicts = 0; ; conflicts += 1) {
    try {
      return await repo.replace(trackId, buildWrite(source));
    } catch (error) {
      if (!isConflict(error)) throw error;
      if (conflicts >= MAX_CONFLICT_RETRIES) {
        throw new PerformanceMetadataConflictError(
          `Could not save ${targetDescription} after ${MAX_CONFLICT_RETRIES} conflict retries`,
        );
      }
      const latest = await repo.get(trackId);
      if (!targetUnchanged(latest)) {
        throw new PerformanceMetadataConflictError(
          `Cannot save ${targetDescription} because it was changed concurrently`,
        );
      }
      source = latest;
    }
  }
}

export function persistCue(
  repo: PerformanceMetadataRepository,
  trackId: number,
  baseline: PerformanceMetadata,
  slot: number,
  positionMs: number | null,
): Promise<PerformanceMetadata> {
  if (!Number.isInteger(slot) || slot < 0 || slot > 15) {
    throw new RangeError("Cue slot must be an integer from 0 through 15");
  }
  if (positionMs !== null && (!Number.isFinite(positionMs) || positionMs < 0)) {
    throw new RangeError("Cue position must be a finite non-negative number or null");
  }

  const baselineCue = cueAt(baseline, slot);
  return persistWithRebase(
    repo,
    trackId,
    baseline,
    `cue slot ${slot}`,
    (latest) => cuesEqual(cueAt(latest, slot), baselineCue),
    (metadata) => cueWrite(metadata, slot, positionMs),
  );
}

export function persistLoop(
  repo: PerformanceMetadataRepository,
  trackId: number,
  baseline: PerformanceMetadata,
  loop: PerformanceLoop,
): Promise<PerformanceMetadata> {
  if (typeof loop.id !== "string" || loop.id.trim().length === 0) {
    throw new TypeError("Loop id must be a non-empty string");
  }
  if (!Number.isFinite(loop.start_ms) || loop.start_ms < 0) {
    throw new RangeError("Loop start must be a finite non-negative number");
  }
  if (!Number.isFinite(loop.end_ms) || loop.end_ms <= loop.start_ms) {
    throw new RangeError("Loop end must be finite and greater than its start");
  }

  const baselineLoop = loopById(baseline, loop.id);
  return persistWithRebase(
    repo,
    trackId,
    baseline,
    `loop ${loop.id}`,
    (latest) => loopsEqual(loopById(latest, loop.id), baselineLoop),
    (metadata) => loopWrite(metadata, loop),
  );
}

export function cuePositions(
  metadata: PerformanceMetadata,
  durationMs: number,
): Array<number | null> {
  if (!Number.isFinite(durationMs) || durationMs < 0) {
    throw new RangeError("Track duration must be a finite non-negative number");
  }
  const positions: Array<number | null> = Array.from({ length: metadata.cue_points.some(cue => cue.slot >= 8) ? 16 : 8 }, () => null);
  for (const cue of metadata.cue_points) {
    if (!Number.isInteger(cue.slot) || cue.slot < 0 || cue.slot > 15) {
      throw new RangeError(`Stored cue slot ${String(cue.slot)} is outside 0 through 15`);
    }
    if (!Number.isFinite(cue.position_ms) || cue.position_ms < 0 || cue.position_ms >= durationMs) {
      throw new RangeError(`Stored cue position for slot ${cue.slot} is outside the track duration`);
    }
    if (positions[cue.slot] !== null) {
      throw new Error(`Stored cue slot ${cue.slot} is duplicated`);
    }
    positions[cue.slot] = cue.position_ms;
  }
  return positions;
}
