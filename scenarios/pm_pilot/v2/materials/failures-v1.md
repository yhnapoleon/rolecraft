# 筹备期试用问答记录

本案例的公司与业务资料为虚构训练设定。

整理：筹备期技术试用记录。以下试验均在产品经理接手前完成，各试验单独采用所列初始配置和同一批初始来源。试验编号用于回查，不是本次工作区的配置版本。

试验Q01｜提问：会议室预约入口在什么地方

请求配置：{"chunk_size": 500, "domains": ["stable_faq", "onboarding", "policy_travel", "policy_meal", "policy_leave"], "fallback": "human", "freshness_guard": "none", "launch_day": 7, "manual_domains": [], "min_score": 0.35, "participants": 20, "prohibited_topics": [], "retrieval_limit": 1, "scope_filter": true, "update_strategy": "daily", "work_items": ["scope_filter", "human_fallback"]}

实际配置：{"chunk_size": 500, "domains": ["stable_faq", "onboarding", "policy_travel", "policy_meal", "policy_leave"], "fallback": "human", "freshness_guard": "none", "launch_day": 7, "manual_domains": [], "min_score": 0.35, "participants": 20, "prohibited_topics": [], "retrieval_limit": 1, "scope_filter": true, "update_strategy": "daily", "work_items": ["scope_filter", "human_fallback"]}

参数差异：{}

实际回答：会议室预约：在公司日历选择空闲会议室并提交预约，填写主题、时间和参与人。改期后同步取消原预约；助手不能确认房间已被锁定。

引用：faq@1

源版本：{"faq": 1, "leave": 1, "meal": 1, "onboarding": 1, "policy": 1}；索引版本：{"faq": 1, "leave": 1, "meal": 1, "onboarding": 1, "policy": 1}

实际状态：answered；原因码：无错误。

试验Q02｜提问：我的账号密码忘记了，需要重置

请求配置：{"chunk_size": 500, "domains": ["stable_faq", "onboarding", "policy_travel", "policy_meal", "policy_leave"], "fallback": "human", "freshness_guard": "none", "launch_day": 7, "manual_domains": [], "min_score": 0.35, "participants": 20, "prohibited_topics": [], "retrieval_limit": 1, "scope_filter": true, "update_strategy": "daily", "work_items": ["scope_filter", "human_fallback"]}

实际配置：{"chunk_size": 500, "domains": ["stable_faq", "onboarding", "policy_travel", "policy_meal", "policy_leave"], "fallback": "human", "freshness_guard": "none", "launch_day": 7, "manual_domains": [], "min_score": 0.35, "participants": 20, "prohibited_topics": [], "retrieval_limit": 1, "scope_filter": true, "update_strategy": "daily", "work_items": ["scope_filter", "human_fallback"]}

参数差异：{}

实际回答：账号密码忘记或需要重置：通过办公系统的自助重置入口完成身份核验。无法通过时联系内部服务台；不要把密码或验证码发给助手。这里提供流程，不会告知任何人的现有密码。

引用：faq@1

源版本：{"faq": 1, "leave": 1, "meal": 1, "onboarding": 1, "policy": 1}；索引版本：{"faq": 1, "leave": 1, "meal": 1, "onboarding": 1, "policy": 1}

实际状态：answered；原因码：无错误。

试验Q03｜提问：入职账号没有开通通知该怎么办

请求配置：{"chunk_size": 500, "domains": ["stable_faq", "onboarding", "policy_travel", "policy_meal", "policy_leave"], "fallback": "human", "freshness_guard": "none", "launch_day": 7, "manual_domains": [], "min_score": 0.35, "participants": 20, "prohibited_topics": [], "retrieval_limit": 1, "scope_filter": true, "update_strategy": "daily", "work_items": ["scope_filter", "human_fallback"]}

实际配置：{"chunk_size": 500, "domains": ["stable_faq", "onboarding", "policy_travel", "policy_meal", "policy_leave"], "fallback": "human", "freshness_guard": "none", "launch_day": 7, "manual_domains": [], "min_score": 0.35, "participants": 20, "prohibited_topics": [], "retrieval_limit": 1, "scope_filter": true, "update_strategy": "daily", "work_items": ["scope_filter", "human_fallback"]}

