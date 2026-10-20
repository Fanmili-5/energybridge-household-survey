// EnergyPlus 24.1 wet-bulb numerical repair *candidate*.
// Pure numerical helper: no EnergyPlus state, psychrometric cache, or I/O.
#ifndef EB_WETBULB_BOUNDED_FALLBACK_HH
#define EB_WETBULB_BOUNDED_FALLBACK_HH

#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>

#if defined(EP_nocache_Psychrometrics) || defined(EP_IF97)
#error This candidate is valid only for the locked v24.1 cached Hyland-Wexler psychrometric build.
#endif

namespace EnergyPlus::Psychrometrics::WetBulbBoundedFallback {

enum class Status { Unique, NoRoot, MultipleRoots, InvalidInput, Supersaturated, NonMonotone, ResidualFailure };

inline char const *statusName(Status status)
{
    switch (status) {
    case Status::Unique: return "unique";
    case Status::NoRoot: return "no_root";
    case Status::MultipleRoots: return "multiple_roots";
    case Status::InvalidInput: return "invalid_input";
    case Status::Supersaturated: return "supersaturated";
    case Status::NonMonotone: return "nonmonotone";
    case Status::ResidualFailure: return "residual_failure";
    }
    return "unknown";
}

struct Result {
    Status status{Status::InvalidInput};
    int roots{0};
    double rootC{std::numeric_limits<double>::quiet_NaN()};
    double residual{std::numeric_limits<double>::quiet_NaN()};
};

// The v24.1 PsyPsatFnTemp cache retains 24 mantissa bits (Grid_Shift=28).
inline double psatQuantize(double value)
{
    static_assert(sizeof(double) == sizeof(std::uint64_t));
    std::uint64_t bits;
    std::memcpy(&bits, &value, sizeof(bits));
    bits &= ~((std::uint64_t{1} << 28) - 1);
    std::memcpy(&value, &bits, sizeof(value));
    return value;
}

inline double saturationPressure(double temperatureC)
{
    double const k = psatQuantize(temperatureC) + 273.15;
    if (k < 173.15) return 0.001405102123874164;
    if (k < 273.16) {
        return std::exp(-5674.5359 / k + 6.3925247 +
                        k * (-0.009677843 + k * (0.00000062215701 + k *
                        (0.0000000020747825 - 0.0000000000009484024 * k))) + 4.1635019 * std::log(k));
    }
    if (k <= 473.15) {
        return std::exp(-5800.2206 / k + 1.3914993 +
                        k * (-0.048640239 + k * (0.000041764768 - 0.000000014452093 * k)) + 6.5459673 * std::log(k));
    }
    return 1555073.745636215;
}

inline double humidityResidual(double tdbC, double targetW, double pressurePa, double twbC, bool iceBranch)
{
    double const ps = saturationPressure(twbC);
    if (!(ps > 0.0 && ps < pressurePa)) return std::numeric_limits<double>::quiet_NaN();
    double const ws = 0.62198 * ps / (pressurePa - ps);
    double calculatedW;
    if (iceBranch) {
        calculatedW = ((2830.0 - 0.24 * twbC) * ws - 1.006 * (tdbC - twbC)) /
                      (2830.0 + 1.86 * tdbC - 2.1 * twbC);
    } else {
        calculatedW = ((2501.0 - 2.326 * twbC) * ws - 1.006 * (tdbC - twbC)) /
                      (2501.0 + 1.86 * tdbC - 4.186 * twbC);
    }
    return calculatedW - targetW;
}

// Only an erroneous actual return can be replaced. An iteration-count warning
// alone is insufficient: the old return may already satisfy the equation.
// The caller handles the pre-existing dry-bulb clip separately.
inline bool shouldAttempt(int iterations, int icvg, double returnedHumidityResidual)
{
    return (iterations > 100 || icvg == 1) &&
           (!std::isfinite(returnedHumidityResidual) || std::abs(returnedHumidityResidual) > 1.0e-8);
}

inline Result solve(double tdbC, double w, double pressurePa)
{
    Result result;
    if (!std::isfinite(tdbC) || !std::isfinite(w) || !std::isfinite(pressurePa) ||
        !(tdbC > -99.0 && tdbC < 90.0 && w >= 0.0 && pressurePa > 0.0)) {
        return result;
    }
    double const dryPs = saturationPressure(tdbC);
    if (!(dryPs > 0.0 && dryPs < pressurePa)) return result;
    double const dryWs = 0.62198 * dryPs / (pressurePa - dryPs);
    if (w > dryWs + 1.0e-10) {
        result.status = Status::Supersaturated;
        return result;
    }

    auto scanBranch = [&](double low, double high, bool ice) -> bool {
        if (!(low <= high)) return false;
        auto f = [&](double x) { return humidityResidual(tdbC, w, pressurePa, x, ice); };
        double fLow = f(low);
        double fHigh = f(high);
        if (!std::isfinite(fLow) || !std::isfinite(fHigh)) return false;
        double previous = fLow;
        for (int i = 1; i <= 128; ++i) {
            double const current = f(low + (high - low) * double(i) / 128.0);
            if (!std::isfinite(current) || current + 1.0e-10 < previous) {
                result.status = Status::NonMonotone;
                return false;
            }
            previous = current;
        }
        if (!(fLow <= 0.0 && fHigh >= 0.0)) return true;
        for (int i = 0; i < 80 && high - low > 1.0e-7; ++i) {
            double const middle = (low + high) / 2.0;
            if (f(middle) > 0.0) {
                high = middle;
            } else {
                low = middle;
            }
        }
        double const root = (low + high) / 2.0;
        double const residual = f(root);
        if (!std::isfinite(residual) || std::abs(residual) > 1.0e-8) {
            result.status = Status::ResidualFailure;
            return false;
        }
        ++result.roots;
        if (result.roots == 1) {
            result.rootC = root;
            result.residual = residual;
        }
        return true;
    };

    double const iceHigh = tdbC < 0.0 ? tdbC : std::nextafter(0.0, -1.0);
    if (!scanBranch(-99.0, iceHigh, true)) return result;
    if (tdbC >= 0.0 && !scanBranch(0.0, tdbC, false)) return result;
    result.status = result.roots == 1 ? Status::Unique : (result.roots > 1 ? Status::MultipleRoots : Status::NoRoot);
    return result;
}

} // namespace EnergyPlus::Psychrometrics::WetBulbBoundedFallback
#endif
