# 连续时段端点与 EV 凌晨记录核对

> 历史记录，保留当时的测试结果和设计依据。项目使用说明见[文档目录](README.md)。

界面只标连续时段的起止，温度/功率变化不重复标时刻，中间停机仍保留断开。原温度分段与原始坐标不变。去掉重复的读图说明，空调/热水器标题直接标“温度设定”。

EV 展示示例来源为 artifacts/overnight_20260914/pair-valid.json；对应原生记录 summer/appliance_clock.json。家庭配置 arrival_h=22、departure_h=8、target_soc=0.8、capacity_kwh=60、daily_drive_kwh=25。未提供 initial_soc，当前固定版本 EVCharger 按 target_soc - daily_drive_kwh / capacity_kwh 初始化为 0.383333。

_is_home 对跨夜窗口允许 hod >= 22 或 hod < 8。因此第一天凌晨在家且电量不足，会充电。保存记录首个 EV 步为 00:10，功率 7.4kW；使用示例完整 EV 配置执行单步复现一致。它是模型起始状态假设，不是参与者填报的首日凌晨充电，也不是已经验证的前一晚运行轨迹。未将这段移到次日或删除，未修改原生执行。

Node 检查连续时段只标两端、温度分段仍保留、停机间隔不合并、两段 EV 充电不跨日挪动。此次未运行 EP 或付费模型。
