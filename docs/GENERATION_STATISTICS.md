# 家庭与A/B聚合统计

本页由静态命令从冻结家庭、实际选中计划及覆盖台账重新计算；不运行仿真。

| 指标 | 数量 |
|---|---:|
| 家庭 / 配对题 | 1000 / 10000 |
| 源户组 / 构造组 | 1000 / 875 |
| C/D配对组 | 125 |
| 声明 / 已选根动作格 | 939 / 939 |
| 至少两国 / 单国根动作格 | 924 / 15 |
| 受控家庭×功能 / 已选变化 | 5001 / 4990 |
| 每根格题数：最小 / 中位数 / P90 / 最大 | 1 / 7 / 34 / 844 |

覆盖出现不代表频数均衡或足够统计功效；以下控制组合与事件均为实验配置。

## 国家与角色

| 国家 | A | B | C | D | E | F | 合计 |
|---|---:|---:|---:|---:|---:|---:|---:|
| AU | 21 | 24 | 16 | 19 | 20 | 25 | 125 |
| CN | 21 | 25 | 15 | 19 | 20 | 25 | 125 |
| DE | 21 | 24 | 16 | 19 | 19 | 26 | 125 |
| ES | 20 | 25 | 16 | 19 | 20 | 25 | 125 |
| GB | 21 | 25 | 15 | 19 | 20 | 25 | 125 |
| IN | 21 | 25 | 15 | 19 | 19 | 26 | 125 |
| MX | 20 | 25 | 16 | 19 | 19 | 26 | 125 |
| US | 21 | 25 | 16 | 18 | 19 | 26 | 125 |

## 核心字段来源

每项按家庭计数，避免把成员数不同造成的字段数量误当成补全比例。

| 国家 | 精确周日程 | 舒适参数 | 参考面积 | 空调存在状态 |
|---|---|---|---|---|
| AU | benchmark_assigned: 125 | benchmark_assigned: 125 | benchmark_assigned: 125 | benchmark_installed: 4, observed: 121 |
| CN | benchmark_assigned: 125 | benchmark_assigned: 125 | benchmark_assigned: 125 | observed: 125 |
| DE | benchmark_assigned: 125 | benchmark_assigned: 125 | benchmark_assigned: 125 | benchmark_installed: 121, observed: 4 |
| ES | benchmark_assigned: 125 | benchmark_assigned: 125 | benchmark_assigned: 125 | benchmark_installed: 59, observed: 66 |
| GB | benchmark_assigned: 125 | benchmark_assigned: 125 | benchmark_assigned: 125 | benchmark_installed: 110, observed: 15 |
| IN | benchmark_assigned: 125 | benchmark_assigned: 125 | benchmark_assigned: 125 | observed: 125 |
| MX | benchmark_assigned: 125 | benchmark_assigned: 125 | benchmark_assigned: 125 | observed: 125 |
| US | benchmark_assigned: 125 | benchmark_assigned: 125 | derived: 125 | benchmark_installed: 17, observed: 108 |

## 根动作覆盖的定义

一个格由角色、功能、根动作机制、方向和分离的幅度轴构成；仅统计直接事件请求。启动时移/许可时长按0、(0,30]、(30,60]、(60,120]、>120分钟报告；温度差与事件前/中准备轴分开，不把不同轴合成居民负担等级。

格定义见[record_raw_cells](../benchmark/ab_generation/generate_native.py)及[动作轴规则](../benchmark/ab_generation/unified/ACTION_AXIS_RULES.json)。939是当前候选域中有见证的根动作格，不是全部连续动作或全部二元/高阶交互组合。

| 角色 | AC | WM | DR | DW | WH | EV |
|---|---|---|---|---|---|---|
| 记法 | 已选/声明（至少两国） | 同左 | 同左 | 同左 | 同左 | 同左 |
| A | 96/96 (96) | 8/8 (8) | 3/3 (3) | 5/5 (5) | 41/41 (41) | 4/4 (4) |
| B | 96/96 (96) | 1/1 (1) | 1/1 (1) | 5/5 (5) | 41/41 (41) | 3/3 (3) |
| C | 96/96 (96) | 8/8 (8) | 3/3 (3) | 5/5 (5) | 41/41 (41) | 4/4 (4) |
| D | 96/96 (96) | 4/4 (3) | 4/4 (3) | 5/5 (5) | 41/41 (41) | 4/4 (3) |
| E | 96/96 (96) | 1/1 (1) | 1/1 (1) | 5/5 (5) | 41/41 (41) | 3/3 (3) |
| F | 96/96 (96) | 8/8 (8) | 3/3 (3) | 5/5 (5) | 61/61 (49) | 4/4 (4) |

