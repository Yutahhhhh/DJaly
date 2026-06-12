import json
import time
import urllib.request
import urllib.error
import os
import shutil
import subprocess
import tempfile
from typing import Optional, Dict, Any, Tuple
from sqlmodel import Session
from config import settings
from infra.database.connection import get_setting_value
import ollama
from utils.logger import get_logger

logger = get_logger(__name__)

# プロバイダー定義
PROVIDER_OPENAI = "openai"
PROVIDER_CODEX = "codex"
PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_GOOGLE = "google"
PROVIDER_OLLAMA = "ollama"

LLM_ERROR_PREFIXES = ("API_ERROR:", "CONNECTION_ERROR:", "BLOCKED:", "CONFIG_ERROR:")
CODEX_DEFAULT_TIMEOUT_SECONDS = 180

# 分類・パラメータ推定タスク向けの低温度デフォルト
DEFAULT_TEMPERATURE = 0.2

# リトライ対象の HTTP ステータス (レート制限・一時的障害)
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}
MAX_RETRIES = 3

def is_llm_error(text: str) -> bool:
    return text.startswith(LLM_ERROR_PREFIXES)

def get_llm_config(session: Session) -> Tuple[str, str, str, str]:
    """
    DB設定からLLM構成を取得する。
    Returns: (provider, model_name, api_key, ollama_host)
    """
    provider = get_setting_value(session, "llm_provider", PROVIDER_OLLAMA)
    model_name = get_setting_value(session, "llm_model", "")
    
    # Default model fallback based on provider
    if not model_name:
        if provider == PROVIDER_OPENAI:
            model_name = "gpt-5.4-mini"
        elif provider == PROVIDER_CODEX:
            model_name = "gpt-5.5"
        elif provider == PROVIDER_ANTHROPIC:
            model_name = "claude-sonnet-4-20250514"
        elif provider == PROVIDER_GOOGLE:
            model_name = "gemini-2.5-flash"
        else:
            model_name = "llama3.2"
    
    api_key = ""
    if provider == PROVIDER_OPENAI:
        api_key = get_setting_value(session, "openai_api_key", "")
    elif provider == PROVIDER_ANTHROPIC:
        api_key = get_setting_value(session, "anthropic_api_key", "")
    elif provider == PROVIDER_GOOGLE:
        api_key = get_setting_value(session, "google_api_key", "")
    
    if not api_key and provider != PROVIDER_OLLAMA:
        legacy_key = get_setting_value(session, "api_key", "")
        if legacy_key:
            api_key = legacy_key

    # 環境変数からデフォルト値を取得
    default_host = settings.OLLAMA_HOST
    ollama_host = get_setting_value(session, "ollama_host", default_host)

    return provider, model_name, api_key, ollama_host

def _call_openai(api_key: str, model: str, prompt: str, temperature: float = DEFAULT_TEMPERATURE, json_mode: bool = False) -> str:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    data = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": 4096
    }
    if json_mode:
        data["response_format"] = {"type": "json_object"}
    return _execute_request(url, headers, data, parse_openai_response)

def _call_anthropic(api_key: str, model: str, prompt: str, temperature: float = DEFAULT_TEMPERATURE, json_mode: bool = False) -> str:
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "content-type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01"
    }
    messages = [{"role": "user", "content": prompt}]
    if json_mode:
        # Assistant プリフィルで JSON 出力を強制する
        messages.append({"role": "assistant", "content": "{"})
    data = {
        "model": model,
        "messages": messages,
        "max_tokens": 4096,
        "temperature": temperature
    }
    result = _execute_request(url, headers, data, parse_anthropic_response)
    if json_mode and result and not is_llm_error(result) and not result.lstrip().startswith("{"):
        result = "{" + result
    return result

def _call_google(api_key: str, model: str, prompt: str, temperature: float = DEFAULT_TEMPERATURE, json_mode: bool = False) -> str:
    # Google Gemini API
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}

    # 安全性設定: すべて BLOCK_NONE にして過剰なフィルタリングを防ぐ
    safety_settings = [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
    ]

    generation_config = {
        "temperature": temperature,
        "maxOutputTokens": 8192
    }
    if json_mode:
        generation_config["response_mime_type"] = "application/json"

    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": generation_config,
        "safetySettings": safety_settings
    }
    return _execute_request(url, headers, data, parse_google_response)

