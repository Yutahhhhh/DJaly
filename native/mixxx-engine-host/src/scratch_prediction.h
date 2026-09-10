#pragma once

#include <algorithm>

namespace scratch {
struct Prediction { double position; double velocity; };

// Position and its analytic derivative share one trajectory. Extrapolate for
// two packet windows, then join the final observation with a Hermite segment.
// Both joins preserve velocity; expiration never drops a nonzero lead in one
// callback. Units: frames, frames/ms, ms.
inline Prediction predict(double velocity, double age, double window) {
    age = std::max(0.0, age);
    window = std::clamp(window, 8.0, 60.0);
    if (age <= 2 * window) return {velocity * age, velocity};
    if (age >= 3 * window) return {0, 0};
    const double t = age / window - 2;
    return {velocity * window * (2 + t - 8*t*t + 5*t*t*t),
            velocity * (1 - 16*t + 15*t*t)};
}
}
