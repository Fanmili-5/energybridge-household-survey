# 来源、输入与再分发范围

| 输入 | 身份与用途 | 准备方式/不据此推断 |
|---|---|---|
| 七普2020城市普通住宅表 | 人口、人数矩、代数、面积与自然间控制 | 引自[国家统计局七普年鉴](https://www.stats.gov.cn/sj/pcsj/rkpc/7rp/zk/indexch.htm)；按表标题/注释/原hash核口径，不将省级边际当逐户联合事实 |
| CHFS2021实际访次 | 同住代理、关系/性别/粗年龄及部分经济组联合参考 | 用户自行取得适用许可的原件，按`chfs_admission_20261003`/`chfs_census_bridge_20261003`接口准备；经济名单不等于常住名单，不发布源户ID/金额/名册 |
| CRECS2012 | 部分历史城市设备/频次/时长参考 | 按`crecs_admission_20261003`审核原字段；不能当当代拥有率或完整同户分钟日记 |
| 中国住宅原型/几何与天气 | 围护、功能空间和参考气候 | 原件/派生IDF、EPW留在合法研究环境；目录数量不是人群频率，参考年代不是实际竣工年 |
| 锁定EB版本 | 功能设备程序、原生控制与IDF | 原仓库资源脚本和原版本锁；不把厂家外形尺寸当完整运行性能 |
| EnergyPlus24.1与模型schema | 编译和数值仿真 | 学校已配置的引擎；数值/输入检查不等于人类舒适或住宅实测校准 |
| 冻结上游研究包 | 世界、日期、程序、参数、绑定/回读的同版本输入 | 对当前链是受控输入；提供hash及接口，不在此源码同步中公开全部逐户原件 |
| 真人回答 | 指定演员×角色×情境的回应 | 当前0；招募/收集/预算/切分另行落实，工程样例不能充当人类标签 |

学校准备好的工作区保持 `docs/research/collection-adjustment-20260930/household1000/` 布局。每阶段输入可能包括 `RUNTIME.json`、`raw/`、`inputs/`、`worlds/`、`actors/`、`pairs/`、`idfs/`、`runs/` 与绑定清单。源码import可以读取前置阶段，因此不能只复制五个V17脚本就执行。

关键现行受控输入：

- V16：`WORLD_BINDINGS1000.json`、`PAIR_BINDINGS10000.json`、世界/角色、参数目录、背景IDF和上游模型。
- V17全量：`SELECTION1000.json`、1000世界/角色、10000配对及IDF输入。
- V17原50户：`SELECTION50.json`、`EXECUTION_AUTHORIZATION.json`、相应输入与`CURRENT_EP_RESULTS.json`、`READBACK_REVIEW.json`/结果。
- 前端：公开去案例模板，加上述50户同版本资料与后果；公开模板的六段内嵌JSON为空，不能误当完整案例bank。

源码以原字节记录在`SOURCE_SNAPSHOT.json`，仅模板HTML移除内嵌案例；调查、第三方模型/天气、SQL、私有研究原件、联系人、会话、答卷和密钥未进入本次载荷。原件可取得不自动意味着可以整体再分发，输入hash也不是再分发许可。

统计与几何源码用到NumPy/Pandas/SciPy及阶段声明的解析/几何依赖。原几何环境记录过Python3.14.3、Shapely2.1.2、SciPy1.17.1、Pandas3.0.3、NumPy2.5.2和access-parser特定提交；学校当前原生执行使用Python3.10.12、EnergyPlus24.1和已有Node20运行时。这里记录来源环境，不声称所有历史诊断在同一Python环境已验证。新只读统一入口仅依赖标准库。
