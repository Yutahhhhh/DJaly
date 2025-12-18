
# Audio Analysis Constants

# Audio Loading
# Keep 44.1kHz to preserve high-frequency content (air, brilliance) for high-quality timbre analysis.
SAMPLE_RATE = 44100

# Analysis Parameters
# Increase Frame Size to 2048 for better frequency resolution (better for bass/key).
# Increase Hop Size to 1024 to reduce the number of frames by half (2x speedup in spectral analysis loop).
FRAME_SIZE = 2048
HOP_SIZE = 1024
WINDOW_TYPE = 'hann'
KEY_PROFILE_TYPE = 'edma'
RHYTHM_METHOD = 'multifeature'

# Normalization Ranges (Min, Max)
# These are heuristic values based on typical Essentia outputs
NORM_ENERGY = (0.0, 0.4)          # Slightly increased max to prevent ceiling effect (was 0.3)
NORM_DANCEABILITY = (0.0, 2.5)
NORM_BRIGHTNESS = (500.0, 5000.0)
NORM_NOISINESS = (0.0, 0.15)
NORM_FLUX = (0.0, 1.0)            # Lowered max to boost contrast for electronic music (was 5.0)
NORM_LOUDNESS_RANGE = (0.0, 15.0) # Lowered min to capture low-dynamic range genres like EDM (was 3.0)

# Default Values
DEFAULT_LOUDNESS_RANGE = 5.0
