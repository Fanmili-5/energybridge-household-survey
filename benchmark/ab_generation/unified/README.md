# 统一生成入口 v2.10

家庭v3 → 原生活需求 → A → 固定18:00—19:00机会 → 不同取舍B → 问卷材料。
保留单设备、多设备、同类多批以及没帮助、生活冲突、待确认、名义缺额和未知。
生成器不产生接受答案、评分或回答理由，不运行物理仿真或部署。

```sh
python -m pip install -r benchmark/ab_generation/unified/requirements-lock.txt
python -B -m benchmark.ab_generation.unified build --inputs FROZEN_INPUTS.json --out NEW_OUTPUT --workers 1
```

CLI缺省读取CURRENT_CONFIG.json（v2.10）；`--config`可显式指定模式。
DEFAULT_CONFIG.json是保留的旧内部API默认，不是当前CLI推荐配置。
输入文件需包含冻结的家庭日与授权来源；大写文件名是占位符。
可实际运行的六类公开输入与命令见[复现说明](../../research_delivery/REPRODUCE.md)。

[统一方法](../../research_delivery/METHOD.md) · [设备规则](../../research_delivery/DEVICE_EXECUTION_MAP.md) ·
[精确联合任务数](../../research_delivery/JOINT_ORDER_SELECTION_METHOD.md) · [来源和实验参数](../../research_delivery/SOURCES_AND_PARAMETERS.md)。

v2.10先最大化每户已见证任务数的覆盖，再优化原覆盖/重复及种子等价解，不规定各类型配比。
任务数不是电器种类数，自动洗烘依赖不另计独立任务。无候选不等于没有机会。
预算、相对幅度分箱和优先级是实验设置，未知不能记成物理失败或成功。
旧500题及源码身份保留，本轮只是三户30日期重新选题验证，不声称完成新版500题验收。
