# 试用配置与完整回答

本案例的公司与业务资料为虚构训练设定。

下列配置卡属于接手前的独立试验，不是当前工作区的配置版本。

## Q01

提问：会议室预约入口在什么地方

完整实际回答：会议室预约：在公司日历选择空闲会议室并提交预约，填写主题、时间和参与人。改期后同步取消原预约；助手不能确认房间已被锁定。

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

超出当前额度（未自动修改）：计划人数20超过当前容量15

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

超出当前额度（未自动修改）：计划人数20超过当前容量15

## Q03

提问：入职账号没有开通通知该怎么办

完整实际回答：办公账号：收到开通通知后登录并核对所属组织和可访问范围。没收到通知或登录失败，保留提示信息并联系内部服务台。

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

超出当前额度（未自动修改）：计划人数20超过当前容量15

## Q04

提问：设备坏了想报修应该提供哪些信息

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

超出当前额度（未自动修改）：计划人数20超过当前容量15

## Q05

提问：出差住宿报销一晚能报多少

完整实际回答：国内出差住宿报销上限为每人每晚500元；超出上限须在出行前取得经理书面批准，并保留票据。

状态／原因码：answered / 无错误

引用：policy@1

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

超出当前额度（未自动修改）：计划人数20超过当前容量15

## Q06

提问：出差出租车单程报销上限

完整实际回答：出差出租车单程报销上限为200元；超限或特殊路线需走例外核验。

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

超出当前额度（未自动修改）：计划人数20超过当前容量15

## Q07

提问：今天餐费报销每天按什么额度

完整实际回答：餐费报销上限为每人每天100元；报销需保留合规票据，重复报销和个人个案交费用管理核验。

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

超出当前额度（未自动修改）：计划人数20超过当前容量15

## Q08

提问：计划性请假提交申请需要提前多久

完整实际回答：计划性请假原则上提前3个工作日提交申请，并写明交接安排；紧急情况联系直属负责人。

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

超出当前额度（未自动修改）：计划人数20超过当前容量15

## Q09

提问：国内出差住宿每晚的报销上限

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

超出当前额度（未自动修改）：计划人数20超过当前容量15

## Q10

提问：国内出差住宿每晚的报销上限

完整实际回答：国内出差住宿报销上限为每人每晚500元；超出上限须在出行前取得经理书面批准，并保留票据。

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

超出当前额度（未自动修改）：计划人数20超过当前容量15; 计划上线第10天晚于当前期限第7天

## Q11

提问：国内出差住宿每晚的报销上限

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

超出当前额度（未自动修改）：计划人数20超过当前容量15

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

超出当前额度（未自动修改）：计划人数20超过当前容量15
