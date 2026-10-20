#include <EnergyPlus/WetBulbBoundedFallback.hh>

#include <cassert>
#include <cmath>
#include <limits>
#include <string_view>

using namespace EnergyPlus::Psychrometrics::WetBulbBoundedFallback;

int main()
{
    assert(shouldAttempt(101, 0, 2.7256977204649256e-5));
    assert(shouldAttempt(101, 0, 0.00030148240882957094));
    assert(!shouldAttempt(101, 0, 1.0e-12)); // A warning with an accurate actual return stays unchanged.
    assert(shouldAttempt(18, 1, -4.2176784313572527e-6));
    assert(!shouldAttempt(9, 1, -1.5444691966320923e-12));
    assert(!shouldAttempt(7, 1, 4.8702925373178552e-13)); // 0093 14:20: valid old water root despite second mathematical root.
    assert(shouldAttempt(7, 1, std::numeric_limits<double>::quiet_NaN()));
    assert(statusName(Status::MultipleRoots) == std::string_view("multiple_roots"));

    auto a = solve(5.0601730346679688, 0.0017073890194296837, 101960.0);
    assert(a.status == Status::Unique && a.roots == 1 && std::abs(a.rootC + 0.36024474538862705) < 2.0e-5);
    assert(std::abs(a.residual) < 1.0e-8);
    assert(shouldAttempt(101, 0, humidityResidual(5.0601730346679688, 0.0017073890194296837,
                                                  101960.0, 0.037781708993608921, false)));

    auto b = solve(6.4530715942382812, 0.0011623585596680641, 101460.0);
    assert(b.status == Status::Unique && b.roots == 1 && std::abs(b.rootC + 0.4647389519959688) < 2.0e-5);
    assert(std::abs(b.residual) < 1.0e-8);
    assert(shouldAttempt(101, 0, humidityResidual(6.4530715942382812, 0.0011623585596680641,
                                                  101460.0, -0.0079135674930914442, true)));

    auto c = solve(6.5, 0.0011226590722799301, 102090.0);
    assert(c.status == Status::Unique && c.roots == 1 && std::abs(c.rootC + 0.46573677100241184) < 2.0e-5);
    assert(std::abs(c.residual) < 1.0e-8);
    assert(std::abs(humidityResidual(6.5, 0.0011226590722799301, 102090.0,
                                     0.0014358116451059747, false) - 4.217678431357253e-6) < 1.0e-10);
    assert(shouldAttempt(18, 1, humidityResidual(6.5, 0.0011226590722799301,
                                                 102090.0, 0.0014358116451059747, false)));

    auto normal = solve(6.1999969482421875, 0.0011576050892472267, 102090.0);
    assert(normal.status == Status::Unique && std::abs(normal.rootC + 0.575416861101985) < 2.0e-5);
    assert(std::abs(humidityResidual(6.1999969482421875, 0.0011576050892472267, 102090.0,
                                     -0.57541686149122806, true)) < 1.0e-8);
    assert(!shouldAttempt(9, 1, humidityResidual(6.1999969482421875, 0.0011576050892472267,
                                                 102090.0, -0.57541686149122806, true)));

    auto dual = solve(6.7999992370605469, 0.0010856939479708672, 102090.0);
    assert(dual.status == Status::MultipleRoots && dual.roots == 2);
    assert(std::abs(humidityResidual(6.7999992370605469, 0.0010856939479708672, 102090.0,
                                     0.11872687444222484, false)) < 1.0e-8);
    assert(!shouldAttempt(7, 1, humidityResidual(6.7999992370605469, 0.0010856939479708672,
                                                 102090.0, 0.11872687444222484, false)));

    auto invalid = solve(std::numeric_limits<double>::quiet_NaN(), 0.001, 101325.0);
    assert(invalid.status == Status::InvalidInput);
    auto saturated = solve(6.5, 0.1, 102090.0);
    assert(saturated.status == Status::Supersaturated);
}
