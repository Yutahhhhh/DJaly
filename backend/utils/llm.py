import json
import urllib.request
import urllib.error
import os
from typing import Optional, Dict, Any, Tuple
from sqlmodel import Session
from config import settings
from db import get_setting_value
import ollama
from utils.logger import get_logger

logger = get_logger(__name__)

# プロバイダー定義
PROVIDER_OPENAI = "openai"
PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_GOOGLE = "google"
PROVIDER_OLLAMA = "ollama"

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
            model_name = "gpt-3.5-turbo"
        elif provider == PROVIDER_ANTHROPIC:
            model_name = "claude-3-haiku-20240307"
        elif provider == PROVIDER_GOOGLE:
            model_name = "gemini-1.5-flash"
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

def _call_openai(api_key: str, model: str, prompt: str) -> str:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    data = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.5,
        "max_tokens": 4096
    }
    return _execute_request(url, headers, data, parse_openai_response)

def _call_anthropic(api_key: str, model: str, prompt: str) -> str:
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "content-type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01"
    }
    data = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 4096,
        "temperature": 0.5
    }
    return _execute_request(url, headers, data, parse_anthropic_response)

def _call_google(api_key: str, model: str, prompt: str) -> str:
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

    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.5,
            "maxOutputTokens": 8192
        },
        "safetySettings": safety_settings
    }
    return _execute_request(url, headers, data, parse_google_response)

def _call_ollama(host: str, model: str, prompt: str) -> str:
    try:
        client = ollama.Client(host=host)
        response = client.generate(model=model, prompt=prompt)
        return response['response'].strip()
    except Exception as e:
        logger.error(f"Ollama Error ({host}): {e}")
        return f"Error calling Ollama: {str(e)}"

def _execute_request(url: str, headers: Dict[str, str], data: Dict[str, Any], parser_func) -> str:
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
        return f"API_ERROR: {e.code} - {error_body}"
        
    except Exception as e:
        logger.error(f"LLM API Connection Error ({url}): {e}")
        return f"CONNECTION_ERROR: {str(e)}"

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

def generate_text(session: Session, prompt: str, model_name: Optional[str] = None) -> str:
    provider, config_model_name, api_key, ollama_host = get_llm_config(session)
    
    target_model = model_name if model_name else config_model_name
    
    logger.info(f"Generating text with {provider} ({target_model})")

    if provider != PROVIDER_OLLAMA and not api_key:
        err_msg = f"Error: API Key for {provider} is not set."
        logger.error(err_msg)
        return err_msg

    result = ""
    if provider == PROVIDER_OPENAI:
        result = _call_openai(api_key, target_model, prompt)
    elif provider == PROVIDER_ANTHROPIC:
        result = _call_anthropic(api_key, target_model, prompt)
    elif provider == PROVIDER_GOOGLE:
        result = _call_google(api_key, target_model, prompt)
    else:
        result = _call_ollama(ollama_host, target_model, prompt)
    
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
    else:
        if not api_key:
            return f"{provider.capitalize()} API Key Missing"
        return f"{provider.capitalize()} Configured (Model: {model_name})"

def generate_vibe_parameters(prompt_text: str, model_name: Optional[str] = None, session: Optional[Session] = None) -> Dict[str, float]:
    if not session: return {}
    
    system_prompt = """
    You are a professional music curator. Analyze the given user prompt (mood/genre/scene) and estimate the ideal audio features for a track that fits this vibe.
    Return ONLY a JSON object with keys: bpm, energy, danceability, brightness, noisiness.
    """
    full_prompt = f"{system_prompt}\n\nUser Prompt: {prompt_text}\n\nJSON:"
    
    try:
        # Use the passed model_name if available, otherwise let generate_text decide based on config
        response_text = generate_text(session, full_prompt, model_name=model_name)
        
        start = response_text.find("{")
        end = response_text.rfind("}") + 1
        if start != -1 and end != -1:
            json_str = response_text[start:end]
            return json.loads(json_str)
        return {}
    except Exception as e:
        logger.error(f"Error generating vibe parameters: {e}")
        return {}
        if start != -1 and end != -1:
            json_str = response_text[start:end]
            return json.loads(json_str)
        return {}
    except Exception as e:
        logger.error(f"Error generating vibe parameters: {e}")
        return {}