def _call_ollama(host: str, model: str, prompt: str, temperature: float = DEFAULT_TEMPERATURE, json_mode: bool = False) -> str:
    try:
        client = ollama.Client(host=host)
        kwargs: Dict[str, Any] = {"options": {"temperature": temperature}}
        if json_mode:
            kwargs["format"] = "json"
        response = client.generate(model=model, prompt=prompt, **kwargs)
        return response['response'].strip()
    except Exception as e:
        logger.error(f"Ollama Error ({host}): {e}")
        return f"CONNECTION_ERROR: Error calling Ollama: {str(e)}"

def _resolve_codex_command(configured_path: str = "") -> Optional[str]:
    candidates = [
        configured_path,
        shutil.which("codex"),
        "/opt/homebrew/bin/codex",
        "/usr/local/bin/codex",
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
        if candidate and os.path.basename(candidate) == "codex":
            resolved = shutil.which(candidate)
            if resolved:
                return resolved
    return None

def _call_codex_cli(model: str, prompt: str, cli_path: str = "", timeout_seconds: int = CODEX_DEFAULT_TIMEOUT_SECONDS) -> str:
    codex_command = _resolve_codex_command(cli_path)
    if not codex_command:
        return "CONFIG_ERROR: Codex CLI was not found. Set codex_cli_path or install the codex command."

    task_prompt = f"""
You are being used as a text-only LLM backend for Djaly.
Do not inspect files, run shell commands, edit files, or explain your process.
Answer only the user's requested content.

{prompt}
""".strip()

    try:
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=True) as output_file:
            cmd = [
                codex_command,
                "exec",
                "--sandbox",
                "read-only",
                "--ephemeral",
                "--ignore-user-config",
                "--ignore-rules",
                "--skip-git-repo-check",
                "--color",
                "never",
                "-m",
                model,
                "-o",
                output_file.name,
                "-",
            ]
            completed = subprocess.run(
                cmd,
                input=task_prompt,
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
            output_file.seek(0)
            final_message = output_file.read().strip()
    except subprocess.TimeoutExpired:
        logger.error(f"Codex CLI timed out after {timeout_seconds} seconds")
        return f"CONNECTION_ERROR: Codex CLI timed out after {timeout_seconds} seconds"
    except Exception as e:
        logger.error(f"Codex CLI Error: {e}")
        return f"CONNECTION_ERROR: Codex CLI failed: {str(e)}"

    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()

    if completed.returncode != 0:
        logger.error(f"Codex CLI failed with status {completed.returncode}: {stderr}")
        detail = stderr or stdout or "unknown error"
        return f"CONNECTION_ERROR: Codex CLI failed with status {completed.returncode}: {detail}"

    if not final_message:
        logger.warning(f"Codex CLI returned empty stdout. stderr: {stderr}")

    return final_message

def _execute_request(url: str, headers: Dict[str, str], data: Dict[str, Any], parser_func) -> str:
    last_error = "CONNECTION_ERROR: unknown error"
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(data).encode('utf-8'),
                headers=headers
            )
            with urllib.request.urlopen(req, timeout=60) as response:
                response_body = response.read().decode('utf-8')
                result = json.loads(response_body)
                parsed_text = parser_func(result)

                if not parsed_text:
                    logger.warning(f"Empty response parsed from {url}. Raw body: {response_body}")

                return parsed_text

        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8')
            logger.error(f"LLM API HTTP Error ({url}): Status {e.code}\nBody: {error_body}")
            last_error = f"API_ERROR: {e.code} - {error_body}"
            if e.code in RETRYABLE_STATUS_CODES and attempt < MAX_RETRIES - 1:
                backoff = 2 ** attempt * 2  # 2s, 4s
                logger.info(f"Retrying LLM request in {backoff}s (attempt {attempt + 2}/{MAX_RETRIES})")
                time.sleep(backoff)
                continue
            return last_error

        except Exception as e:
            logger.error(f"LLM API Connection Error ({url}): {e}")
            last_error = f"CONNECTION_ERROR: {str(e)}"
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 ** attempt * 2)
                continue
            return last_error
    return last_error

# --- Response Parsers ---
def parse_openai_response(data):
    try:
        return data['choices'][0]['message']['content'].strip()
    except (KeyError, IndexError):
        logger.error(f"OpenAI Parse Error: Unexpected format: {json.dumps(data)}")
        return ""

def parse_anthropic_response(data):
    try:
        return data['content'][0]['text'].strip()
    except (KeyError, IndexError):
        logger.error(f"Anthropic Parse Error: Unexpected format: {json.dumps(data)}")
        return ""

