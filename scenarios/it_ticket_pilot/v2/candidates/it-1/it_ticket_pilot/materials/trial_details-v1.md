# 试用配置与完整回答

本案例的公司与业务资料为虚构训练设定。

下列配置卡属于接手前的独立试验，不是当前工作区的配置版本。

## Q01

提问：VPN客户端在哪里下载和登录

完整实际回答：VPN 连接：在受管电脑上打开公司 VPN 客户端，用办公账号登录并完成二次验证。连不上时先确认网络和客户端版本，再把错误提示截图交给服务台；助手不能远程替你连接。

状态／原因码：answered / 无错误

引用：faq@1

源版本：faq: 1; leave: 1; meal: 1; onboarding: 1; policy: 1；索引版本：faq: 1; leave: 1; meal: 1; onboarding: 1; policy: 1

试验配置标识：trial-Q01; version=1; config_version=0

| 参数 | 请求配置 | 实际配置 |
| --- | --- | --- |
| domains | stable_faq, onboarding, policy_travel, policy_meal, policy_leave | stable_faq, onboarding, policy_travel, policy_meal, policy_leave |
| scope_filter | true | true |
| update_strategy | daily | daily |
| fallback | human | human |
| chunk_size | 500 | 500 |
| retrieval_limit | 1 | 1 |
| min_score | 0.35 | 0.35 |
| freshness_guard | none | none |
| manual_domains | — | — |
| prohibited_topics | — | — |
| work_items | scope_filter, human_fallback | scope_filter, human_fallback |
| participants | 20 | 20 |
| launch_day | 7 | 7 |

未生效项（已按实际配置执行）：无

超出当前额度（未自动修改）：无

## Q02

提问：我的账号密码忘记了，需要重置

完整实际回答：账号密码忘记或需要重置：通过办公系统的自助重置入口完成身份核验。无法通过时联系内部服务台；不要把密码或验证码发给助手。这里提供流程，不会告知任何人的现有密码。

状态／原因码：answered / 无错误

引用：faq@1

源版本：faq: 1; leave: 1; meal: 1; onboarding: 1; policy: 1；索引版本：faq: 1; leave: 1; meal: 1; onboarding: 1; policy: 1

试验配置标识：trial-Q02; version=1; config_version=0

| 参数 | 请求配置 | 实际配置 |
| --- | --- | --- |
| domains | stable_faq, onboarding, policy_travel, policy_meal, policy_leave | stable_faq, onboarding, policy_travel, policy_meal, policy_leave |
| scope_filter | true | true |
| update_strategy | daily | daily |
| fallback | human | human |
| chunk_size | 500 | 500 |
| retrieval_limit | 1 | 1 |
| min_score | 0.35 | 0.35 |
| freshness_guard | none | none |
| manual_domains | — | — |
| prohibited_topics | — | — |
| work_items | scope_filter, human_fallback | scope_filter, human_fallback |
| participants | 20 | 20 |
| launch_day | 7 | 7 |

未生效项（已按实际配置执行）：无

超出当前额度（未自动修改）：无

## Q03

提问：入职账号没有开通通知该怎么办

完整实际回答：账号开通：收到开通通知后登录办公系统，核对所属组织和可访问范围；证件与个人信息走指定入口，不向助手上传完整原件。

状态／原因码：answered / 无错误

引用：onboarding@1

源版本：faq: 1; leave: 1; meal: 1; onboarding: 1; policy: 1；索引版本：faq: 1; leave: 1; meal: 1; onboarding: 1; policy: 1

试验配置标识：trial-Q03; version=1; config_version=0

