/* ISY5002 前端原型 · 演示数据
   全部为「原型演示数据，未审核 D2」。ID 以 DEMO_ 开头。
   保留 v0.8 的四个练习参数：容量 30 人、索引延迟 24 小时、可用开发 3 人天、实时同步需 5 人天。
   公司、人物、政策文字、事件触发、变体均为虚构可替换设定，不是真实客户事实或 gold。 */

window.DEMO = (function () {
  const SCENARIO = {
    id: 'DEMO_T1',
    version: 'DEMO_T1@v1',
    title: 'Open a knowledge-assistant pilot within one week',
    company: 'Northwind Retail Ops (fictional)',
    role: 'AI Product Manager, Internal Tools',
    expectedMinutes: '20–30',
    params: { capacity: 30, indexDelayHours: 24, devDaysAvailable: 3, devDaysRealtime: 5 },
    variants: [
      { id: 'DEMO_V1', title: 'Variant A · Policy revised mid-pilot', desc: 'HR reissues the expense policy on day 3 of the pilot. Decide how the assistant and your update policy respond.', status: '模拟变体，未审核' },
      { id: 'DEMO_V2', title: 'Variant B · Audience doubles', desc: 'Sales asks to add 35 more users before the demo. Capacity is unchanged. Decide who enters and who waits.', status: '模拟变体，未审核' },
    ],
  };

  /* ---------- 材料（带版本、可引用段落） ---------- */
  const MATERIALS = [
    {
      id: 'DEMO_M01', title: 'Pilot request from Priya (manager)', kind: 'Message', owner: 'Priya Nair', versions: [
        { v: 'v1', date: 'Day 0, 09:12', paras: [
          { id: 'M01§1', text: 'We have budget approval to pilot the internal knowledge assistant. I want a first group of staff using it within one week. Please own the plan.' },
          { id: 'M01§2', text: 'Deliverable: a pilot plan I can forward to Ops leadership. It must say who gets access, what the assistant is allowed to answer, how we keep it accurate, and how we know it worked.' },
          { id: 'M01§3', text: 'Do not promise anything to the wider company yet. Talk to Daniel (tech) and Mei (HR Ops) before you commit numbers.' },
        ]},
      ],
    },
    {
      id: 'DEMO_M02', title: 'Knowledge assistant — product note', kind: 'Product doc', owner: 'Internal Tools', versions: [
        { v: 'v1', date: 'Day −6', paras: [
          { id: 'M02§1', text: 'The assistant answers staff questions by retrieving passages from approved internal documents and composing a short reply with citations. It does not browse the web and does not learn from chats.' },
          { id: 'M02§2', text: 'Approved sources today: HR policy handbook, IT service FAQ, expense guidelines, facilities FAQ. Sources are added by the Internal Tools team on request.' },
          { id: 'M02§3', text: 'Answer scope can be restricted per pilot group. When a question falls outside the allowed scope the assistant can be configured to refuse, to answer with a warning, or to hand off to a human queue.' },
          { id: 'M02§4', text: 'Each reply can show the index snapshot date. This is optional and off by default.' },
        ]},
      ],
    },
    {
      id: 'DEMO_M03', title: 'Platform capacity and operations note', kind: 'Ops doc', owner: 'Daniel Koh', versions: [
        { v: 'v1', date: 'Day −2', paras: [
          { id: 'M03§1', text: 'The current deployment is sized for 30 concurrent named users. Above that, response times degrade and the rate limiter starts rejecting requests. Raising the limit needs a new instance and a cost approval.' },
          { id: 'M03§2', text: 'The document index is rebuilt once a night. A change published to a source document appears in answers after the next rebuild, so up to 24 hours later.' },
          { id: 'M03§3', text: 'Real-time synchronisation (changes visible within minutes) is technically possible but is not built. Estimate: 5 developer-days, including testing.' },
          { id: 'M03§4', text: 'Retrieval logs record the question, the retrieved passages, the index snapshot and the configuration version. Logs are kept for 90 days.' },
        ]},
      ],
    },
    {
      id: 'DEMO_M04', title: 'Engineering availability this sprint', kind: 'Planning note', owner: 'Daniel Koh', versions: [
        { v: 'v1', date: 'Day −1', paras: [
          { id: 'M04§1', text: 'Internal Tools has 3 developer-days free in the coming sprint. Everything else is committed to the payroll integration.' },
          { id: 'M04§2', text: 'Small configuration changes (scope, warnings, hand-off queue) cost hours, not days. New source ingestion costs about half a day per source.' },
          { id: 'M04§3', text: 'Any work beyond 3 developer-days must be approved by Ops leadership and would push the payroll integration.' },
        ]},
      ],
    },
    {
      id: 'DEMO_M05', title: 'HR policy handbook — expenses chapter', kind: 'Policy', owner: 'Mei Lin', versions: [
        { v: 'v1', date: 'Day −40', paras: [
          { id: 'M05§1', text: 'Home-office equipment: staff may claim up to SGD 300 per calendar year for approved equipment, with receipts.' },
          { id: 'M05§2', text: 'Claims are submitted through the expense portal and approved by the line manager.' },
          { id: 'M05§3', text: 'Annual leave: new employees receive 14 days per year, pro-rated in the first year.' },
        ]},
        { v: 'v2', date: 'Day 1, 14:00', paras: [
          { id: 'M05§1', text: 'Home-office equipment: staff may claim up to SGD 500 per calendar year for approved equipment, with receipts. Claims above SGD 300 need Finance sign-off.' },
          { id: 'M05§2', text: 'Claims are submitted through the expense portal and approved by the line manager.' },
          { id: 'M05§3', text: 'Annual leave: new employees receive 14 days per year, pro-rated in the first year.' },
        ]},
      ],
    },
    {
      id: 'DEMO_M06', title: 'IT service FAQ (stable)', kind: 'FAQ', owner: 'IT Service Desk', versions: [
        { v: 'v1', date: 'Day −120', paras: [
          { id: 'M06§1', text: 'Password reset: use the self-service portal; a reset link is sent to your recovery phone within 5 minutes.' },
          { id: 'M06§2', text: 'VPN: install the corporate client from the software centre. Access is granted automatically to all staff.' },
          { id: 'M06§3', text: 'Laptop replacement cycle: every 4 years, or earlier on hardware failure confirmed by the service desk.' },
        ]},
      ],
    },
  ];

  /* ---------- 三位同事：角色卡与预设分支 ---------- */
  const COLLEAGUES = [
    {
      id: 'DEMO_C_MGR', name: 'Priya Nair', short: 'manager', role: 'Head of Internal Tools · your manager', initials: 'PN', tone: 'wants momentum',
      knows: 'Business goal, the one-week ask, what leadership will read.',
      unknown: 'Technical limits, exact capacity, engineering hours.',
      questions: [
        { id: 'q_mgr_goal', text: '这次试点想达成什么？', answer: 'Leadership wants proof that staff get correct answers faster than asking HR or IT by email. If the pilot goes well we expand in the next quarter. If it produces wrong answers on policy, we lose the budget.', fact: 'Goal: prove correct answers faster than email; wrong policy answers are the main risk.' },
        { id: 'q_mgr_who', text: '第一批用户你想给谁？', answer: 'I would love the whole Ops floor, about 80 people. But I trust your judgement on what is safe. Pick a group that gives us a clear signal.', fact: 'Manager preference: Ops floor (~80 people); accepts a smaller group if justified.' },
        { id: 'q_mgr_deadline', text: '一周的期限能不能动？', answer: 'The date is tied to the Ops leadership review. If you need more time, tell me what you would deliver on time and what you would need extra for. I can argue for it if the reasoning is written down.', fact: 'Deadline is tied to leadership review; conditional delay possible with written reasoning.' },
        { id: 'q_mgr_capacity', text: '系统能支持多少人？', answer: 'I do not know the technical limits. Daniel owns the platform, ask him.', fact: null, refer: 'DEMO_C_TECH' },
        { id: 'q_mgr_answer', text: '直接告诉我方案该怎么写', answer: 'That is the job I am asking you to do. Show me the constraints you found and the trade-off you chose; I will react to that.', fact: null, boundary: true },
      ],
    },
    {
      id: 'DEMO_C_TECH', name: 'Daniel Koh', short: 'tech lead', role: 'Tech lead · Internal Tools', initials: 'DK', tone: 'protects the team',
      knows: 'Platform limits, indexing behaviour, engineering availability and implementation estimates.',
      unknown: 'Which policies matter most to staff, HR priorities.',
      questions: [
        { id: 'q_tech_capacity', text: '平台现在能支持多少并发用户？', answer: 'Thirty named users. That is what the instance is sized for. Above that the rate limiter kicks in and people see errors. See my ops note if you want the detail.', fact: 'Capacity: 30 concurrent named users; beyond that requests are rejected.', cite: 'M03§1' },
        { id: 'q_tech_index', text: '文档更新后多久能在回答里生效？', answer: 'We rebuild the index nightly. Worst case a change shows up 24 hours after it is published. Until then the assistant will confidently quote the old text.', fact: 'Index rebuilds nightly; changes can lag up to 24 hours; old text is quoted until then.', cite: 'M03§2' },
        { id: 'q_tech_realtime', text: '能不能做成实时同步？', answer: 'Possible, not built. Five developer-days including tests. I have three free this sprint, and those three also have to cover any pilot configuration work.', fact: 'Real-time sync: 5 developer-days; only 3 available this sprint.', cite: 'M03§3' },
        { id: 'q_tech_effort', text: '改范围、加提醒、接人工兜底要多少工时？', answer: 'Hours each. Scope restriction is a setting. The index-date warning is a flag. The hand-off queue exists, it needs a mailbox and about half a day to wire up.', fact: 'Config changes cost hours; hand-off queue ~0.5 developer-day.', cite: 'M04§2' },
        { id: 'q_tech_raise', text: '容量能不能直接加到 80？', answer: 'Not this week. A bigger instance needs a cost approval from Ops leadership and a day to provision and test. Do not write 80 into a plan unless that approval exists.', fact: 'Raising capacity needs cost approval plus ~1 day; not available this week.', cite: 'M03§1' },
        { id: 'q_tech_hr', text: 'HR 最关心哪些政策？', answer: 'Ask Mei. I only see the logs, not what people actually need.', fact: null, refer: 'DEMO_C_BIZ' },
      ],
    },
    {
      id: 'DEMO_C_BIZ', name: 'Mei Lin', short: 'business owner', role: 'HR Operations lead · business owner', initials: 'ML', tone: 'afraid of wrong answers',
      knows: 'Which policies are stable, which are changing this week, who asks what.',
      unknown: 'Platform capacity, engineering effort.',
      questions: [
        { id: 'q_biz_stable', text: '哪些政策是稳定的，可以放心开放？', answer: 'Leave entitlements, the IT FAQ and the facilities FAQ have not changed in a year. Those I am comfortable with.', fact: 'Stable: leave entitlements, IT FAQ, facilities FAQ (unchanged for a year).' },
        { id: 'q_biz_changing', text: '最近有什么政策在改？', answer: 'The home-office equipment cap. Finance is raising it this week and I will publish the new handbook chapter as soon as it is signed. If the assistant tells someone the old number after that, I will get the complaint.', fact: 'Expense cap is changing this week; new handbook chapter to be published; stale answers are the owner\'s top worry.' },
        { id: 'q_biz_users', text: '你建议先给谁用？', answer: 'The Ops floor asks the most questions, but the new-joiner cohort of about 20 people asks the simplest ones. If you want a safe signal, start with them.', fact: 'Suggested first group: new-joiner cohort (~20 people) with simple, stable questions.' },
        { id: 'q_biz_fallback', text: '答不准的时候你希望怎么处理？', answer: 'Send it to the HR shared mailbox with the original question. We answer within a day. Please do not let it guess.', fact: 'Fallback preference: hand off to HR shared mailbox, no guessing.', timeoutOnce: true },
        { id: 'q_biz_capacity', text: '系统能撑多少人？', answer: 'No idea, that is Daniel\'s side.', fact: null, refer: 'DEMO_C_TECH' },
      ],
    },
  ];

  /* ---------- 测试查询与模拟回答规则 ---------- */
  const QUERIES = [
    { id: 'DEMO_Q1', kind: 'stable', label: 'Stable FAQ', text: 'How many annual leave days does a new employee get?', source: 'DEMO_M05', para: 'M05§3' },
    { id: 'DEMO_Q2', kind: 'changed', label: 'Recently changed policy', text: 'What is the claim limit for home-office equipment?', source: 'DEMO_M05', para: 'M05§1' },
    { id: 'DEMO_Q3', kind: 'oos', label: 'Out of scope', text: 'What is the refund policy for enterprise customers?', source: null, para: null },
    { id: 'DEMO_Q4', kind: 'stable', label: 'Stable FAQ', text: 'How do I reset my password?', source: 'DEMO_M06', para: 'M06§1' },
    { id: 'DEMO_Q5', kind: 'oos', label: 'Out of scope', text: 'What is my manager\'s salary band?', source: null, para: null },
  ];

  const SCOPES = [
    { id: 'all', label: 'All approved sources', docs: ['DEMO_M05', 'DEMO_M06'] },
    { id: 'stable', label: 'Stable sources only (leave, IT FAQ)', docs: ['DEMO_M06'], stableParas: ['M05§3'] },
    { id: 'hr', label: 'HR handbook only', docs: ['DEMO_M05'] },
  ];

  const FALLBACKS = [
    { id: 'guess', label: 'Answer anyway (no hand-off)' },
    { id: 'refuse', label: 'Refuse out-of-scope questions' },
    { id: 'handoff', label: 'Hand off to HR shared mailbox' },
  ];

  /* ---------- 九字段 ---------- */
  const FIELDS = [
    { id: 'users', label: 'User scope', hint: 'Who enters the pilot, who waits, and why.' },
    { id: 'knowledge', label: 'Knowledge scope', hint: 'Which sources and question types are allowed.' },
    { id: 'capacity', label: 'Capacity', hint: 'Number of users or a limit, consistent with the platform.' },
    { id: 'update', label: 'Update policy', hint: 'How changes reach answers and how the delay is disclosed.' },
    { id: 'fallback', label: 'Fallback', hint: 'What happens on uncertain, out-of-scope or risky questions.' },
    { id: 'work', label: 'Work items', hint: 'Concrete actions, owners and effort; extra resources marked as conditional.' },
    { id: 'tests', label: 'Acceptance tests', hint: 'Real queries you ran and the risks they cover.' },
    { id: 'metrics', label: 'Success measures', hint: 'What you will observe and how you will read it.' },
    { id: 'exit', label: 'Exit conditions', hint: 'When to pause, narrow or delay, and what happens next.' },
  ];

  /* ---------- 演示用示例填法（两种合理结局，均非 gold） ---------- */
  const SAMPLE_PLANS = {
    A: {
      title: 'Ending A · Limited launch on stable knowledge',
      users: 'New-joiner cohort (about 20 people) plus 5 HR Ops staff as observers. Ops floor waits for the next wave.',
      knowledge: 'Leave entitlements and the IT service FAQ only. The expenses chapter is excluded until the revised version has been indexed.',
      capacity: '25 named users, under the 30-user platform limit.',
      update: 'Nightly index; every reply shows the index snapshot date. Changed policies are excluded from scope for 24 hours after publication.',
      fallback: 'Out-of-scope and low-confidence questions are handed off to the HR shared mailbox with the original question.',
      work: 'Restrict scope (hours, Daniel); enable index-date warning (hours); wire hand-off mailbox (0.5 day); brief the cohort (Mei). Total under 1 developer-day.',
      tests: 'Re-ran the leave and password queries after scope change: correct with citation. Ran the expense-cap query: excluded and handed off. Ran the refund query: handed off.',
      metrics: 'Share of questions answered with a citation; hand-off rate; complaints about wrong policy answers (target: zero in week one).',
      exit: 'Pause if any wrong policy answer is reported or if hand-off rate exceeds 40%. Expand scope only after the revised expenses chapter is indexed and re-tested.',
    },
    B: {
      title: 'Ending B · Conditional delay for real-time sync',
      users: 'Ops floor (about 80 people) in two waves of 30, starting after real-time sync is live.',
      knowledge: 'All approved sources including the expenses chapter, because the expense cap is the most asked changing policy.',
      capacity: 'Wave 1: 30 users at the current limit; wave 2 only after instance upgrade approval.',
      update: 'Real-time sync so revised policies appear within minutes; index date shown on each reply.',
      fallback: 'Hand off to HR shared mailbox; refuse questions outside approved sources.',
      work: 'Real-time sync: 5 developer-days, exceeds the 3 available. Conditional on Ops leadership approving 2 extra days and a one-week delay. If not approved, fall back to Ending A scope.',
      tests: 'Expense-cap query returned the old SGD 300 after the v2 publication; this is the failure the delay avoids. Leave and password queries correct.',
      metrics: 'Time from policy publication to correct answer; citation rate; complaints.',
      exit: 'If approval is not given by day 3, launch the stable-scope pilot instead. Pause if wrong-answer complaints appear.',
    },
  };

  const INTAKE_EXAMPLES = [
    { id: 'ex1', text: 'I want to practise opening an internal policy Q&A assistant for staff, as a pilot, within a week.' },
    { id: 'ex2', text: 'Our HR team gets the same questions by email every day. I want to test a knowledge assistant with a small group first.' },
    { id: 'ex3', text: 'Recommend products to shoppers on a retail app using purchase history.' },
  ];

  const AUTHORISED_TEXT_SAMPLE = 'Northwind Retail Ops is a fictional 400-person retail operations company with an HR Ops team of 6 and an Internal Tools team of 4. Staff currently ask HR and IT questions by email and wait about one day for replies.';

  return { SCENARIO, MATERIALS, COLLEAGUES, QUERIES, SCOPES, FALLBACKS, FIELDS, SAMPLE_PLANS, INTAKE_EXAMPLES, AUTHORISED_TEXT_SAMPLE };
})();
