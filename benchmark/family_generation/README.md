# 家庭生成与上下游连接 v1

本模块将**有来源说明的联合家庭参考条件 → EB角色配额 → 成员、关系、住房/设备与权限契约 → 同源子集 → 住房绑定 → 生活需求及A**组成公开、可复现的路径。输入规模由配置决定，不读取原1000户、旧运行目录、调查答案或B结果，也不启动EnergyPlus。

**现有50户/1000户、角色、A/B、仿真、费用和线上版本均未迁移。1000户仿真继续暂停。** 新入口与公开样例是独立方法版本，不替换旧数据及其封存源码。

## 为什么需要新入口

旧`household_master.py`是历史1000户的重建入口，依赖授权输入、旧世界及环境目录。其源码公开不等于外部读者能独立生成新家庭。本次保留旧版本身份，另提供无历史路径依赖的入口，并修正成员逐ID核对、完整输入绑定、缓存产物完整性及共享住户身份连接等问题。详见[审查记录](REVIEW.md)。

## 公开复现

基础生成只需Python标准库；代码内部复用已公开的[EB配额算法](../household_archetypes/ALLOCATION.md)。

```bash
python -B -m benchmark.family_generation generate \
  --input benchmark/family_generation/examples/batch.json --out /tmp/family-demo
python -B -m benchmark.family_generation verify /tmp/family-demo
python -B -m unittest benchmark.family_generation.test_generation -v
```

安装住房模块的固定依赖后，可直接连接住房与生活A，仍不运行EP：

```bash
python -m pip install -r benchmark/housing_simulation/requirements.txt
python -B -m benchmark.family_generation connect \
  --families /tmp/family-demo --out /tmp/family-connected
python -B -m benchmark.family_generation verify /tmp/family-connected
python -B -m unittest benchmark.family_generation.test_connection -v
```

输出保存完整请求名额、逐户结果、源输入/代码哈希、未满足原因及同源子集。目录必须新建；不信任旧`passed`缓存、不覆盖原产物。`connect`调用正式住房装配和生活生成实现，不伪造空间可行或A已完成。

## 方法与输入边界

- 从**完整联合记录/参考情境池**抽取整户，保留成员组合与年龄，不独立乱抽父母子女，不改年龄凑角色。当前选择规则为固定种子的情境池有放回选择，不能称为人口加权合成。
- 分字段登记人口/关系、住房、设备、权限和生活安排的来源。`unknown`职业、收入和实际偏好保留未知；声明的通勤或生活场景不改写为调查职业。
- 六类作为实验条件；配额参考EB被分配角色的584人构成，使用最大余数法。新构造结果与当前原比例1000户分开管理。
- 每个目标家庭有空调及4—6类设备。只计算目标家庭有使用权的设备，邻户设备不替目标凑覆盖。EV出行和照护需要明确背景，不由年龄或设备拥有自动推断。
- 每个常住者有床位、家庭归属与完整生活日历；共享住户名册和权限保留。操作权与实际偏好分别处理，不因“在家”补授权。缺少成年决策人/支持契约、未知关系细分或不受支持的安装条件会留下失败原因。
- 每日设备使用、生活时间变化、A/B选择与物理状态仍属于下游实验规则；设备存在不自动创造空洗、额外出行、帮手或压缩机负荷。

公开池为**六种明确声明的合成情境**，用于验证代码和接口；不代表真实人口、不证明1000户多样性或六类人群份额。若载入授权联合数据，需要先按[输入说明](INPUTS.md)形成带来源的规范记录。本模块不提供第三方个体调查原件，也不声称仅靠公开六条示例复现了历史1000户人口抽样。

## 当前审查与结果

历史1000户只读结构核查未见人数、ID、代际数、房间归属和设备登记错位，但保留110户多空调房间兼容提示、4户关系年龄细分复核提示，以及16户非同住监护支持边界；这些不被写成全部通过。[历史复核](LEGACY_REVIEW.json)只给合成家庭标识、汇总与问题代码，没有原调查个人答卷。

新模块20项测试通过，六类公开示例6/6接通住房及生活A；反例测试、独立生成、住房/生活A连接和字节复现结果见[VALIDATION.json](VALIDATION.json)。该验证不替代1000户物理验收、真实生活校准或真人偏好验证。

[方法与论文表述](METHOD.md) · [输入与字段](INPUTS.md) · [来源/规则](SOURCES.json) · [审查与修正](REVIEW.md) · [模块许可](LICENSE) · [内容锁](PACKAGE_MANIFEST.json)
