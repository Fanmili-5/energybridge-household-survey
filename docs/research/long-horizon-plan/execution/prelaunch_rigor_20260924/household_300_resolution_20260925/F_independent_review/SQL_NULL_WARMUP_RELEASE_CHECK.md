# EnergyPlus SQL 空暖机标志：两个精确代码改动的发布核验

`realtime_pilot/native_assets.py` 与 `realtime_pilot/paired_ep.py` 的待发布差异各只有 SQL 条件一行：`t.WarmupFlag=0` → `COALESCE(t.WarmupFlag,0)=0`。其余改动不在这两个文件。当前 `realtime_pilot/test_energyplus_sql_null_warmup.py` 的本地回归通过，证明 `NULL` 普通行保留。

F 另用本机临时 SQLite 分别给两个真实读取器输入三个同日小时点：`WarmupFlag=NULL` 且值 25、`WarmupFlag=1` 且值 99、`WarmupFlag=0` 且值 26。两读取器都只返回 25 与 26，恰好 2 点，暖机值 99 被排除。隔离发布副本测试也包含同一反例。

D 第三版真实 `cityrole-0004__semantic_regression/eplusout.sql` 的 `Time` 含 1,440 个十分钟非暖机点和 240 个小时点；两个读取器按十天、240 小时视窗各读出 3 个报表键，每键恰好 1,440 个十分钟样本。该真实探针中 `WarmupFlag=0`，是实际步数与输出键检查；`NULL` 由受控 SQLite 反例证明。此改动只作用于 SQL 读取，不改 D/G 既有 IDF 或数值文件。