| 参数 | 请求配置 | 实际配置 |
| --- | --- | --- |
| domains | stable_faq, onboarding, policy_travel, policy_meal, policy_leave | stable_faq, onboarding, policy_travel, policy_meal, policy_leave |
| scope_filter | true | true |
| update_strategy | daily | daily |
| fallback | human | human |
| chunk_size | 500 | 500 |
| retrieval_limit | 1 | 1 |
| min_score | 0.35 | 0.35 |
| freshness_guard | none | none |
| manual_domains | — | — |
| prohibited_topics | — | — |
| work_items | scope_filter, human_fallback | scope_filter, human_fallback |
| participants | 20 | 20 |
| launch_day | 7 | 7 |

未生效项（已按实际配置执行）：无

超出当前额度（未自动修改）：无

## Q04

提问：电脑坏了想报修应该提供哪些信息

完整实际回答：未检索到可靠依据，请转人工核验。

状态／原因码：fallback / no_retrieval_hit

引用：—

源版本：faq: 1; leave: 1; meal: 1; onboarding: 1; policy: 1；索引版本：faq: 1; leave: 1; meal: 1; onboarding: 1; policy: 1

试验配置标识：trial-Q04; version=1; config_version=0

| 参数 | 请求配置 | 实际配置 |
| --- | --- | --- |
| domains | stable_faq, onboarding, policy_travel, policy_meal, policy_leave | stable_faq, onboarding, policy_travel, policy_meal, policy_leave |
| scope_filter | true | true |
| update_strategy | daily | daily |
| fallback | human | human |
| chunk_size | 500 | 500 |
| retrieval_limit | 1 | 1 |
| min_score | 0.35 | 0.35 |
| freshness_guard | none | none |
| manual_domains | — | — |
| prohibited_topics | — | — |
| work_items | scope_filter, human_fallback | scope_filter, human_fallback |
| participants | 20 | 20 |
| launch_day | 7 | 7 |

未生效项（已按实际配置执行）：无

超出当前额度（未自动修改）：无

## Q05

提问：P2工单多久必须有人响应

完整实际回答：未检索到可靠依据，请转人工核验。

状态／原因码：fallback / no_retrieval_hit

引用：—

源版本：faq: 1; leave: 1; meal: 1; onboarding: 1; policy: 1；索引版本：faq: 1; leave: 1; meal: 1; onboarding: 1; policy: 1

试验配置标识：trial-Q05; version=1; config_version=0

| 参数 | 请求配置 | 实际配置 |
| --- | --- | --- |
| domains | stable_faq, onboarding, policy_travel, policy_meal, policy_leave | stable_faq, onboarding, policy_travel, policy_meal, policy_leave |
| scope_filter | true | true |
| update_strategy | daily | daily |
| fallback | human | human |
| chunk_size | 500 | 500 |
| retrieval_limit | 1 | 1 |
| min_score | 0.35 | 0.35 |
| freshness_guard | none | none |
| manual_domains | — | — |
| prohibited_topics | — | — |
| work_items | scope_filter, human_fallback | scope_filter, human_fallback |
| participants | 20 | 20 |
| launch_day | 7 | 7 |

未生效项（已按实际配置执行）：无

超出当前额度（未自动修改）：无

## Q06

提问：P1工单响应时限

完整实际回答：P1 工单（影响多人或核心系统的故障）响应时限为30分钟；夜间与节假日走值班电话升级。

状态／原因码：answered / 无错误

引用：policy@1

源版本：faq: 1; leave: 1; meal: 1; onboarding: 1; policy: 1；索引版本：faq: 1; leave: 1; meal: 1; onboarding: 1; policy: 1

试验配置标识：trial-Q06; version=1; config_version=0

| 参数 | 请求配置 | 实际配置 |
| --- | --- | --- |
| domains | stable_faq, onboarding, policy_travel, policy_meal, policy_leave | stable_faq, onboarding, policy_travel, policy_meal, policy_leave |
| scope_filter | true | true |
| update_strategy | daily | daily |
| fallback | human | human |
| chunk_size | 500 | 500 |
| retrieval_limit | 1 | 1 |
| min_score | 0.35 | 0.35 |
| freshness_guard | none | none |
| manual_domains | — | — |
| prohibited_topics | — | — |
| work_items | scope_filter, human_fallback | scope_filter, human_fallback |
| participants | 20 | 20 |
| launch_day | 7 | 7 |

