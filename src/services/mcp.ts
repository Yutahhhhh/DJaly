import { apiClient } from "./api-client";

export interface McpTool {
  name: string;
  description: string;
}

export interface McpInfo {
  server_name: string;
  port: number;
  http_path: string;
  url: string;
  tool_count: number;
  tools: McpTool[];
}

export const mcpService = {
  getInfo: () => apiClient.get<McpInfo>("/mcp/info"),
};