参数差异：{}

实际回答：办公账号：收到开通通知后登录并核对所属组织和可访问范围。没收到通知或登录失败，保留提示信息并联系内部服务台。

引用：onboarding@1

源版本：{"faq": 1, "leave": 1, "meal": 1, "onboarding": 1, "policy": 1}；索引版本：{"faq": 1, "leave": 1, "meal": 1, "onboarding": 1, "policy": 1}

实际状态：answered；原因码：无错误。

试验Q04｜提问：设备坏了想报修应该提供哪些信息

请求配置：{"chunk_size": 500, "domains": ["stable_faq", "onboarding", "policy_travel", "policy_meal", "policy_leave"], "fallback": "human", "freshness_guard": "none", "launch_day": 7, "manual_domains": [], "min_score": 0.35, "participants": 20, "prohibited_topics": [], "retrieval_limit": 1, "scope_filter": true, "update_strategy": "daily", "work_items": ["scope_filter", "human_fallback"]}

实际配置：{"chunk_size": 500, "domains": ["stable_faq", "onboarding", "policy_travel", "policy_meal", "policy_leave"], "fallback": "human", "freshness_guard": "none", "launch_day": 7, "manual_domains": [], "min_score": 0.35, "participants": 20, "prohibited_topics": [], "retrieval_limit": 1, "scope_filter": true, "update_strategy": "daily", "work_items": ["scope_filter", "human_fallback"]}

参数差异：{}

实际回答：未检索到可靠依据，请转人工核验。

引用：无

源版本：{"faq": 1, "leave": 1, "meal": 1, "onboarding": 1, "policy": 1}；索引版本：{"faq": 1, "leave": 1, "meal": 1, "onboarding": 1, "policy": 1}

实际状态：fallback；原因码：no_retrieval_hit。

试验Q05｜提问：出差住宿报销一晚能报多少

请求配置：{"chunk_size": 500, "domains": ["stable_faq", "onboarding", "policy_travel", "policy_meal", "policy_leave"], "fallback": "human", "freshness_guard": "none", "launch_day": 7, "manual_domains": [], "min_score": 0.35, "participants": 20, "prohibited_topics": [], "retrieval_limit": 1, "scope_filter": true, "update_strategy": "daily", "work_items": ["scope_filter", "human_fallback"]}

实际配置：{"chunk_size": 500, "domains": ["stable_faq", "onboarding", "policy_travel", "policy_meal", "policy_leave"], "fallback": "human", "freshness_guard": "none", "launch_day": 7, "manual_domains": [], "min_score": 0.35, "participants": 20, "prohibited_topics": [], "retrieval_limit": 1, "scope_filter": true, "update_strategy": "daily", "work_items": ["scope_filter", "human_fallback"]}

参数差异：{}

实际回答：国内出差住宿报销上限为每人每晚500元；超出上限须在出行前取得经理书面批准，并保留票据。

引用：policy@1

源版本：{"faq": 1, "leave": 1, "meal": 1, "onboarding": 1, "policy": 1}；索引版本：{"faq": 1, "leave": 1, "meal": 1, "onboarding": 1, "policy": 1}

实际状态：answered；原因码：无错误。

试验Q06｜提问：出差出租车单程报销上限

请求配置：{"chunk_size": 500, "domains": ["stable_faq", "onboarding", "policy_travel", "policy_meal", "policy_leave"], "fallback": "human", "freshness_guard": "none", "launch_day": 7, "manual_domains": [], "min_score": 0.35, "participants": 20, "prohibited_topics": [], "retrieval_limit": 1, "scope_filter": true, "update_strategy": "daily", "work_items": ["scope_filter", "human_fallback"]}

实际配置：{"chunk_size": 500, "domains": ["stable_faq", "onboarding", "policy_travel", "policy_meal", "policy_leave"], "fallback": "human", "freshness_guard": "none", "launch_day": 7, "manual_domains": [], "min_score": 0.35, "participants": 20, "prohibited_topics": [], "retrieval_limit": 1, "scope_filter": true, "update_strategy": "daily", "work_items": ["scope_filter", "human_fallback"]}

参数差异：{}

实际回答：出差出租车单程报销上限为200元；超限或特殊路线需走例外核验。

引用：policy@1

