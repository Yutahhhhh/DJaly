import { apiClient } from "@/services/api-client";
import { isTauri } from "@tauri-apps/api/core";

export async function downloadFile(url: string, defaultFilename: string) {
  try {
    if (isTauri()) {
      try {
        // Tauriのダイアログプラグインを動的インポート
        const { save } = await import("@tauri-apps/plugin-dialog");
        
        // 1. 先に保存先を聞く (ユーザー体験向上: 生成待ちの前にパスを確定)
        const path = await save({
          defaultPath: defaultFilename,
          filters: [{
            name: 'File',
            extensions: [defaultFilename.split('.').pop() || 'txt']
          }]
        });

        if (!path) return; // キャンセルされた場合は終了

        // 2. コンテンツを取得 (ここで時間がかかる可能性がある)
        const response = await fetch(url);
        if (!response.ok) {
            const errText = await response.text();
            throw new Error(`Failed to fetch file content: ${response.status} ${errText}`);
        }
        const content = await response.text();

        // 3. バックエンド経由で保存
        await apiClient.post("/system/save-file", { path, content });

        // 4. Finder/Explorerで表示
        await apiClient.post("/system/reveal-file", { path });

      } catch (e) {
        console.error("Tauri save failed:", e);
        alert("Export failed: " + (e instanceof Error ? e.message : String(e)));
      }
    } else {
      // Web環境: 従来通り Blob ダウンロード
      const response = await fetch(url);
      if (!response.ok) {
          const errText = await response.text();
          throw new Error(`Failed to fetch file content: ${response.status} ${errText}`);
      }
      const content = await response.text();
      browserDownload(content, defaultFilename);
    }
  } catch (e) {
    console.error("Download failed:", e);
    alert("Download failed: " + (e instanceof Error ? e.message : String(e)));
  }
}

function browserDownload(content: string, filename: string) {
  const blob = new Blob([content], { type: "text/plain" });
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  window.URL.revokeObjectURL(url);
}
