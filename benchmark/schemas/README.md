# 标准记录接口

`response.schema.json`定义六个人类回答字段；`record.schema.json`定义同版采集记录的最低字段。实际服务器同时校验身份、源案例、页面显示文本、分数有限值与一位小数、幂等提交、修订及同意状态，JSON Schema不是全部服务端准入规则。

`input.fields`包含family/request/changes/impacts；`expanded_schedule`仅在该身份/案例/版本下曾展示后附带。`response`不进入输入，`objective_results`始终来自源仿真。私有导出另附当前修订的`quality_review`；未人工复核的不是已验证标签。记录及问卷口径随发布摘要绑定，旧标签不能仅改版本号搬到新发布。