未生效项（已按实际配置执行）：无

超出当前额度（未自动修改）：无

## Q07

提问：今年耗材领用每人额度多少

完整实际回答：键盘、鼠标、耳机等耗材领用额度为每人每年100元；超额或重复领用交资产管理核验。

状态／原因码：answered / 无错误

引用：meal@1

源版本：faq: 1; leave: 1; meal: 1; onboarding: 1; policy: 1；索引版本：faq: 1; leave: 1; meal: 1; onboarding: 1; policy: 1

试验配置标识：trial-Q07; version=1; config_version=0

| 参数 | 请求配置 | 实际配置 |
| --- | --- | --- |
| domains | stable_faq, onboarding, policy_travel, policy_meal, policy_leave | stable_faq, onboarding, policy_travel, policy_meal, policy_leave |
| scope_filter | true | true |
| update_strategy | daily | daily |
| fallback | human | human |
| chunk_size | 500 | 500 |
| retrieval_limit | 1 | 1 |
| min_score | 0.35 | 0.35 |
| freshness_guard | none | none |
| manual_domains | — | — |
| prohibited_topics | — | — |
| work_items | scope_filter, human_fallback | scope_filter, human_fallback |
| participants | 20 | 20 |
| launch_day | 7 | 7 |

未生效项（已按实际配置执行）：无

超出当前额度（未自动修改）：无

## Q08

提问：计划性系统变更需要提前多久提交

完整实际回答：计划性系统变更原则上提前3个工作日提交变更单，并写明回退方案；紧急变更联系值班负责人。

状态／原因码：answered / 无错误

引用：leave@1

源版本：faq: 1; leave: 1; meal: 1; onboarding: 1; policy: 1；索引版本：faq: 1; leave: 1; meal: 1; onboarding: 1; policy: 1

试验配置标识：trial-Q08; version=1; config_version=0

| 参数 | 请求配置 | 实际配置 |
| --- | --- | --- |
| domains | stable_faq, onboarding, policy_travel, policy_meal, policy_leave | stable_faq, onboarding, policy_travel, policy_meal, policy_leave |
| scope_filter | true | true |
| update_strategy | daily | daily |
| fallback | human | human |
| chunk_size | 500 | 500 |
| retrieval_limit | 1 | 1 |
| min_score | 0.35 | 0.35 |
| freshness_guard | none | none |
| manual_domains | — | — |
| prohibited_topics | — | — |
| work_items | scope_filter, human_fallback | scope_filter, human_fallback |
| participants | 20 | 20 |
| launch_day | 7 | 7 |

未生效项（已按实际配置执行）：无

超出当前额度（未自动修改）：无

## Q09

提问：P2工单的响应时限

完整实际回答：该问题超出当前开放知识范围，请转人工核验。

状态／原因码：fallback / outside_scope

引用：—

源版本：faq: 1; leave: 1; meal: 1; onboarding: 1; policy: 1；索引版本：faq: 1; leave: 1; meal: 1; onboarding: 1; policy: 1

试验配置标识：trial-Q09; version=1; config_version=0

| 参数 | 请求配置 | 实际配置 |
| --- | --- | --- |
| domains | stable_faq, onboarding | stable_faq, onboarding |
| scope_filter | true | true |
| update_strategy | daily | daily |
| fallback | human | human |
| chunk_size | 500 | 500 |
| retrieval_limit | 1 | 1 |
| min_score | 0.35 | 0.35 |
| freshness_guard | none | none |
| manual_domains | — | — |
| prohibited_topics | — | — |
| work_items | scope_filter, human_fallback | scope_filter, human_fallback |
| participants | 20 | 20 |
| launch_day | 7 | 7 |

未生效项（已按实际配置执行）：无

