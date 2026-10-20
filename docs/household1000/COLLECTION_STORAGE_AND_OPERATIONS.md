# 正式采集的存储、导出与维护

当前正式入口：https://47.85.194.154/household50-current/ 。使用UI91立体房间与50户500题完整配对后果；当前发布签名、上线记录与后续维护状态分别见[MANIFEST](../../benchmark/releases/reference50-v4-ui91-complete/MANIFEST.json)、[ACTIVATION](../../benchmark/releases/reference50-v4-ui91-complete/ACTIVATION.json)和[OPERATIONS](../../benchmark/releases/reference50-v4-ui91-complete/OPERATIONS.json)。上线时保留旧库是历史事实；此后用户明确要求清除退役采集记录，维护状态已更新，不能把历史上线回执当作当前保留策略。

## 保存位置与完整信息

正式数据库在服务器的新40GiB数据盘`/dev/vdb1`，ext4挂载于`/srv/energybridge-data`。2026-10-20已先备份再迁移；只有`/dev/vdb`执行分区和格式化，系统盘未分区、格式化或扩容。实际数据库路径：

```text
/srv/energybridge-data/collections/current50/collection_ui91_physics/e9f4e541e35558b7dae3/formal_responses.sqlite3
```

原路径通过bind mount指向同一份新盘数据，现有服务命令、浏览器cookie、身份和恢复码不变：

```text
/var/lib/energybridge-current50/collection_ui91_physics/e9f4e541e35558b7dae3/formal_responses.sqlite3
```

这是SQLite数据库。`responses_v69.record_json`保存版本绑定的完整提交，修改追加新修订、保留历史；重试使用同一提交标识，不重复产生答案。草稿、查看历史、匿名身份、多轮分配和同意/撤回另表保存，未提交草稿不计作正式答卷。页面显示提交回执才表示提交已确认；断网未同步内容仍可能只在浏览器，不能当作服务器已收到。

每份提交包含：匿名`participant_id`、本轮`assignment_id`与轮次、家庭与日期、四项评分、接受/拒绝、原因、提交时间/回执/修订、所见文本和完整排程是否展开、问卷/案例/家庭/资源的版本哈希，以及独立的客观仿真结果。冻结的完整家庭、住房、设备、A/B与后果题包位于：

```text
/opt/energybridge-current50/e9f4e541e35558b7dae3/release
```

题包与程序同样已迁至新盘，实际在`/srv/energybridge-data/programs/current50`；`/opt/energybridge-current50`通过bind mount保持兼容。备份应覆盖数据库及同目录的`credential_pepper`，题包另以冻结签名关联保存。

答卷通过`case_id`和哈希关联完整题包，不能只导出分数后丢掉题包。角色模型的`input`只包含所见信息；未展开的完整排程不补进该输入。后台客观结果与所见输入分别保存，避免把隐藏结果混入角色判断。当前题包133MB左右，包含500个冻结案例；不在问卷服务器上临时跑EnergyPlus。

## 导出

授权管理员在服务器使用匹配运行时导出UTF-8 JSONL，每行一题、一名匿名参与者的一轮最新提交：

```bash
/usr/bin/python3 -B /opt/energybridge-current50/e9f4e541e35558b7dae3/runtime/admin.py export \
  --release /opt/energybridge-current50/e9f4e541e35558b7dae3/release \
  --data-root /var/lib/energybridge-current50/collection_ui91_physics/e9f4e541e35558b7dae3 \
  --quality all --output /private/approved-export/answers-YYYYMMDD.jsonl
```

输出目录由管理员事先创建并限制权限，文件必须是新路径；不要直接复制命令中的占位目录。`all`保留未复核状态，`valid`只包含当前修订已人工复核有效且未撤回的答案；两者均排除工程fixture。原始修订仍在数据库内，常规JSONL取最新修订，不能把修订重复计数。CSV如需用于表格分析，应从JSONL另生成扁平副本，SQLite、JSONL及冻结题包保留为原始依据。同一参与者的多轮要按`participant_id`关联，轮次数不能当作独立人数。

数据库、恢复材料、答卷JSONL和私有备份不进入GitHub，也不通过公开网页提供。GitHub只保留代码、格式、来源和脱敏验收记录。

## 请求体与服务器验收

2026-10-20检查发现当前路径继承Nginx的32KB限制，而应用允许256KB。500题中，完整排程加4000字符原因在最坏JSON转义下最大40,546字节；该合法边界会被旧代理拦截为413。已仅对`/household50-current`显式设为256KB，其他入口配置不变，Nginx平滑重载，正式采集进程未重启。部署脚本现在会发送不带身份、无答卷字段的256KB探针，要求请求抵达应用会话拒绝；413、意外成功或非采集器拒绝都不能算发布通过。

服务器临时隔离库的实际HTTP检查通过：4000字原因及全部评分/选择原样保存，完整展开排程与家庭/A/B/物理版本绑定保留，JSONL读回一致，SQLite备份恢复逐字节一致，8次同时重试只保留1份提交。该被测提交JSON约180KB、首提交约20毫秒；这些是本次小规模测试值，不是所有题目的最大存储量或大规模吞吐保证。公网256KB体积验收通过；未向正式库写测试答案。新盘迁移后可用约40.45GB（37.67GiB），系统盘约8.87GB；这是验收时刻的余量，未来1000户的内存、题包体积和并发仍须单独验收。

