import { WS_BASE_URL } from "./api-client";

export type IngestEventType = 
  | "idle"
  | "start" 
  | "processing" 
  | "cancelled" 
  | "progress" 
  | "complete" 
  | "error";

export type IngestTerminalType = "idle" | "complete" | "cancelled" | "error";

export interface IngestMessage {
  type: IngestEventType;
  total?: number;
  current?: number;
  file?: string;
  bpm?: number;
  key?: string;
  processed?: number;
  warningCount?: number;
  skipped?: number;
  errors?: number;
  start_time?: number;
  estimated_remaining?: number;
  run_id?: string | null;
  revision?: number;
  details?: {
    stage?: string;
    last_error?: string;
    active_files?: Record<string, number>;
    failed_files?: string[];
    [key: string]: unknown;
  };
  message?: string;
  [key: string]: any;
}

type MessageListener = (data: IngestMessage) => void;

class IngestionSocketManager {
  private ws: WebSocket | null = null;
  private listeners: Set<MessageListener> = new Set();
  private reconnectTimer: any | null = null;
  private isExplicitlyClosed = false;
  private reconnectInterval = 3000;

  constructor() {
    // Auto-bind methods if necessary, but arrow functions handle this well.
  }

  /**
   * Connects to the WebSocket server.
   * This is called automatically when the first listener is added,
   * but can be called manually if needed.
   */
  public connect() {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    this.isExplicitlyClosed = false;
    console.info(`Connecting to WebSocket: ${WS_BASE_URL}/ingest`);
    const socket = new WebSocket(`${WS_BASE_URL}/ingest`);
    this.ws = socket;

    socket.onopen = () => {
      console.info("Ingestion WebSocket Connected");
    };

    socket.onmessage = (event) => {
      if (this.ws !== socket) return;
      try {
        const data = JSON.parse(event.data) as IngestMessage;
        this.notify(data);
      } catch (e) {
        console.error("Failed to parse WS message", e);
      }
    };

    socket.onclose = () => {
      if (this.ws !== socket) return;
      this.ws = null;
      if (!this.isExplicitlyClosed) {
        this.reconnectTimer = setTimeout(() => this.connect(), this.reconnectInterval);
      }
    };

    socket.onerror = (error) => {
      console.error("Ingestion WebSocket Error", error);
      // Closing will trigger onclose, which handles reconnection
      socket.close();
    };
  }

  /**
   * Disconnects the WebSocket and stops reconnection attempts.
   */
  public disconnect() {
    this.isExplicitlyClosed = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      const socket = this.ws;
      this.ws = null;
      socket.close();
    }
  }

  /**
   * Adds a listener for WebSocket messages.
   * Automatically connects if not already connected.
   * Returns a function to remove the listener.
   */
  public addMessageListener(listener: MessageListener): () => void {
    this.listeners.add(listener);
    
    // Ensure connection is active when we have listeners
    this.connect();

    return () => {
      this.listeners.delete(listener);
      // Optional: Disconnect if no listeners left? 
      // For now, we keep it open to avoid frequent reconnects if components unmount/remount quickly.
    };
  }

  private notify(data: IngestMessage) {
    this.listeners.forEach((listener) => listener(data));
  }
}

// Singleton instance
export const ingestionSocket = new IngestionSocketManager();
