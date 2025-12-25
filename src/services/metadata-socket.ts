import { WS_BASE_URL } from "./api-client";

export type MetadataEventType = 
  | "idle"
  | "start" 
  | "processing" 
  | "complete" 
  | "error";

export interface MetadataMessage {
  type: MetadataEventType;
  total?: number;
  current?: number;
  processed?: number;
  updated?: number;
  skipped?: number;
  errors?: number;
  current_track?: string;
  message?: string;
}

type MessageListener = (data: MetadataMessage) => void;

class MetadataSocketManager {
  private ws: WebSocket | null = null;
  private listeners: Set<MessageListener> = new Set();
  private reconnectTimer: any | null = null;
  private isExplicitlyClosed = false;
  private reconnectInterval = 3000;

  public connect() {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    this.isExplicitlyClosed = false;
    console.info(`Connecting to WebSocket: ${WS_BASE_URL}/metadata`);
    this.ws = new WebSocket(`${WS_BASE_URL}/metadata`);

    this.ws.onopen = () => {
      console.info("Metadata WebSocket Connected");
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as MetadataMessage;
        this.notify(data);
      } catch (e) {
        console.error("Failed to parse WS message", e);
      }
    };

    this.ws.onclose = () => {
      if (!this.isExplicitlyClosed) {
        this.reconnectTimer = setTimeout(() => this.connect(), this.reconnectInterval);
      }
    };

    this.ws.onerror = (error) => {
      console.error("Metadata WebSocket Error", error);
      this.ws?.close();
    };
  }

  public disconnect() {
    this.isExplicitlyClosed = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  public addMessageListener(listener: MessageListener): () => void {
    this.listeners.add(listener);
    if (this.listeners.size === 1) {
      this.connect();
    }
    return () => {
      this.listeners.delete(listener);
      if (this.listeners.size === 0) {
        this.disconnect();
      }
    };
  }

  private notify(data: MetadataMessage) {
    this.listeners.forEach((listener) => listener(data));
  }
}

export const metadataSocket = new MetadataSocketManager();
