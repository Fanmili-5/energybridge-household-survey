# 独立EnergyPlus24.1有界湿球数值修复

[方法、证据与适用边界](../../PHYSICS_REPAIR_PRODUCTION.md)。补丁改变真实返回/缓存路径；必须保留原警告、APPLIED、UNRESOLVED和原有边界裁剪记录，不能仅以进程退出码判定可靠。

源码起点为官方24.1.0-9d7789a3ac，cached Hyland–Wexler构建。`energyplus_v24_1_twb_repair_candidate.patch`包含新增头文件；从官方源码根目录以`patch -p1`应用。完整构建与原生实验在独立计算环境执行，GitHub不重跑批量实验。

纯C++检查（无需EnergyPlus运行）：

```sh
c++ -std=c++17 -Wall -Wextra -Werror -I repair_overlay/src repair_overlay/tests/check_wetbulb_bounded.cc -o /tmp/check_wetbulb_bounded
/tmp/check_wetbulb_bounded
```

[EnergyPlus原许可](../../../housing_simulation/resources/ENERGYPLUS_LICENSE.txt)继续适用于其源代码、公式实现及补丁涉及的原文。此目录不重新许可第三方软件或数据。未发布计算服务器二进制、家庭输入或SQL；执行文件、动态库、IDD和补丁的指纹随数值复核器和运行凭据绑定。
