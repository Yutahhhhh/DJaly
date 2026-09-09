import { metadataService } from "../metadata";
import { jogWaveform, type JogAssets } from "./ddj1000-display";
export async function loadJogAssets(trackId: number): Promise<JogAssets> {
  const metadata = await metadataService.getMetadata(trackId);
  let artwork: number[] = [];
  // Use a blank jacket when the source has none, so the previous track's image
  // cannot survive an unload/load. This is generated locally, never fetched.
  const canvas = document.createElement("canvas"); canvas.width = canvas.height = 80;
  const context = canvas.getContext("2d");
  if (context) {
    context.fillStyle = "#111820"; context.fillRect(0, 0, 80, 80);
    if (metadata.artwork) {
      const image = new Image();
      image.src = metadata.artwork.startsWith("data:") ? metadata.artwork : `data:image/jpeg;base64,${metadata.artwork}`;
      try { await image.decode(); context.drawImage(image, 0, 0, 80, 80); } catch { /* blank jacket */ }
    }
    const blob = await new Promise<Blob | null>(resolve => canvas.toBlob(resolve, "image/jpeg", 0.65));
    if (blob && blob.size <= 32768) artwork = Array.from(new Uint8Array(await blob.arrayBuffer()));
  }
  return { waveform: metadata.waveform_peaks?.length ? jogWaveform(metadata.waveform_peaks) : [], artwork, version: 1 };
}
