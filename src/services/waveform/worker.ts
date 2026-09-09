import { parseTile, parsePcmWindow } from './protocol';
self.onmessage = (event: MessageEvent<{id:number;buffer:ArrayBuffer;pcmBin?:number}>) => {
  try {
    const tile=event.data.pcmBin?parsePcmWindow(event.data.buffer,event.data.pcmBin):parseTile(event.data.buffer);
    postMessage({id:event.data.id,tile},{transfer:[tile.counts.buffer,...tile.fields.map(field=>field.buffer)]});
  } catch(error) {postMessage({id:event.data.id,error:error instanceof Error?error.message:String(error)});}
};
