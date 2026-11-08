# 算法：调查约束的参考家庭生成

## 输入与输出

输入为已版本锁定的调查文件或同一标准化器生成的候选池P、国家集合C、总户数N、国家配额n_c、角色配额n_r、种子s、生活规则版本L和覆盖配置K。输出每户源事实X、实验角色R、成员补全H、参考周W、控制集合F、服务合同S及来源台账；另有整批审计、分组信息和版本清单。实际问卷/仿真/标签计数均为0。

## 步骤

1. **原件归一化**：按8个固定文件SHA读取中国CRECS、美国RECS、英国/西班牙/德国ENABLE.EU、印度IRES、墨西哥ENASIC与ENIGH、澳洲ECA。按字典保留同户锚点；住房跨户匹配、调查插补和未测信息不得说成共同观测。按原有语义筛除不相容项，中国问题户保留隔离台账。
2. **确定配额**：默认国家等额；角色采用EB计数权重。最大余数：q_r=floor(N w_r/sum(w))，剩余名额按小数余数从大到小分配，相同余数按角色ID。国家×角色矩阵用整数约束保持行列边际，各格在n_c n_r/N的floor/ceil内；每国六类非空；配对时D≥C。冻结实际矩阵，不要求跨求解器重新求解相同。
3. **选源户与补参考人**：固定种子哈希排序，在角色相容性、源就业/年龄/在家/照护等限制下逐户尝试最多4个参考补全。先选C/D的同块、同设备来源签名、不同源户配对，再按E/B/A/F/D处理剩余名额；有工作证据优先用于A/F。每批源键唯一。该过程为确定性受限搜索，失败不等于全局无解，保留逐户拒绝原因。
4. **构造参考周**：保留源信息的量纲和调查范围；补匿名成员槽位、工作/通勤、上学、照护、周末、用餐、逐人洗浴和手动操作机会。角色态度由EB实验条件拷贝。具体日程不是调查原周。C为明确时间偏移与通知条件，不能声称不可预测性来自实测。
5. **分配控制功能**：每户从6种功能中选4—6种，AC必选，F的EV必选；可用组合分别为16/11种（F仅取包含AC和EV的11种）。二元x_(i,m)表示户i选组合m，sum_m x=1。整数约束实现全局、角色、国家×角色基数平衡，国家模式、角色模式、功能与非全配置二元覆盖，以及C/D同组合。目标为少增配实验设备与种子哈希破平；不使用省电、接受率或后续标签。
6. **接服务合同**：控制接入不代表任务发生。洗/烘/洗碗需真实负载与完整程序；烘干需同批洗衣、共享资产不可冲突；EV需一个停车事件和能量需求，连续补能为本实验默认；AC/热水需服务需求和温度/安全约束。未解析的前置事件阻止后续实例化。10题仅为覆盖蓝图。
7. **审计与冻结**：逐户独立原件审计、生活时间/人员、控制与服务结构核验，加整批源去重、配额、模式/功能/二元覆盖和配对检查。冻结池SHA、代码SHA、运行依赖、配置、配额矩阵、选中基线、控制分配与最终JSONL。新进程从基线重放最终JSONL逐字节相同；失败写FAILURE/SELECTION_FAILURE，不输出passed。

```text
prepare(P_raw, dictionaries, pins) -> P
quota(N, countries, role_weights) -> integer matrix Q
for country:
    pair compatible distinct C/D sources
    select remaining roles in fixed priority with hash(seed, source)
    complete profile only if source/life checks pass
freeze selected profiles and ordinals
solve control enrollment x under declared coverage K
for each selected profile:
    rebuild week for selected controls; bind service contracts
    audit raw facts, life, controls and services
independently recompute population invariants
freeze input/code/config/assignment hashes; replay final projection
```

## 默认生产覆盖

1000户4/5/6类为333/333/334；其他规模最大余数近似等分。每个角色与国家×角色格内各基数人数相差≤1。每国16种含AC合法组合均至少1户；各角色各合法组合≥2户；每格各功能≥2户。在非6类户中，各角色每功能≥20、每功能对≥10，防止全配置户独占覆盖。F只能包含EV，合法模式数随之缩为11。小样例显式降低覆盖；不得隐含降级。

## 八国范围的理由和边界

中国保留本项目研究起点；美国提供详细住宅能源调查；英国/西班牙/德国使用同一ENABLE.EU工具便于字段核对，德国另与EB柏林场景衔接；印度、墨西哥补充不同家庭/照护和能源情境；澳洲补充大洋洲能源消费者调查。选择同时受公开逐户数据可取得性与可映射字段约束，是目的性情境覆盖，不是随机全球抽样。国家等配额、角色交叉减少完全绑定，但不能证明模型不利用国家线索或外部有效性。

## 复现范围

固定原件、代码、配置、环境，可复查新一批；最强逐字节保证针对已冻结选中基线和控制分配的最终投影。MILP可能找到多个可行解，跨SciPy/HiGHS版本重新求解不保证相同组合。程序检查可行性并单独报告求解器最优性；可行且超时不能包装成最优算法性能。
