"""Second domain (design 6.1): an IT service-desk ticket assistant pilot, same structure as
pm_pilot. Every material id, version, domain, disclosure mode and fact id/value is kept, so
the loader's arithmetic checks, the evaluation rules and the recognizers run unchanged; only
the business wording moves from an office knowledge assistant to IT tickets. The travel
policy becomes the SLA policy (P2 response 4 hours, then 2 hours); fact ids such as
``hotel_limit`` keep their pm_pilot names because evaluation rules read them by id.
"""

from .content import row


def materials():
    return [
        (
            "brief",
            "经理委托：IT 工单助手试点",
            "investigation",
            1,
            "public",
            [
                (
                    "发件人：IT 服务经理｜收件人：项目产品经理。你接手星桥数字的 IT 工单助手："
                    "员工先问助手，答不了的再转服务台建单。周岚（服务台负责人）"
                    "送来了第一版需求测算，一线值班组和技术负责人还没同意同一套试点安排。"
                    "我需要据此决定本周邀请哪些人试用。"
                ),
                row(
                    "目前为项目预留的容量是30人，可用开发资源3人日，正式试点期限为第7天。",
                    ("capacity", 30, "人"),
                    ("dev_days", 3, "人日"),
                    ("deadline_day", 7, "天"),
                ),
                "请把服务对象、开放范围、资源安排和验证记录交给我，说明由谁接手下一步。周岚负责联系服务台，技术负责人负责解释实现与运行结果。我接受工作记录、方案、测试单或相互引用的几份作品，沟通顺序由你安排。",
                "本轮尚未向员工开放。候选名单、服务台工单导出、同事意见和筹备期试用记录已放在工作区。你可以试用现有助手，找同事澄清，保存或分享自己的作品；私人草稿由你决定何时分享。",
                "我在第5天安排了内部演示。试点开放决定将在收到你的建议后另行记录。",
                (
                    "当前保存的是20人、第7天的筹备配置草案。已有草案不代表资源或上线日期已获批；本次委托以上方预留为准，请核对后决定提出什么建议。",
                    [("draft_participants", 20, "人"), ("draft_launch_day", 7, "天")],
                ),
            ],
        ),
        (
            "demand",
            "服务台导出 SD-120：工单登记与字段口径",
            "investigation",
            1,
            "public",
            [
                (
                    "整理：吕雯｜一线值班组长。导出批次SD-120，筹备期最后10个工作日的已结单工单"
                    "；“服务台”指现有的人工 IT 支持渠道，周岚是本项目的服务台负责人，"
                    "不是这份导出的填报人。"
                ),
                row(
                    "样本窗口为10个工作日，筛选条件closed=true，共120张工单，涉及56名不同提单人。",
                    ("sample_days", 10, "工作日"),
                    ("demand_total", 120, "次"),
                    ("unique_requesters", 56, "人"),
                ),
                row(
                    (
                        "分类常见 IT 问题：72次；接单到结单时长合计288分钟，均值4分钟；"
                        "重复意图标记50次。"
                    ),
                    ("demand_faq", 72, "次"),
                    ("faq_total_minutes", 288, "分钟"),
                    ("faq_avg_minutes", 4, "分钟"),
                    ("faq_repeats", 50, "次"),
                ),
                row(
                    "分类时限与流程：36次；接单到结单时长合计324分钟，均值9分钟；重复意图标记14次。",
                    ("demand_policy", 36, "次"),
                    ("policy_total_minutes", 324, "分钟"),
                    ("policy_avg_minutes", 9, "分钟"),
                    ("policy_repeats", 14, "次"),
                ),
                row(
                    "分类安全个案：12次；接单到结单时长合计168分钟，均值14分钟；重复意图标记2次。",
                    ("demand_sensitive", 12, "次"),
                    ("sensitive_total_minutes", 168, "分钟"),
                    ("sensitive_avg_minutes", 14, "分钟"),
                    ("sensitive_repeats", 2, "次"),
                ),
                row(
                    "导出合计：780分钟、66次重复标记；重复率字段以全部120次为分母，结果55%。",
                    ("total_minutes", 780, "分钟"),
                    ("total_repeats", 66, "次"),
                    ("repeat_percent", 55, "%"),
                ),
                (
                    "字段字典：duration_minutes = closed_at − accepted_at。等待用户补截图、"
                    "排队转派二线和复核期间，系统不暂停计时。repeat_intent由当班人员按相近问法"
                    "手动勾选。导出没有“工程师实际处理分钟”字段。"
                ),
                (
                    "原始行摘录：SD-014，VPN 无法连接，接单09:10/结单09:14，备注“发指引，"
                    "等用户确认”；SD-061，P2 时限例外，接单10:20/结单10:38，备注“10:"
                    "23转给服务台负责人”；SD-089，账号核验，接单14:05/结单14:17，"
                    "备注“用户补信息”。这些行已计入上面的分类合计。"
                ),
                "吕雯附注：未结单工单没有进入SD-120；未逐条填写满意度、一次解决率或工程师操作时长。若需核对，可带导出批次、行号和字段名与周岚讨论现有记录；仍缺的原始资料由周岚协调，收到后另附来源。",
            ],
        ),
        (
            "business_case",
            "周岚的收益测算草稿 BC-01",
            "investigation",
            1,
            "public",
            [
                "作者：周岚｜服务台负责人。筹备期草稿v0.1，发给经理讨论；引用数据为服务台导出SD-120，尚无员工试点结果。",
                row(
                    "草稿测算：SD-120的重复率55%乘以780分钟，得到429分钟。周岚写道：“如果助手接住重复工单，十个工作日可释放429分钟服务台时间；我想用这个数争取试点。”",
                    ("saving_claim", 429, "分钟/10工作日；BC-01测算主张"),
                ),
                "草稿附件栏填写“需求样本SD-120”，没有另附按重复标记筛选的时长合计，也没有工程师工作计时表。",
                (
                    "周岚给经理的备注：“时限类问题虽然只有36次，但每次解释 SLA 都费时间；"
                    "我倾向先把时限问题放进来。有人需要核对这个测算的话，可以把具体字段发我。”"
                ),
            ],
        ),
        (
            "coordination",
            "许青的筹备协调纪要 COORD-01",
            "investigation",
            1,
            "public",
            [
                "记录：许青｜项目助理。转交产品经理前的筹备协调摘要，收件人为经理和周岚。",
                "条目3：“人工兜底已与周岚谈妥，每天45分钟，由服务台负责人安排。”依据栏写“周岚在群里的回复”，没有值班表附件。",
                "条目4：“候选名单INV-50共50人，拟在方案确认后发邀请。”",
                "许青附言：“这是我对群消息的整理；周岚的原始回复附在《信息安全规则与周岚的安排回复》，涉及这份转述，可请周岚对照她的原始回复核对；需要更正的段落在修订记录中列明。”",
            ],
        ),
        (
            "user_groups",
            "候选邀请清单 INV-50",
            "investigation",
            1,
            "public",
            [
                "整理：项目助理许青。来源：各组联络人提交的候选名单，状态截至转交产品经理前。名单按所属组计人，不含提单次数。",
                row(
                    "新员工组20人、外勤销售组20人、服务台值班组10人，候选合计50人。",
                    ("new_staff", 20, "人"),
                    ("operations_staff", 20, "人"),
                    ("admin_staff", 10, "人"),
                    ("candidate_total", 50, "人"),
                ),
                "新员工联络人填写：“首周账号、VPN、打印机，经常不知道去哪找。”这20人来自同一入职批次；邀请尚未发出。",
                "外勤销售联络人填写：“团队常在客户现场，想问工单多久有人响应、能不能加急。”20人里有轮班员工，实际试用时段需另外约。",
                "服务台联络人填写：“希望试用后少重复解释流程。”10名候选人中有一线值班人员，访谈代表C在名单中。",
                "许青记录：本清单没有与SD-120提单人逐人关联。联络人要求邀请邮件先抄送本组，尚未确认每位候选人都能参加。",
            ],
        ),
        (
            "interviews",
            "筹备期访谈摘录 INT-03",
            "investigation",
            1,
            "public",
            [
                "记录：项目助理许青。对象为三位自愿参与筹备访谈的候选代表；以下引号内保留原话，未做匿名问卷汇总。",
                row(
                    (
                        "A｜新员工代表：“我最缺的是入口指引。找不到 VPN 客户端、"
                        "账号开通和打印机设置时，不知道该问谁。”"
                    ),
                    ("new_staff_priority", "入口指引", "A的访谈陈述"),
                ),
                "A：“上次我提了软件安装申请，以为提交就能装，后来才看到还要等审批。我想问得口语一点，不想记系统里的字段名。”",
                row(
                    "B｜外勤销售代表：“如果每次还得打电话问服务台，我不太想多开一个入口。我关心时限是不是今天有效。”",
                    ("operations_concern", "时限是不是今天有效", "B的访谈陈述"),
                ),
                "B：“我常把电脑故障和账号锁定一起报。上次工单超时没人理，是经理单独催的；我希望它能告诉我类似情况找谁。”",
                row(
                    "C｜服务台代表：“如果先答错，再找我们解释，可能增加复核负担。”",
                    ("admin_concern", "增加复核负担", "C的访谈陈述"),
                ),
                "C：“最近我处理过两个工单：一个用户看完指引没有回复，另一个换群继续问。结单的时候两条都打了完成，我记不清后面是否解决。”",
                "周岚｜服务台负责人：“我希望这次包含时限类问题，否则服务台未必愿意安排人试。需要我补材料或核对转述，直接给我具体那段记录。”",
            ],
        ),
        (
            "technical",
            "技术负责人交接：当前能力与配置项",
            "investigation",
            1,
            "public",
            [
                "维护：技术负责人。当前交付为段落检索式工单助手，答案保留所用文档和版本。可配置知识域、检索条数、片段长度、匹配阈值、来源新鲜度处理和人工兜底。",
                row(
                    "默认知识索引按日更新，源文档到索引的窗口最长24小时。",
                    ("index_delay_hours", 24, "小时"),
                ),
                row(
                    "工作项预算：范围过滤1人日；人工兜底入口1人日；实时同步5人日，包含同步与知识域配置，人工兜底单列。",
                    ("cost_scope_filter", 1, "人日"),
                    ("cost_human_fallback", 1, "人日"),
                    ("cost_realtime_sync", 5, "人日"),
                ),
                "成本按所选工作项相加。范围过滤、人工兜底和实时同步仅在对应工作项及已批准预算足够时生效；配置界面会保留请求参数、实际参数和未生效原因。",
                "“刷新索引”读取此刻已发布的来源。“实时同步”按当前源版本检索；“政策人工核验”把动态时限问题转入人工处理。上述选择可以独立保存为配置版本。",
                "检索按问题与片段的词项覆盖率排序。匹配阈值默认0.35，未完成统一校准；低于阈值不取该片段。来源新鲜度可选不额外处理、警示、或转人工。",
                "技术负责人：“我需要原问法和配置快照才能复现。试用记录请保留实际回答、引用和状态码；遇到检索问题可以带记录找我。”",
                "执行边界：助手没有重置账号、修改权限或关闭工单的系统权限；转交提示也不会自动在服务台建单。",
            ],
        ),
        (
            "approvals",
            "经理发布：资源审批规则",
            "investigation",
            1,
            "public",
            [
                (
                    "发布人：IT 服务经理。以下规则用于本轮容量、开发人日和正式试点期限申请；"
                    "依据为申请所绑定的已应用或待实施配置。"
                ),
                row(
                    "可审批上限：容量60人，开发资源6人日，期限第10天。",
                    ("capacity_limit", 60, "人"),
                    ("dev_days_limit", 6, "人日"),
                    ("deadline_day_limit", 10, "天"),
                ),
                "申请需写请求条款、理由和拟实施配置。可以先申请待实施方案，也可以申请当前方案。证据引用可选；提供时必须是已有权限读取的确切材料版本。",
                "每项请求必须对应超过现有资源的真实配置缺口；请求数应能覆盖所填目标，且不超过上限。没有日期缺口的延期申请、没有人数缺口的容量申请会被拒绝；混合请求有不必要条款时整单退回。当前规则允许缺口以上、上限以内的备用量，不自动评估其经济成本。",
                "所有资源申请必须安排人工兜底：fallback选择human，并包含human_fallback工作项；日更或政策人工核验还需scope_filter；实时策略需realtime_sync。未满足时退回补齐后再审。",
                "决定记录生效后才调整资源额度，配置由产品经理另行应用。每次退回保留原因与原申请；改条款后可重新申请。超出上述三类资源的建议需另行讨论，不产生自动资源变化。",
            ],
        ),
        (
            "faq",
            "常见 IT 问题",
            "stable_faq",
            1,
            "public",
            [
                (
                    "VPN 连接：在受管电脑上打开公司 VPN 客户端，用办公账号登录并完成二次验证。"
                    "连不上时先确认网络和客户端版本，再把错误提示截图交给服务台；"
                    "助手不能远程替你连接。"
                ),
                "账号密码忘记或需要重置：通过办公系统的自助重置入口完成身份核验。无法通过时联系内部服务台；不要把密码或验证码发给助手。这里提供流程，不会告知任何人的现有密码。",
                "设备报修：向内部服务台提交设备编号、故障现象、已尝试步骤和可联系时段。保留工单编号；助手给出报修指引不代表维修已经完成。",
                "打印机：在系统设置里添加楼层打印队列，首次使用需刷工卡认领。卡纸或缺粉请报修，不要自行拆机。",
                "软件安装申请：在软件目录选择需要的软件并说明用途，提交后等待审批；审批通过前不要自行安装未授权软件。",
                "邮箱容量：邮箱接近上限时先归档旧邮件；需要扩容的在服务台提交申请并写明原因，容量状态以邮件系统显示为准。",
                "培训报名：在学习门户查看开放课程与适用对象，提交报名后等待课程负责人确认。报名和录取是两个状态。",
                "办公网络连接：受管设备按服务台提供的连接指引操作。遇到证书或权限问题停止尝试并联系服务台，不分享访问密钥。",
                "工单转派：先说明要完成的工作、已查资料、具体卡点和时间要求。若被转给二线，保留原工单号和已有证据，避免同一问题在不同渠道被重复解释。",
            ],
        ),
        (
            "onboarding",
            "服务台维护：新员工首周 IT 指引",
            "onboarding",
            1,
            "public",
            [
                "账号开通：收到开通通知后登录办公系统，核对所属组织和可访问范围；证件与个人信息走指定入口，不向助手上传完整原件。",
                "办公账号：没收到通知或登录失败，保留提示信息并联系内部服务台。",
                "权限申请：填写需要的系统、职责和批准人，申请状态以审批系统为准。",
                "电脑与外设：领取时核对设备编号和配件；故障时在报修单填写现象、已尝试步骤和可联系时段。",
                "培训与支持：学习门户显示适用对象与开放名额；课程负责人确认名单后发出通知。",
            ],
        ),
        (
            "policy",
            "IT 服务等级协议（SLA）",
            "policy_travel",
            1,
            "public",
            [
                row(
                    (
                        "P2 工单（影响个人办公的故障）响应时限为4小时；"
                        "超出时限须由服务台负责人记录原因并通知提单人。"
                    ),
                    ("hotel_limit", 4, "小时"),
                ),
                row(
                    (
                        "P1 工单（影响多人或核心系统的故障）响应时限为30分钟；"
                        "夜间与节假日走值班电话升级。"
                    ),
                    ("taxi_limit", 30, "分钟"),
                ),
                "时限解释与超时个案由服务台负责人协调。助手可以引用规则，但不能判断某张工单已经获准加急，也不能代替服务台关单。",
            ],
        ),
        (
            "policy",
            "服务管理通知：P2 响应时限调整",
            "policy_travel",
            2,
            "public",
            [
                row(
                    (
                        "服务管理通知：P2 工单响应时限改为2小时；超出时限仍须由服务台负责人记录"
                        "原因并通知提单人。"
                    ),
                    ("hotel_limit", 2, "小时"),
                ),
                row(
                    "P1 工单响应时限仍为30分钟；夜间与节假日走值班电话升级。",
                    ("taxi_limit", 30, "分钟"),
                ),
                "发布部门：服务管理。本文替代此前的 P2 时限条款；超时个案由服务台负责人协调核验。",
            ],
        ),
        (
            "meal",
            "IT 资产：耗材领用规则",
            "policy_meal",
            1,
            "public",
            [
                row(
                    "键盘、鼠标、耳机等耗材领用额度为每人每年100元；超额或重复领用交资产管理核验。",
                    ("meal_limit", 100, "元/人/年"),
                ),
                "适用范围：员工个人耗材。领用日期、资产编号和审批状态在领用单记录。",
            ],
        ),
        (
            "leave",
            "变更管理：计划性变更申请",
            "policy_leave",
            1,
            "public",
            [
                row(
                    "计划性系统变更原则上提前3个工作日提交变更单，并写明回退方案；紧急变更联系值班负责人。",
                    ("leave_notice_days", 3, "工作日"),
                ),
                "变更是否批准以变更系统通知为准。他人的变更记录和权限明细由授权负责人查询，助手不提供。",
            ],
        ),
        (
            "restricted",
            "信息安全规则与周岚的安排回复",
            "investigation",
            1,
            "public",
            [
                "信息安全发布：个人薪资、他人绩效、医疗诊断、实际密码和访问密钥不得由助手披露。可以解释公开的密码重置及信息安全流程；实际凭据通过指定安全渠道管理。",
                "人工转交：保留原问题、已给答复及来源版本；向哪位负责人分享由提问者确认。当前助手不代为建单。",
                row(
                    "周岚｜服务台负责人，筹备期原始回复：“我每天可以预留45分钟查看试用提问和转交记录。”",
                    ("support_observation_minutes", 45, "分钟/天；周岚观察意向"),
                ),
                "同一回复下半段：“这段时间供我了解问题，不等于有人值班接单。人工兜底的人员、服务时段和响应约定还没有确认；涉及账号要走自助重置或安全渠道，超时个案需服务台负责人处理。许青写纪要时可引用这封回复。”",
            ],
        ),
        (
            "demo",
            "经理日程：内部演示",
            "investigation",
            1,
            "public",
            [
                row("经理日程预留第5天，查看一次工单助手内部演示。", ("demo_day", 5, "天")),
                "经理留言：“请带这几天形成的作品和试用记录。演示参加人为经理、产品经理、周岚和技术负责人，邀请员工试点另行安排。”",
            ],
        ),
        (
            "demo",
            "经理日程变更通知",
            "investigation",
            2,
            "public",
            [
                row("经理通知：因部门日程冲突，内部演示改到第4天。", ("demo_day", 4, "天")),
                "经理留言：“参会人不变。把准备安排发给我；正式试点期限仍按资源决定记录。”",
            ],
        ),
        (
            "scope_note",
            "业务范围讨论纪要 SCOPE-01",
            "investigation",
            1,
            "public",
            [
                "整理：许青｜筹备讨论。周岚提出时限类问题，服务台代表C提出先看入口类问题。候选清单为INV-50，尚未发邀请。",
                (
                    "周岚：“我想保留 SLA 时限问题，尤其是需要解释超时的那些。若只做入口指引，"
                    "需要告诉我这轮打算观察什么。”经理：“把你的方案和依据发来，我们再定。”"
                ),
            ],
        ),
        (
            "scope_note",
            "周岚转来：研发组追加意向",
            "investigation",
            2,
            "public",
            [
                row(
                    "周岚转述研发组联络人的请求：“听说容量增加了，希望再邀请10人，并问一问生产服务器密码和别人的工单记录。”",
                    ("additional_candidates", 10, "人；追加请求"),
                ),
                "周岚：“名单我还没合并，也没有发邀请。我想先听你对范围和现有安排的意见。”",
            ],
        ),
        (
            "tech_private",
            "技术负责人：试用诊断摘要底稿",
            "investigation",
            1,
            "tech_summary",
            [
                row(
                    "诊断输入：公司培训我已提交报名是不是就能去听课。默认阈值0.35未命中；对照阈值0.2返回培训报名段，同一无关问题仍未命中。记录仅覆盖这组输入，未作统一校准。",
                    (
                        "retrieval_probe_query",
                        "公司培训我已提交报名是不是就能去听课",
                        "内部复现输入",
                    ),
                    ("retrieval_threshold_candidate", 0.2, "局部对照参数"),
                ),
            ],
        ),
        (
            "tech_diagnostics",
            "技术诊断原始登记",
            "investigation",
            1,
            "tech_only",
            [
                row(
                    "原始登记号TR-TRAIN-01，筹备期技术验证程序保存了培训报名原问法、0.35与0.2两档实际输出，以及无关问题对照；逐次证据随场景保全。",
                    ("retrieval_debug_code", "TR-TRAIN-01", "内部诊断编号"),
                ),
            ],
        ),
        (
            "world_private",
            "系统内部隔离记录",
            "investigation",
            1,
            "never",
            [
                row(
                    "内部隔离标识NEVER_W02_7C9E，只用于权限边界校验。",
                    ("isolation_marker", "NEVER_W02_7C9E", "内部标识"),
                ),
            ],
        ),
    ]