def parse_google_response(data):
    try:
        if 'candidates' in data and data['candidates']:
            candidate = data['candidates'][0]
            if 'content' in candidate and 'parts' in candidate['content']:
                return candidate['content']['parts'][0]['text'].strip()
            elif 'finishReason' in candidate:
                logger.warning(f"Gemini blocked response. Finish Reason: {candidate['finishReason']}")
                return f"BLOCKED: {candidate['finishReason']}"
                
        logger.error(f"Gemini Parse Error: No content in candidates. Data: {json.dumps(data)}")
        return ""
    except (KeyError, IndexError) as e:
        logger.error(f"Gemini Parse Exception: {e}, Data: {data}")
        return ""

# --- Main Public API ---

def generate_text(
    session: Session,
    prompt: str,
    model_name: Optional[str] = None,
    json_mode: bool = False,
    temperature: float = DEFAULT_TEMPERATURE
) -> str:
    provider, config_model_name, api_key, ollama_host = get_llm_config(session)

    target_model = model_name if model_name else config_model_name

    logger.info(f"Generating text with {provider} ({target_model})")

    if provider not in [PROVIDER_OLLAMA, PROVIDER_CODEX] and not api_key:
        err_msg = f"CONFIG_ERROR: API Key for {provider} is not set."
        logger.error(err_msg)
        return err_msg

    result = ""
    if provider == PROVIDER_OPENAI:
        result = _call_openai(api_key, target_model, prompt, temperature=temperature, json_mode=json_mode)
    elif provider == PROVIDER_CODEX:
        cli_path = get_setting_value(session, "codex_cli_path", "")
        timeout_value = get_setting_value(session, "codex_timeout_seconds", str(CODEX_DEFAULT_TIMEOUT_SECONDS))
        try:
            timeout_seconds = int(timeout_value)
        except ValueError:
            timeout_seconds = CODEX_DEFAULT_TIMEOUT_SECONDS
        codex_prompt = prompt
        if json_mode:
            codex_prompt = f"{prompt}\n\nRespond with a single valid JSON object only. No markdown, no commentary."
        result = _call_codex_cli(target_model, codex_prompt, cli_path=cli_path, timeout_seconds=timeout_seconds)
    elif provider == PROVIDER_ANTHROPIC:
        result = _call_anthropic(api_key, target_model, prompt, temperature=temperature, json_mode=json_mode)
    elif provider == PROVIDER_GOOGLE:
        result = _call_google(api_key, target_model, prompt, temperature=temperature, json_mode=json_mode)
    else:
        result = _call_ollama(ollama_host, target_model, prompt, temperature=temperature, json_mode=json_mode)

    return result

def check_llm_status(session: Session) -> str:
    provider, model_name, api_key, ollama_host = get_llm_config(session)
    
    if provider == PROVIDER_OLLAMA:
        try:
            client = ollama.Client(host=ollama_host)
            models_response = client.list()
            
            # Handle both dict (old) and object (new) response from ollama library
            model_list = []
            if hasattr(models_response, 'models'):
                model_list = models_response.models
            elif isinstance(models_response, dict):
                model_list = models_response.get('models', [])
            
            model_names = []
            for m in model_list:
                if hasattr(m, 'model'):
                    model_names.append(m.model)
                elif isinstance(m, dict):
                    # Old format used 'name', newer might use 'model'
                    model_names.append(m.get('name') or m.get('model'))
            
            base_model = model_name.split(':')[0]
            found = any(base_model in m for m in model_names if m)
            
            status_msg = f"Ollama Connected ({model_name} at {ollama_host})"
            if not found:
                status_msg += f" - Warning: Model '{model_name}' not found."
            return status_msg
        except Exception as e:
            return f"Ollama Connection Failed: {str(e)}"
    elif provider == PROVIDER_CODEX:
        cli_path = get_setting_value(session, "codex_cli_path", "")
        codex_command = _resolve_codex_command(cli_path)
        if not codex_command:
            return "Codex CLI Missing"
        return f"Codex CLI Configured (Model: {model_name}, Command: {codex_command})"
    else:
        if not api_key:
            return f"{provider.capitalize()} API Key Missing"
        return f"{provider.capitalize()} Configured (Model: {model_name})"

# --- Vibe Parameter Estimation ---

# 同一プロンプトの再解決を防ぐ TTL キャッシュ (ページネーションごとの LLM 再実行対策)
_VIBE_CACHE: Dict[Tuple[str, str], Tuple[float, Dict[str, Any]]] = {}
_VIBE_CACHE_TTL_SECONDS = 600
_VIBE_CACHE_MAX_SIZE = 256