超出当前额度（未自动修改）：无

## Q10

提问：P2工单的响应时限

完整实际回答：P2 工单（影响个人办公的故障）响应时限为4小时；超出时限须由业务负责人记录原因并通知提单人。

状态／原因码：answered / 无错误

引用：policy@1

源版本：faq: 1; leave: 1; meal: 1; onboarding: 1; policy: 1；索引版本：faq: 1; leave: 1; meal: 1; onboarding: 1; policy: 1

试验配置标识：trial-Q10; version=1; config_version=0

| 参数 | 请求配置 | 实际配置 |
| --- | --- | --- |
| domains | stable_faq, onboarding, policy_travel, policy_meal, policy_leave | stable_faq, onboarding, policy_travel, policy_meal, policy_leave |
| scope_filter | true | false |
| update_strategy | realtime | daily |
| fallback | human | human |
| chunk_size | 500 | 500 |
| retrieval_limit | 1 | 1 |
| min_score | 0.35 | 0.35 |
| freshness_guard | none | none |
| manual_domains | — | — |
| prohibited_topics | — | — |
| work_items | realtime_sync, human_fallback | human_fallback |
| participants | 20 | 20 |
| launch_day | 10 | 10 |

未生效项（已按实际配置执行）：工作项: realtime_sync, human_fallback → human_fallback; 更新策略: realtime → daily; 范围过滤: true → false

超出当前额度（未自动修改）：计划上线第10天晚于当前期限第7天

## Q11

提问：P2工单的响应时限

完整实际回答：该知识域需要人工核验，当前未作自动回答。

状态／原因码：fallback / manual_verification_required

引用：—

源版本：faq: 1; leave: 1; meal: 1; onboarding: 1; policy: 1；索引版本：faq: 1; leave: 1; meal: 1; onboarding: 1; policy: 1

试验配置标识：trial-Q11; version=1; config_version=0

| 参数 | 请求配置 | 实际配置 |
| --- | --- | --- |
| domains | stable_faq, onboarding, policy_travel, policy_meal, policy_leave | stable_faq, onboarding, policy_travel, policy_meal, policy_leave |
| scope_filter | true | true |
| update_strategy | manual_policy | manual_policy |
| fallback | human | human |
| chunk_size | 500 | 500 |
| retrieval_limit | 1 | 1 |
| min_score | 0.35 | 0.35 |
| freshness_guard | none | none |
| manual_domains | — | — |
| prohibited_topics | — | — |
| work_items | scope_filter, human_fallback | scope_filter, human_fallback |
| participants | 20 | 20 |
| launch_day | 7 | 7 |

未生效项（已按实际配置执行）：无

超出当前额度（未自动修改）：无

## Q12

提问：海王星大气的主要成分

完整实际回答：当前无法可靠自动回答，且人工兜底尚未生效。

状态／原因码：failed / no_retrieval_hit

引用：—

源版本：faq: 1; leave: 1; meal: 1; onboarding: 1; policy: 1；索引版本：faq: 1; leave: 1; meal: 1; onboarding: 1; policy: 1

试验配置标识：trial-Q12; version=1; config_version=0

| 参数 | 请求配置 | 实际配置 |
| --- | --- | --- |
| domains | stable_faq, onboarding, policy_travel, policy_meal, policy_leave | stable_faq, onboarding, policy_travel, policy_meal, policy_leave |
| scope_filter | true | true |
| update_strategy | daily | daily |
| fallback | none | none |
| chunk_size | 500 | 500 |
| retrieval_limit | 1 | 1 |
| min_score | 0.35 | 0.35 |
| freshness_guard | none | none |
| manual_domains | — | — |
| prohibited_topics | — | — |
| work_items | scope_filter, human_fallback | scope_filter, human_fallback |
| participants | 20 | 20 |
| launch_day | 7 | 7 |

未生效项（已按实际配置执行）：无

超出当前额度（未自动修改）：无
