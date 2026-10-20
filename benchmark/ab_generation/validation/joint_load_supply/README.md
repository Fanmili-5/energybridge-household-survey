# 本轮可公开证据

`LARCO_KUBO2_COTTON40.csv` 是公开数据v6 [DOI10.5281/zenodo.19666168](https://zenodo.org/records/19666168) 的8条实验室记录，限定KUBO-2、cotton、40℃，保留两种环境温度下所有公开载量点，仅选取本模型所需字段。署名：Žygimantas Jasiūnas、João Braz Ferreira、Tiago Julião、José Cecílio、Guilherme Carrilho da Graça、Pedro M. Ferreira，2026。原数据描述论文：[DOI10.1038/s41597-026-07361-6](https://doi.org/10.1038/s41597-026-07361-6)。数据及本CSV衍生部分遵循[CC BY4.0](https://creativecommons.org/licenses/by/4.0/)，不改变其再使用权；作者不为本实验背书。

修改包括行/字段选择、以目标载量构造相对曲线、以本实验设备功率及参考时长重新定标。绝对尺度及烘干曲线不是该数据的实测结论。未发布家庭记录、音频或天气数据。`LARCO_SOURCE.json` 保存版本、筛选条件及已抽取成员校验；ZIP全包MD5仅为仓库发布值，不声称完整下载校验。

`derive_load_curve.py` 由16℃4条记录派生形状，以32℃4条记录展示环境迁移误差。`LOAD_SHAPE.json` 是固定数据运算回执，不是家庭校准。其余本轮结果在固定8情境运行后发布；失败、缺机会和覆盖缺额均计入分母。运行入口及方法见[JOINT_LOAD_SUPPLY.md](../../docs/history/JOINT_LOAD_SUPPLY.md)。