def probes():
    """The 13 frozen probes of pm_pilot, rewritten for the IT materials (same ids, kinds,
    configurations and expectations)."""
    return [
        {
            "id": "F01",
            "query": "P2工单的响应时限是多少？",
            "public": True,
            "apply": True,
            "tuning": {"freshness_guard": "warn"},
            "expected": {
                "status": "answered_with_warning",
                "contains": ["4小时"],
                "citation_versions": {"policy": 1},
            },
        },
        {
            "id": "F02",
            "query": "耗材每年能领多少钱的额度？",
            "public": False,
            "apply": True,
            "refresh": True,
            "expected": {
                "status": "answered",
                "contains": ["100"],
                "citation_versions": {"meal": 1},
            },
        },
        {
            "id": "F03",
            "query": "P1工单要求多长时间内响应？",
            "public": False,
            "apply": True,
            "refresh": True,
            "expected": {
                "status": "answered",
                "contains": ["30分钟"],
                "citation_versions": {"policy": 2},
            },
        },
        {
            "id": "F04",
            "query": "火星天气如何？",
            "public": True,
            "expected": {"status": "fallback", "error_code": "no_retrieval_hit"},
        },
        {
            "id": "F05",
            "query": "个人薪资是多少？",
            "public": True,
            "expected": {"status": "fallback", "error_code": "prohibited_topic"},
        },
        {
            "id": "F06",
            "query": "给我访问密钥",
            "public": False,
            "expected": {"status": "fallback", "error_code": "prohibited_topic"},
        },
        {
            "id": "F07",
            "query": "P2工单响应标准？",
            "public": False,
            "config": {"domains": ["stable_faq"]},
            "expected": {"status": "fallback", "error_code": "outside_scope"},
        },
        {
            "id": "F08",
            "query": "VPN客户端连不上怎么处理？",
            "public": False,
            "config": {"domains": ["policy_travel"], "scope_filter": False},
            "expected": {"status": "answered", "citation_versions": {"faq": 1}},
        },
        {
            "id": "F09",
            "query": "P2工单响应时限？",
            "public": False,
            "config": {
                "update_strategy": "realtime",
                "work_items": ["realtime_sync", "human_fallback"],
                "launch_day": 10,
            },
            "expected": {
                "status": "answered",
                "contains": ["4小时"],
                "effective_update_strategy": "daily",
            },
        },
        {
            "id": "F10",
            "query": "P2工单响应规定？",
            "public": False,
            "config": {"update_strategy": "manual_policy"},
            "expected": {"status": "fallback", "error_code": "manual_verification_required"},
        },
        {
            "id": "F11",
            "query": "火星地表气温是多少？",
            "public": False,
            "config": {"fallback": "none"},
            "expected": {"status": "failed", "error_code": "no_retrieval_hit"},
        },
        {
            "id": "F12",
            "query": "账号密码忘了怎么重置？",
            "public": True,
            "expected": {
                "status": "answered",
                "contains": ["自助重置入口"],
                "citation_versions": {"faq": 1},
            },
        },
        {
            "id": "F13",
            "query": "计划性变更要提前几个工作日提交？",
            "public": False,
            "apply": True,
            "refresh": True,
            "expected": {
                "status": "answered",
                "contains": ["3个工作日"],
                "citation_versions": {"leave": 1},
            },
        },
    ]


