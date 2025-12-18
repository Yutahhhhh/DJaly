import math
import re
from typing import Optional, Dict, List

# Camelot Wheel Adjacency Map (Harmonic Mixing Rules)
CAMELOT_ADJACENCY: Dict[str, List[str]] = {
    "1A": ["1A", "1B", "2A", "12A"],
    "1B": ["1B", "1A", "2B", "12B"],
    "2A": ["2A", "2B", "3A", "1A"],
    "2B": ["2B", "2A", "3B", "1B"],
    "3A": ["3A", "3B", "4A", "2A"],
    "3B": ["3B", "3A", "4B", "2B"],
    "4A": ["4A", "4B", "5A", "3A"],
    "4B": ["4B", "4A", "5B", "3B"],
    "5A": ["5A", "5B", "6A", "4A"],
    "5B": ["5B", "5A", "6B", "4B"],
    "6A": ["6A", "6B", "7A", "5A"],
    "6B": ["6B", "6A", "7B", "5B"],
    "7A": ["7A", "7B", "8A", "6A"],
    "7B": ["7B", "7A", "8B", "6B"],
    "8A": ["8A", "8B", "9A", "7A"],
    "8B": ["8B", "8A", "9B", "7B"],
    "9A": ["9A", "9B", "10A", "8A"],
    "9B": ["9B", "9A", "10B", "8B"],
    "10A": ["10A", "10B", "11A", "9A"],
    "10B": ["10B", "10A", "11B", "9B"],
    "11A": ["11A", "11B", "12A", "10A"],
    "11B": ["11B", "11A", "12B", "10B"],
    "12A": ["12A", "12B", "1A", "11A"],
    "12B": ["12B", "12A", "1B", "11B"],
}

KEY_TO_CAMELOT = {
    "C Major": "8B", "C Minor": "5A",
    "C# Major": "3B", "Db Major": "3B", "C# Minor": "12A",
    "D Major": "10B", "D Minor": "7A",
    "D# Major": "5B", "Eb Major": "5B", "D# Minor": "2A", "Eb Minor": "2A",
    "E Major": "12B", "E Minor": "9A",
    "F Major": "7B", "F Minor": "4A",
    "F# Major": "2B", "Gb Major": "2B", "F# Minor": "11A",
    "G Major": "9B", "G Minor": "6A",
    "G# Major": "4B", "Ab Major": "4B", "G# Minor": "1A",
    "A Major": "11B", "A Minor": "8A",
    "A# Major": "6B", "Bb Major": "6B", "A# Minor": "3A", "Bb Minor": "3A",
    "B Major": "1B", "B Minor": "10A",
}

def normalize_key(key_str: Optional[str]) -> Optional[str]:
    """Normalize key string to Camelot format (e.g. '8A')."""
    if not key_str:
        return None
    key_str = key_str.strip()
    
    if re.match(r"^\d{1,2}[AB]$", key_str):
        return key_str
    
    if key_str in KEY_TO_CAMELOT:
        return KEY_TO_CAMELOT[key_str]
    
    for k, v in KEY_TO_CAMELOT.items():
        if k.lower() in key_str.lower():
            return v
            
    return None

def calculate_mixability_score(
    target_bpm: float, 
    target_key: Optional[str], 
    candidate_bpm: float, 
    candidate_key: Optional[str],
    vector_similarity: float = 0.0,
    weights: dict = None
) -> float:
    """
    Calculate a mixability score (0.0 - 1.0) between two tracks.
    """
    w = weights or {"bpm": 0.35, "key": 0.25, "vector": 0.4}
    
    # 1. BPM Score
    if target_bpm <= 0: target_bpm = 120
    if candidate_bpm <= 0: candidate_bpm = 120
    
    bpm_ratio = candidate_bpm / target_bpm
    if bpm_ratio < 0.6: bpm_ratio *= 2
    elif bpm_ratio > 1.8: bpm_ratio /= 2
    
    # Gaussian decay based on BPM difference
    bpm_score = math.exp(-pow(bpm_ratio - 1, 2) / (2 * pow(0.08, 2))) 
    
    # 2. Key Score
    norm_t = normalize_key(target_key)
    norm_c = normalize_key(candidate_key)
    key_score = 0.0
    
    if norm_t and norm_c:
        if norm_t == norm_c:
            key_score = 1.0
        elif norm_c in CAMELOT_ADJACENCY.get(norm_t, []):
            key_score = 0.9
        else:
            key_score = 0.1
    else:
        key_score = 0.5
        
    # 3. Vector Score
    vec_score = max(0.0, min(1.0, vector_similarity))
    
    final_score = (bpm_score * w["bpm"]) + (key_score * w["key"]) + (vec_score * w["vector"])
    return final_score