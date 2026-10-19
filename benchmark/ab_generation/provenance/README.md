# 公开来源与历史规则

`ORIGINAL_EB.json`将本次实际核对的原EB文件绑定到固定Git对象、SHA-256及永久链接。内容按本地固定对象核对，并与仓库公开的`UPSTREAM_TRACKED_FILES.json`交叉验证；没有将当前上游HEAD误当作旧提交。它提供设计依据，不授予上游代码许可。

`project_history/`补齐此前只有本地路径的六份项目生成规则原文；另外三份已有公开文件通过`SOURCES.json`中的`public_path`指向。九份原文逐字节保留，供规则沿革审查，具有历史目录耦合和不完整依赖，不能当作新生成器入口运行。当前运行只依赖公开的`benchmark/ab_generation`根目录实现及显式输入。

`REUSABLE_AB_CONTRACT.json`是此前项目设计稿的原始快照，不是当前全部功能已实现的证明。尤其其中`current A forecast`的措辞由当前`OFFLINE_EXPERIMENT.md`中的完整A离线反事实条件取代。原50户分配和1000户设计约束作为历史记录保留，本次不运行这些批次。

论文提供外部链接和已审阅版本SHA，不复制全文。项目来源公开与授予统一开源许可、实地设备控制权或参与者同意是不同事项，逐项状态见`../AUTHORIZATION.json`。
