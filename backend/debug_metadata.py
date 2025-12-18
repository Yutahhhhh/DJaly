import sys
import os
# Add backend directory to sys.path to allow imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from tinytag import TinyTag
from utils.metadata import extract_metadata_smart

def debug_file(filepath):
    if not os.path.exists(filepath):
        print(f"Error: File not found: {filepath}")
        return

    print(f"--- Debugging Metadata for: {os.path.basename(filepath)} ---")
    print(f"Full Path: {filepath}")
    
    try:
        print("\n[TinyTag Raw Output]")
        tag = TinyTag.get(filepath)
        print(f"Title:  '{tag.title}'")
        print(f"Artist: '{tag.artist}'")
        
        print("\n[extract_metadata_smart Output (with Mutagen fallback)]")
        meta = extract_metadata_smart(filepath, tag)
        print(f"Title:  '{meta['title']}'")
        print(f"Artist: '{meta['artist']}'")
        print(f"Genre:  '{meta['genre']}'")
        
        if meta['artist'] == 'Unknown':
            print("\n-> FAIL: Even with Mutagen, Artist is 'Unknown'.")
        else:
            print("\n-> SUCCESS: Mutagen successfully extracted the Artist.")
            
    except Exception as e:
        print(f"\n[Error]")
        print(f"Debug failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python debug_metadata.py <path_to_music_file>")
        sys.exit(1)
    
    target_file = sys.argv[1]
    debug_file(target_file)