## 事件分布

| 起止分钟 | 题数 |
|---|---:|
| [1000,1060] | 3 |
| [1030,1090] | 1 |
| [1040,1100] | 10 |
| [1080,1140] | 9955 |
| [1100,1160] | 1 |
| [1140,1200] | 1 |
| [1170,1230] | 2 |
| [1190,1250] | 1 |
| [1200,1260] | 2 |
| [960,1020] | 12 |
| [970,1030] | 8 |
| [980,1040] | 1 |
| [990,1050] | 3 |

## 计划变化

| 改变的功能组合 | 题数 |
|---|---:|
| AC | 1250 |
| AC+DR | 265 |
| AC+DR+DW | 155 |
| AC+DR+DW+EV | 74 |
| AC+DR+DW+EV+WH | 243 |
| AC+DR+DW+EV+WH+WM | 192 |
| AC+DR+DW+EV+WM | 43 |
| AC+DR+DW+WH | 235 |
| AC+DR+DW+WH+WM | 150 |
| AC+DR+DW+WM | 77 |
| AC+DR+EV | 33 |
| AC+DR+EV+WH | 69 |
| AC+DR+EV+WH+WM | 20 |
| AC+DR+EV+WM | 26 |
| AC+DR+WH | 104 |
| AC+DR+WH+WM | 31 |
| AC+DR+WM | 92 |
| AC+DW | 397 |
| AC+DW+EV | 76 |
| AC+DW+EV+WH | 105 |
| AC+DW+EV+WH+WM | 91 |
| AC+DW+EV+WM | 56 |
| AC+DW+WH | 165 |
| AC+DW+WH+WM | 125 |
| AC+DW+WM | 78 |
| AC+EV | 196 |
| AC+EV+WH | 80 |
| AC+EV+WH+WM | 46 |
| AC+EV+WM | 41 |
| AC+WH | 217 |
| AC+WH+WM | 88 |
| AC+WM | 158 |
| DR | 653 |
| DR+DW | 174 |
| DR+DW+EV | 21 |
| DR+DW+EV+WH | 50 |
| DR+DW+EV+WH+WM | 2 |
| DR+DW+EV+WM | 4 |
| DR+DW+WH | 75 |
| DR+DW+WH+WM | 4 |
| DR+DW+WM | 16 |
| DR+EV | 39 |
| DR+EV+WH | 30 |
| DR+EV+WH+WM | 1 |
| DR+EV+WM | 9 |
| DR+WH | 129 |
| DR+WH+WM | 33 |
| DR+WM | 464 |
| DW | 786 |
| DW+EV | 60 |
| DW+EV+WH | 50 |
| DW+EV+WH+WM | 23 |
| DW+EV+WM | 24 |
| DW+WH | 172 |
| DW+WH+WM | 37 |
| DW+WM | 87 |
| EV | 456 |
| EV+WH | 112 |
| EV+WH+WM | 20 |
| EV+WM | 134 |
| WH | 730 |
| WH+WM | 97 |
| WM | 530 |

## 分组与解释

原生程序变化仍保持完整任务；下表组合计数只说明选中候选改变哪些功能，不代表人类偏好类别或物理收益。

同一源户、同一家庭全部题目及C/D配对放入同一构造组。当前未分配训练/验证/测试集；有答卷后还需处理重复参与者关联。875等构造组计数不证明统计独立。

未入选的家庭×功能计数：{"EV": 2, "WM": 9}。这些数量本身不证明无机会，须结合独立的冻结域证明。

根动作格是有限离散子域覆盖；完整组合、连续参数、自然性和真人偏好有效性另行评估。名义用电变化不是仿真结果，未知热响应不记作零。

完整的分层频数、时移方向、来源状态和输入指纹见[机器可读统计](GENERATION_STATISTICS.json)。