源版本：{"faq": 1, "leave": 1, "meal": 1, "onboarding": 1, "policy": 1}；索引版本：{"faq": 1, "leave": 1, "meal": 1, "onboarding": 1, "policy": 1}

实际状态：answered；原因码：无错误。

试验Q07｜提问：今天餐费报销每天按什么额度

请求配置：{"chunk_size": 500, "domains": ["stable_faq", "onboarding", "policy_travel", "policy_meal", "policy_leave"], "fallback": "human", "freshness_guard": "none", "launch_day": 7, "manual_domains": [], "min_score": 0.35, "participants": 20, "prohibited_topics": [], "retrieval_limit": 1, "scope_filter": true, "update_strategy": "daily", "work_items": ["scope_filter", "human_fallback"]}

实际配置：{"chunk_size": 500, "domains": ["stable_faq", "onboarding", "policy_travel", "policy_meal", "policy_leave"], "fallback": "human", "freshness_guard": "none", "launch_day": 7, "manual_domains": [], "min_score": 0.35, "participants": 20, "prohibited_topics": [], "retrieval_limit": 1, "scope_filter": true, "update_strategy": "daily", "work_items": ["scope_filter", "human_fallback"]}

参数差异：{}

实际回答：餐费报销上限为每人每天100元；报销需保留合规票据，重复报销和个人个案交费用管理核验。

引用：meal@1

源版本：{"faq": 1, "leave": 1, "meal": 1, "onboarding": 1, "policy": 1}；索引版本：{"faq": 1, "leave": 1, "meal": 1, "onboarding": 1, "policy": 1}

实际状态：answered；原因码：无错误。

试验Q08｜提问：计划性请假提交申请需要提前多久

请求配置：{"chunk_size": 500, "domains": ["stable_faq", "onboarding", "policy_travel", "policy_meal", "policy_leave"], "fallback": "human", "freshness_guard": "none", "launch_day": 7, "manual_domains": [], "min_score": 0.35, "participants": 20, "prohibited_topics": [], "retrieval_limit": 1, "scope_filter": true, "update_strategy": "daily", "work_items": ["scope_filter", "human_fallback"]}

实际配置：{"chunk_size": 500, "domains": ["stable_faq", "onboarding", "policy_travel", "policy_meal", "policy_leave"], "fallback": "human", "freshness_guard": "none", "launch_day": 7, "manual_domains": [], "min_score": 0.35, "participants": 20, "prohibited_topics": [], "retrieval_limit": 1, "scope_filter": true, "update_strategy": "daily", "work_items": ["scope_filter", "human_fallback"]}

参数差异：{}

实际回答：计划性请假原则上提前3个工作日提交申请，并写明交接安排；紧急情况联系直属负责人。

引用：leave@1

源版本：{"faq": 1, "leave": 1, "meal": 1, "onboarding": 1, "policy": 1}；索引版本：{"faq": 1, "leave": 1, "meal": 1, "onboarding": 1, "policy": 1}

实际状态：answered；原因码：无错误。

试验Q09｜提问：国内出差住宿每晚的报销上限

请求配置：{"chunk_size": 500, "domains": ["stable_faq", "onboarding"], "fallback": "human", "freshness_guard": "none", "launch_day": 7, "manual_domains": [], "min_score": 0.35, "participants": 20, "prohibited_topics": [], "retrieval_limit": 1, "scope_filter": true, "update_strategy": "daily", "work_items": ["scope_filter", "human_fallback"]}

实际配置：{"chunk_size": 500, "domains": ["stable_faq", "onboarding"], "fallback": "human", "freshness_guard": "none", "launch_day": 7, "manual_domains": [], "min_score": 0.35, "participants": 20, "prohibited_topics": [], "retrieval_limit": 1, "scope_filter": true, "update_strategy": "daily", "work_items": ["scope_filter", "human_fallback"]}

参数差异：{}

实际回答：该问题超出当前开放知识范围，请转人工核验。

引用：无

源版本：{"faq": 1, "leave": 1, "meal": 1, "onboarding": 1, "policy": 1}；索引版本：{"faq": 1, "leave": 1, "meal": 1, "onboarding": 1, "policy": 1}

实际状态：fallback；原因码：outside_scope。

