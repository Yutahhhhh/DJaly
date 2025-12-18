import os
import sys
import uvicorn
import multiprocessing
import platformdirs

# PyInstaller for multiprocessing support (Windows/macOS)
multiprocessing.freeze_support()

if __name__ == "__main__":
    # アプリケーションデータディレクトリの確保
    APP_NAME = "Djaly"
    APP_AUTHOR = "DjalyDev"
    user_data = platformdirs.user_data_dir(APP_NAME, APP_AUTHOR)
    os.makedirs(user_data, exist_ok=True)

    # Librosaなどのキャッシュディレクトリをユーザーデータ配下に強制設定
    # (書き込み権限のない場所へのアクセスを防ぐため)
    os.environ["NUMBA_CACHE_DIR"] = os.path.join(user_data, ".numba_cache")
    os.environ["MPLCONFIGDIR"] = os.path.join(user_data, ".matplotlib")

    # PyInstallerでバンドルされた場合のパス解決（必要に応じて）
    if getattr(sys, 'frozen', False):
        base_dir = sys._MEIPASS
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    # mainモジュールからappオブジェクトを直接インポート
    # これによりPyInstaller環境下でも正しくアプリが見つかる
    from main import app

    print(f"Starting Djaly Backend Server on port 8001...")
    print(f"User Data Directory: {user_data}")

    # サーバー起動
    # reload=False は必須 (フリーズされたアプリではリロード不可)
    # workers=1 (DuckDBの並行性のためシングルワーカー推奨)
    # 文字列 "main:app" ではなく、appオブジェクトを直接渡す
    uvicorn.run(app, host="127.0.0.1", port=8001, reload=False, workers=1)