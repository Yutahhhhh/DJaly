import os

MUSIC_DIR = os.getenv("MUSIC_DIR", "/music_data")
SUPPORTED_EXTENSIONS = ('.mp3', '.m4a', '.flac', '.wav', '.ogg', '.aac', '.aiff')

# Genre Normalization Constants
GENRE_ABBREVIATIONS = [
    (r'\bdnb\b', 'drum and bass'),
    (r'\br[\'\s]*n[\'\s]*b\b', 'r and b'),
    (r'\brock[\'\s]*n[\'\s]*roll\b', 'rock and roll'),
]

GENRE_SEPARATORS_REGEX = r'[\s\-\.\/\_,]+'