## 新盘挂载与故障保护

`/etc/fstab`按文件系统UUID挂载新盘，并绑定原数据和程序目录。正式服务和备份服务都有`RequiresMountsFor`、`BindsTo`与`After`依赖；新盘离线时不会继续在系统盘生成另一套空数据库。原bind目标的底层空目录权限为000，另由外部[启动守卫](../../deploy/verify_reference50_data_mount.py)核对实际设备UUID、三个真实挂载点、bind目录身份、现有数据库、32字节恢复材料与发布签名。守卫位于`/usr/local/lib/energybridge-current50/verify_data_mount.py`，布局在`/etc/energybridge-current50/storage-layout.json`，不改冻结采集运行时或题包。

已以实际服务账号核对挂载、启动正式服务及备份；故意给错UUID会拒绝启动。`findmnt --verify`、启用生成器的`systemd-analyze --generators=yes verify`及实际挂载单元均通过。服务器未重启，不能把持久配置检查称为实际重启验收。不要在线卸载新盘或直接复制旧库覆盖新库。

最终切换前1185个文件的SHA-256、权限、UID/GID一致；数据库所有表逐行摘要、结构与恢复材料一致。当时已有1个参与身份、1轮分配、2条查看记录、4个会话，正式答卷0；全部保留。新盘临时隔离库使用同一冻结运行时和500题包，通过实际HTTP填写、草稿/查看记录恢复、服务重启、原恢复码续填、追加修订、幂等提交、多轮和备份恢复。正式公网另只创建1个匿名会话，确认写入新盘，未创建测试身份或正式答案。公网UI91资源和500题签名保持一致。

正式切换前有3次配置验收触发自动回退，分别涉及挂载单元生成器、严格umask下程序目录权限、systemctl输出转义解析，均已修正并保留诊断。最后一次切换维护约10秒，不代表此前所有维护窗口之和。[脱敏迁移回执](../../benchmark/releases/reference50-v4-ui91-complete/STORAGE_MIGRATION.json)记录最终结果；私有行摘要、原目录和各次快照仅留服务器。

## 备份与旧版清理

当前正式库每6小时生成一致SQLite备份并检查完整性，同目录保留`latest.tar.gz`和`previous.tar.gz`。此路径仍在系统盘，与正式数据位于不同磁盘：

```text
/var/backups/energybridge-current50/e9f4e541e35558b7dae3/rolling
```

备份含原恢复材料；仅有数据库而丢失恢复材料，会影响恢复码续填。此次已将最终停止写入后的快照、以及重新启用的自动备份各自还原到临时目录，核对所有表、结构及恢复材料一致。迁移前快照、配置和系统盘原目录另保存在：

```text
/var/backups/energybridge-current50/storage-migration-20261020T095249Z/
```

成功迁移的最终快照在其`retry-20261020T095857Z/final-quiesced-snapshot/latest.tar.gz`，原目录在同级`system-disk-originals`。新盘还保存副本`/srv/energybridge-data/private-backups/pre-migration-20261020T095857Z/latest.tar.gz`。旧的未激活迁移副本受root专有目录保护，不是第二个运行中的库。

迁移后的fstab、服务单元及drop-in、布局文件和守卫代码也分别保存在成功迁移目录与新盘快照目录的`configuration-after`，逐文件核对一致；线上守卫代码的哈希与公开源文件一致。

恢复时应先维护并停止写入，保留当前库和恢复材料，校验目标快照的`MANIFEST.json`、SQLite及发布签名，在独立目录验证后成对恢复数据库与`credential_pepper`，保持原权限，再经挂载守卫、服务启动和公网检查后开放。不能在新库收到后续提交后直接回退到迁移前目录；系统盘原目录只是切换时刻的快照。

当前未配置自动异地备份。服务器内双盘和两代滚动快照不能抵御整机或账号故障；本次自动审批未允许将含恢复密钥的快照导出本机，故未下载。异地导出需另获授权并使用私有受控位置，不能上传GitHub。

已停止7套未被公网路由使用的旧采集服务及其旧备份定时器，7套旧程序逐文件校验后压缩归档。常用展开目录保留当前版与一个冷回退版，其他仍在使用的公网入口保留。按用户随后明确要求，删除8个退役采集数据库目录及旧备份副本，包括新版本切换前复制的旧库；旧身份、旧查看记录、旧恢复信息一并清除。当前正式库和当前备份保留。旧程序归档只作程序/题包复现，不含已删除的旧采集记录，不能用于找回已清除的旧恢复码。

后续1000户只预留空目录`/var/lib/energybridge-household1000`，未创建数据库、未部署服务、未开放入口、未启动生成或仿真。正式增加时使用独立发布、数据库、cookie路径、入口、备份和容量验收，不能混入当前50户记录。