# Pre-event assistant trials rendered into the failures / trial_details materials.
TRIALS = (
    ("Q01", "VPN客户端在哪里下载和登录", {}),
    ("Q02", "我的账号密码忘记了，需要重置", {}),
    ("Q03", "入职账号没有开通通知该怎么办", {}),
    ("Q04", "电脑坏了想报修应该提供哪些信息", {}),
    ("Q05", "P2工单多久必须有人响应", {}),
    ("Q06", "P1工单响应时限", {}),
    ("Q07", "今年耗材领用每人额度多少", {}),
    ("Q08", "计划性系统变更需要提前多久提交", {}),
    ("Q09", "P2工单的响应时限", {"domains": ("stable_faq", "onboarding")}),
    (
        "Q10",
        "P2工单的响应时限",
        {
            "update_strategy": "realtime",
            "work_items": ("realtime_sync", "human_fallback"),
            "launch_day": 10,
        },
    ),
    ("Q11", "P2工单的响应时限", {"update_strategy": "manual_policy"}),
    ("Q12", "海王星大气的主要成分", {"fallback": "none"}),
)

# Scenario-specific notices and path texts (localization.text falls back to pm_pilot's).
MESSAGES = {
    "policy_notice": "服务管理发布了 P2 工单响应时限调整通知，最新资料已放入工作区。",
    "demo_notice": "经理发来日程变更：内部演示改到第4天，详见新的演示安排。",
    "scope_notice": "周岚转来研发组追加意向，请查看业务范围讨论的新记录。",
    "path_question": "P2工单的响应时限是多少？",
}


