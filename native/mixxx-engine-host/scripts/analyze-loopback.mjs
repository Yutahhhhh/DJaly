import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
const root = path.resolve(import.meta.dirname, '..');
const file = process.argv[2] || path.join(root, 'smoke-artifacts/loopback.wav');
const wav = await readFile(file);
assert.equal(wav.toString('ascii', 0, 4), 'RIFF');
let pcm, rate, channels, bits;
for (let offset = 12; offset + 8 <= wav.length;) {
  const type = wav.toString('ascii', offset, offset + 4), size = wav.readUInt32LE(offset + 4);
  if (type === 'fmt ') { channels = wav.readUInt16LE(offset + 10); rate = wav.readUInt32LE(offset + 12); bits = wav.readUInt16LE(offset + 22); }
  if (type === 'data') pcm = wav.subarray(offset + 8, offset + 8 + size);
  offset += 8 + size + size % 2;
}
assert.equal(channels, 2); assert.equal(bits, 16); assert.equal(rate, 44100); assert(pcm);
const frames = pcm.length / 4, window = 4096;
let peak = 0, sum = 0, best = 0, bestEnergy = -1;
for (let frame = 0; frame < frames; frame++) for (let channel = 0; channel < 2; channel++) {
  const sample = pcm.readInt16LE(frame * 4 + channel * 2); peak = Math.max(peak, Math.abs(sample)); sum += sample * sample;
}
for (let start = 0; start + window < frames; start += window) {
  let energy = 0; for (let i = 0; i < window; i++) energy += pcm.readInt16LE((start + i) * 4) ** 2;
  if (energy > bestEnergy) { bestEnergy = energy; best = start; }
}
function amplitude(channel, frequency) {
  let real = 0, imaginary = 0;
  for (let i = 0; i < window; i++) { const sample = pcm.readInt16LE((best + i) * 4 + channel * 2); const phase = 2 * Math.PI * frequency * i / rate; real += sample * Math.cos(phase); imaginary += sample * Math.sin(phase); }
  return 2 * Math.hypot(real, imaginary) / window;
}
const left440 = amplitude(0, 440), left660 = amplitude(0, 660), right440 = amplitude(1, 440), right660 = amplitude(1, 660);
assert(peak > 100, 'captured audio must be nonzero');
assert(left440 > left660 * 5, 'left output must contain the generated 440 Hz tone');
assert(right660 > right440 * 5, 'right output must contain the generated 660 Hz tone');
const report = { file, frames, durationSeconds: frames / rate, peakPCM16: peak, rmsDbFS: 20 * Math.log10(Math.sqrt(sum / (frames * 2)) / 32768), left440, left660, right440, right660, passed: true };
if (process.env.DJALY_SMOKE_TWO_DECKS === '1') {
  const windows = [];
  for (let start = 0; start + window < frames; start += window) {
    best = start;
    windows.push({ leftA: amplitude(0, 440), leftB: amplitude(0, 880), rightA: amplitude(1, 660), rightB: amplitude(1, 990) });
  }
  for (const channel of ['left', 'right']) {
    assert(windows.some(w => w[channel + 'A'] > 100 && w[channel + 'A'] > 5 * w[channel + 'B']), `${channel}: A signal must be isolated at one endpoint`);
    assert(windows.some(w => w[channel + 'B'] > 100 && w[channel + 'B'] > 5 * w[channel + 'A']), `${channel}: B signal must be isolated at the other endpoint`);
  }
  report.twoDeck = { isolatedAandB: true, windowsChecked: windows.length };
}
await writeFile(path.join(root, 'smoke-artifacts/loopback-analysis.json'), JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