def _vibe_cache_get(key: Tuple[str, str]) -> Optional[Dict[str, Any]]:
    entry = _VIBE_CACHE.get(key)
    if not entry:
        return None
    cached_at, params = entry
    if time.time() - cached_at > _VIBE_CACHE_TTL_SECONDS:
        _VIBE_CACHE.pop(key, None)
        return None
    return dict(params)

def _vibe_cache_set(key: Tuple[str, str], params: Dict[str, Any]):
    if len(_VIBE_CACHE) >= _VIBE_CACHE_MAX_SIZE:
        # 最も古いエントリを削除
        oldest_key = min(_VIBE_CACHE, key=lambda k: _VIBE_CACHE[k][0])
        _VIBE_CACHE.pop(oldest_key, None)
    _VIBE_CACHE[key] = (time.time(), dict(params))

def clear_vibe_cache():
    _VIBE_CACHE.clear()

def sanitize_vibe_params(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    LLM が返した vibe パラメータを厳格に検証・型変換・クランプする。
    変換できない値はキーごと破棄する (全体は失敗させない)。
    """
    if not isinstance(raw, dict):
        return {}

    def to_float(value) -> Optional[float]:
        if isinstance(value, bool):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    params: Dict[str, Any] = {}

    bpm = to_float(raw.get("bpm"))
    if bpm is not None and bpm > 0:
        params["bpm"] = max(60.0, min(200.0, bpm))

    for key in ("energy", "danceability", "brightness", "noisiness"):
        val = to_float(raw.get(key))
        if val is None:
            continue
        # 1-10 / 0-100 スケールで返された場合の正規化
        if val > 1.0:
            if val <= 10.0:
                val = val / 10.0
            elif val <= 100.0:
                val = val / 100.0
            else:
                val = 1.0
        params[key] = max(0.0, min(1.0, val))

    for key in ("year_min", "year_max"):
        val = to_float(raw.get(key))
        if val is None:
            continue
        year = int(val)
        if 1900 <= year <= 2100:
            params[key] = year

    if "year_min" in params and "year_max" in params and params["year_min"] > params["year_max"]:
        params["year_min"], params["year_max"] = params["year_max"], params["year_min"]

    return params

def generate_vibe_parameters(prompt_text: str, model_name: Optional[str] = None, session: Optional[Session] = None) -> Dict[str, Any]:
    if not session: return {}
    if not prompt_text or not prompt_text.strip(): return {}

    cache_key = (prompt_text.strip(), model_name or "")
    cached = _vibe_cache_get(cache_key)
    if cached is not None:
        return cached

    system_prompt = """
    You are a professional music curator. Convert the user's vibe description
    (possibly in Japanese) into target audio features for track selection.

    Return ONLY this JSON object (all values numeric, no strings):
    {"bpm": <int 60-200>, "energy": <float 0.0-1.0>, "danceability": <float 0.0-1.0>,
     "brightness": <float 0.0-1.0>, "noisiness": <float 0.0-1.0>,
     "year_min": <int, omit if unspecified>, "year_max": <int, omit if unspecified>}

    Examples:
    - "peak time techno" -> {"bpm": 132, "energy": 0.92, "danceability": 0.85, "brightness": 0.6, "noisiness": 0.55}
    - "夜のドライブ用チルR&B" -> {"bpm": 92, "energy": 0.35, "danceability": 0.6, "brightness": 0.35, "noisiness": 0.2}
    - "90s hip hop classics" -> {"bpm": 94, "energy": 0.6, "danceability": 0.75, "brightness": 0.45, "noisiness": 0.4, "year_min": 1990, "year_max": 1999}

    If the user asks for "recent" or "new" tracks, set year_min to a recent year (e.g. 2020).
    If the user asks for "old school" or "90s", set year_min and year_max accordingly.
    """
    full_prompt = f"{system_prompt}\n\nUser Prompt: {prompt_text}\n\nJSON:"

    try:
        # Use the passed model_name if available, otherwise let generate_text decide based on config
        response_text = generate_text(session, full_prompt, model_name=model_name, json_mode=True, temperature=0.1)

        if is_llm_error(response_text):
            logger.error(f"Vibe parameter generation failed: {response_text}")
            return {}

        start = response_text.find("{")
        end = response_text.rfind("}") + 1
        if start != -1 and end > start:
            json_str = response_text[start:end]
            params = sanitize_vibe_params(json.loads(json_str))
            if params:
                _vibe_cache_set(cache_key, params)
            return params
        return {}
    except Exception as e:
        logger.error(f"Error generating vibe parameters: {e}")
        return {}
