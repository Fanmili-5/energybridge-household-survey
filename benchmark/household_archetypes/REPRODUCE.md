# 复现、核验与公开边界

## 仅复算配额与检查发布包

在公开仓库根目录运行，标准库Python 3.10+即可；无需旧家庭、EnergyPlus、模型API或原始个人答卷：

```bash
python -B benchmark/household_archetypes/allocate.py
python -B benchmark/household_archetypes/verify.py
```

核验器检查方法包哈希、六类定义、EB源人数、精确整数化与平余数次序、拟议状态，以及归档证据与汇总的对应。它不将工程一致性检查写成人类偏好效度验证。

## 取得原始输入并核查EB人数

`INPUTS.lock.json`锁定原始公开文件的URL和SHA256，包括EB固定提交、ECA、iFlex、荷兰与eCAPE。按原站许可使用；原始文件不随本仓库再分发。下载与研究缓存均放在包外，不上传个人答卷。

```bash
python -B benchmark/household_archetypes/fetch_inputs.py \
  --output /tmp/eb-archetype-raw
python -B benchmark/household_archetypes/allocate.py \
  --participants /tmp/eb-archetype-raw/eb_participants.csv
```

下载器只读取明确列出的公开地址；原文件已存在时只核哈希。若内容变化即停止，不自动改输入锁。也可手动准备同名原件；eCAPE使用cp1252/分号编码，不能另存后还当同一哈希。输入锁不意味着可以再分发所有原始记录。

## 重放组成维度与同人共现

配额复算不需要科学计算库；原始调查重放另需`requirements-research.txt`中的库。发布记录的环境为Python 3.14.3，各库实测版本见`ENVIRONMENT.json`；其他环境不承诺逐浮点位一致。

```bash
python -m venv /tmp/eb-archetype-env
/tmp/eb-archetype-env/bin/python -m pip install \
  -r benchmark/household_archetypes/requirements-research.txt
/tmp/eb-archetype-env/bin/python -B benchmark/household_archetypes/replay_evidence.py \
  --raw-dir /tmp/eb-archetype-raw \
  --output /tmp/eb-archetype-replayed
```

脚本核原件与研究源码哈希，将冻结的研究代码复制到临时树，重新读取ECA、iFlex和荷兰原始问卷，比较两份连接汇总（相对/绝对容差`1e-10`），再输出`REPLAY.json`。不导出逐人类型或接受答案。输出目录必须是包外新目录；归档原文件、现有家庭和生产指针不写入。

eCAPE的完整拟合参数、6类聚合画像、字段分母、20轮重抽样及3项敏感性结果在`research/archive/docs/research/ecape-fixed-six_20261019/`。本次发布没有调整其字段、分类规则或选择更贴近EB的模型。

## 可选：从原始问卷重新拟合探索模型

每个命令均先重放上述连接核查，再在新目录执行对应的原冻结程序。计算可能需要数分钟；日志和与冻结数值的比较会保留。单纯验证配额不需要这些拟合。

```bash
python -B benchmark/household_archetypes/replay_evidence.py \
  --raw-dir /tmp/eb-archetype-raw --output /tmp/ecape-refit --refit ecape
python -B benchmark/household_archetypes/replay_evidence.py \
  --raw-dir /tmp/eb-archetype-raw --output /tmp/eca-refit --refit eca
python -B benchmark/household_archetypes/replay_evidence.py \
  --raw-dir /tmp/eb-archetype-raw --output /tmp/iflex-refit --refit iflex
python -B benchmark/household_archetypes/replay_evidence.py \
  --raw-dir /tmp/eb-archetype-raw --output /tmp/dutch-refit --refit dutch
```

归档有意保留原脚本的相对目录、参数、原始计划和文件哈希，包装器只解决路径隔离与输入输出管理。原研究代码的临时缓存默认路径不是公共数据依赖。原历史清单列出了更多未随本模块分发的历史文件；实际包内容以本模块`PACKAGE_MANIFEST.json`和`research/PROVENANCE.json`为准，不宣称整个旧工作区都已发布。

ECA固定六类使用官方权重，其余这里列出的分析未使用人口权重。重抽样仅属探索稳健性检查；相同代码数值可复现不代表类别是人口真值、六类效度通过或配比有代表性。

## 当前状态

本模块不创建/修改家庭、成员、设备、角色、排程、仿真、费用、问卷、采集配额或线上版本；无EnergyPlus、模型API或部署依赖。1000户仿真继续暂停。未来配比迁移和实际benchmark实验必须另有数据版本、相容性检查及人类评价证据。