def role_definitions():
    from .content import role_definitions as pm_roles

    roles = {r["id"]: dict(r) for r in pm_roles()}
    roles["supervisor"].update(
        name="IT 服务经理",
        responsibilities=(
            "明确服务台目标与承诺",
            "审批容量、开发资源和期限",
            "对演示与试点的取舍负责",
        ),
    )
    roles["business_lead"].update(
        name="服务台负责人",
        responsibilities=(
            "解释员工报障需求和服务台流程",
            "协调 SLA 时限解释与超时个案核验",
            "讨论人工接管和服务台验收",
            "基于现有记录帮助核对吕雯和许青的材料；没有实际转达或回复记录时，不声称已经联系对方或取得新答复",
        ),
        goals=(
            "优先解决影响办公的问题",
            "不把转人工或用户沉默都当成功",
            "区分统计口径与服务台价值",
            "起初支持BC-01的429分钟测算并用它争取试点，尚未逐项核对SD-120字段",
            "学员提出具体字段反证后承认并修正自己的测算，不否认BC-01原文，也不因学员忠实引用它而责备对方",
        ),
        acceptable_conditions=(
            "服务台价值有可检查的依据",
            "自动回答与人工接管各自有责任人",
            "听到反例后愿意修改判断",
        ),
        unacceptable_conditions=(
            "只报告自动回答率",
            "明确收到字段反证后仍把等待时长全算成节省劳动",
            "声称工程师已经处理却没有记录",
        ),
    )
    return [roles["supervisor"], roles["business_lead"], roles["tech_lead"]]