试验Q10｜提问：国内出差住宿每晚的报销上限

请求配置：{"chunk_size": 500, "domains": ["stable_faq", "onboarding", "policy_travel", "policy_meal", "policy_leave"], "fallback": "human", "freshness_guard": "none", "launch_day": 10, "manual_domains": [], "min_score": 0.35, "participants": 20, "prohibited_topics": [], "retrieval_limit": 1, "scope_filter": true, "update_strategy": "realtime", "work_items": ["realtime_sync", "human_fallback"]}

实际配置：{"chunk_size": 500, "domains": ["stable_faq", "onboarding", "policy_travel", "policy_meal", "policy_leave"], "fallback": "human", "freshness_guard": "none", "launch_day": 10, "manual_domains": [], "min_score": 0.35, "participants": 20, "prohibited_topics": [], "retrieval_limit": 1, "scope_filter": false, "update_strategy": "daily", "work_items": ["human_fallback"]}

参数差异：{"launch_day": "requested_launch_exceeds_approved_deadline", "scope_filter": "scope_filter_not_provisioned", "update_strategy": "realtime_sync_not_provisioned", "work_items": "requested_work_exceeds_approved_budget"}

实际回答：国内出差住宿报销上限为每人每晚500元；超出上限须在出行前取得经理书面批准，并保留票据。

引用：policy@1

源版本：{"faq": 1, "leave": 1, "meal": 1, "onboarding": 1, "policy": 1}；索引版本：{"faq": 1, "leave": 1, "meal": 1, "onboarding": 1, "policy": 1}

实际状态：answered；原因码：无错误。

试验Q11｜提问：国内出差住宿每晚的报销上限

请求配置：{"chunk_size": 500, "domains": ["stable_faq", "onboarding", "policy_travel", "policy_meal", "policy_leave"], "fallback": "human", "freshness_guard": "none", "launch_day": 7, "manual_domains": [], "min_score": 0.35, "participants": 20, "prohibited_topics": [], "retrieval_limit": 1, "scope_filter": true, "update_strategy": "manual_policy", "work_items": ["scope_filter", "human_fallback"]}

实际配置：{"chunk_size": 500, "domains": ["stable_faq", "onboarding", "policy_travel", "policy_meal", "policy_leave"], "fallback": "human", "freshness_guard": "none", "launch_day": 7, "manual_domains": [], "min_score": 0.35, "participants": 20, "prohibited_topics": [], "retrieval_limit": 1, "scope_filter": true, "update_strategy": "manual_policy", "work_items": ["scope_filter", "human_fallback"]}

参数差异：{}

实际回答：该知识域需要人工核验，当前未作自动回答。

引用：无

源版本：{"faq": 1, "leave": 1, "meal": 1, "onboarding": 1, "policy": 1}；索引版本：{"faq": 1, "leave": 1, "meal": 1, "onboarding": 1, "policy": 1}

实际状态：fallback；原因码：manual_verification_required。

试验Q12｜提问：海王星大气的主要成分

请求配置：{"chunk_size": 500, "domains": ["stable_faq", "onboarding", "policy_travel", "policy_meal", "policy_leave"], "fallback": "none", "freshness_guard": "none", "launch_day": 7, "manual_domains": [], "min_score": 0.35, "participants": 20, "prohibited_topics": [], "retrieval_limit": 1, "scope_filter": true, "update_strategy": "daily", "work_items": ["scope_filter", "human_fallback"]}

实际配置：{"chunk_size": 500, "domains": ["stable_faq", "onboarding", "policy_travel", "policy_meal", "policy_leave"], "fallback": "none", "freshness_guard": "none", "launch_day": 7, "manual_domains": [], "min_score": 0.35, "participants": 20, "prohibited_topics": [], "retrieval_limit": 1, "scope_filter": true, "update_strategy": "daily", "work_items": ["scope_filter", "human_fallback"]}

参数差异：{}

实际回答：当前无法可靠自动回答，且人工兜底尚未生效。

引用：无

源版本：{"faq": 1, "leave": 1, "meal": 1, "onboarding": 1, "policy": 1}；索引版本：{"faq": 1, "leave": 1, "meal": 1, "onboarding": 1, "policy": 1}

实际状态：failed；原因码：no_retrieval_hit。
