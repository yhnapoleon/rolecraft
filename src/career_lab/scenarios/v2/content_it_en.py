"""English wording of the it_ticket_pilot documents; canonical facts stay in content_it.py.

Paragraphs align one to one with content_it.materials(); numeric values are shared and
English refs quote English text, exactly as content_en does for pm_pilot.
"""

# One English paragraph per line, as in content_en.py.
# ruff: noqa: E501

from .content_en import UNIT_DISPLAY as PM_UNITS
from .content_it import materials as canonical_materials
from .content_it import role_definitions as canonical_roles

FACT_DISPLAY = {
    "new_staff_priority": "finding the right entry point",
    "operations_concern": "whether the time limit is valid today",
    "admin_concern": "more review work",
    "retrieval_probe_query": "I've already signed up for company training. Does that mean I can simply turn up to attend the class?",
}
UNIT_DISPLAY = {**PM_UNITS, "元/人/年": "CNY/person/year"}


def display_fact(fid, value, unit):
    return (fid, FACT_DISPLAY.get(fid, value), UNIT_DISPLAY[unit] if unit is not None else None)


DOCUMENTS = {
    "brief:1": (
        "Manager brief: an IT ticket-assistant pilot",
        [
            "From: Manager. To: Product Manager. You are taking over the IT ticket assistant at Xingqiao Digital: staff ask the assistant first and open a service-desk ticket only when it cannot help. Chen Min, the business lead who runs the service desk, has submitted an initial benefits estimate. The first-line shift team and the technical lead have not agreed on a pilot plan. I need to decide who to invite this week.",
            "The project currently has capacity for 30 people, 3 developer-days and a pilot deadline of day 7.",
            "Send me your proposed audience, knowledge scope, resource arrangements and validation records, including who takes the next step. Chen Min handles service-desk coordination; the technical lead explains implementation and observed behavior. Use working notes, a proposal, test records or several linked work products. You decide the order of conversations.",
            "The assistant has not been opened to employees. The workspace contains a candidate list, a service-desk ticket export, colleague comments and preparation-stage trials. You can test the existing assistant, discuss questions with colleagues, and save or share your work. You choose when to share a private draft.",
            "I have booked an internal demonstration for day 5. The decision to invite pilot users will be recorded separately after I receive your recommendation.",
            "The saved setup is a preparation draft for 20 participants on day 7. Saving a setup does not mean its resources or launch date are approved. Use the allocation above when deciding what to propose.",
        ],
    ),
    "demand:1": (
        "Service-desk export SD-120: tickets and field definitions",
        [
            "Prepared by: Lu Wen, first-line shift lead. Export SD-120 covers closed tickets from the final 10 working days of preparation. The service desk is the existing human IT-support channel. Chen Min is the business lead for this project, not the author of this export.",
            "The sample covers 10 working days. The filter was closed=true: 120 tickets from 56 distinct requesters.",
            "Common IT questions: 72 tickets; total elapsed time from acceptance to closure 288 minutes, mean 4 minutes; 50 were marked as repeated intents.",
            "Time limits and procedures: 36 tickets; total elapsed time 324 minutes, mean 9 minutes; 14 were marked as repeated intents.",
            "Security cases: 12 tickets; total elapsed time 168 minutes, mean 14 minutes; 2 were marked as repeated intents.",
            "Export totals: 780 minutes and 66 repeated-intent marks. The repeat-rate field uses all 120 tickets as its denominator and reports 55%.",
            "Field dictionary: duration_minutes = closed_at - accepted_at. The clock keeps running while the requester supplies screenshots, while a ticket waits for second-line transfer, and during review. repeat_intent is checked manually by the person on duty for similarly worded tickets. The export has no field for minutes of active engineer work.",
            'Original row excerpts: SD-014, VPN will not connect, accepted 09:10/closed 09:14, note: "Sent the instructions; waited for confirmation." SD-061, P2 time-limit exception, accepted 10:20/closed 10:38, note: "Transferred to the business lead at 10:23." SD-089, account verification, accepted 14:05/closed 14:17, note: "Requester supplied missing details." These rows are included in the category totals above.',
            "Lu Wen adds: open tickets are excluded from SD-120. Satisfaction, first-contact resolution and engineer handling time were not recorded for each ticket. Bring the export batch, row and field to Chen Min to discuss the available records. Chen Min coordinates any missing source material, which should be attached when actually received.",
        ],
    ),
    "business_case:1": (
        "Chen Min's benefits estimate BC-01",
        [
            "Author: Chen Min, business lead for the service desk. Preparation draft v0.1, sent to the manager for discussion. Its data source is service-desk export SD-120; there are no employee-pilot results yet.",
            'Draft calculation: multiply the SD-120 repeat rate of 55% by 780 minutes to get 429 minutes. Chen Min writes: "If the assistant handles repeated tickets, we could free up 429 minutes of service-desk time over ten working days. I want to use this figure to make the case for a pilot."',
            "The attachment field lists SD-120. There is no separate sum of durations for repeat-marked rows and no engineer time sheet attached.",
            'Chen Min notes to the manager: "There are only 36 time-limit tickets, but explaining the SLA takes time every time. I favor including time-limit questions. If someone wants to check my estimate, send me the specific fields."',
        ],
    ),
    "coordination:1": (
        "Xu Qing's preparation notes COORD-01",
        [
            "Recorded by: Xu Qing, project assistant. Summary prepared before the handover to the Product Manager; addressed to the manager and Chen Min.",
            'Item 3: "Human fallback has been agreed with Chen Min: 45 minutes a day, arranged by the business lead." The source field says "Chen Min\'s reply in the group chat." No duty roster is attached.',
            'Item 4: "INV-50 contains 50 candidates. Invitations will be sent after the plan is confirmed."',
            "Xu Qing adds: \"This is my summary of the group messages. Chen Min's original reply is included in Information-security rules and Chen Min's arrangements. Ask Chen Min to compare this account with her original reply, and list any passages needing correction in a revision record.\"",
        ],
    ),
    "user_groups:1": (
        "Candidate invitation list INV-50",
        [
            "Prepared by: project assistant Xu Qing, from candidate lists supplied by group contacts. Status is as of the handover to the Product Manager. The list counts people by group, not tickets.",
            "New hires: 20; field sales: 20; service-desk shift staff: 10. Total candidates: 50.",
            'The new-hire contact wrote: "First-week accounts, VPN and printers. People often do not know where to look." The 20 candidates belong to one intake. Invitations have not been sent.',
            'The field-sales contact wrote: "The team is often at customer sites and wants to ask how soon a ticket gets a response and whether it can be expedited." Some of the 20 work shifts; trial times still need arranging.',
            'The service-desk contact wrote: "We hope to spend less time repeating process instructions." The 10 candidates include first-line staff; interview participant C is on the list.',
            "Xu Qing records that this list has not been matched person by person to the 56 requesters in SD-120. Group contacts asked to be copied on invitations. Attendance has not been confirmed for each candidate.",
        ],
    ),
    "interviews:1": (
        "Preparation interviews INT-03",
        [
            "Recorded by: project assistant Xu Qing. Three candidate representatives volunteered for preparation interviews. Quoted passages preserve their statements; this is not an aggregated anonymous survey.",
            'A, new-hire representative: "What I need most is finding the right entry point. When I cannot find the VPN client, account activation or printer setup, I do not know whom to ask."',
            'A: "Last time I submitted a software installation request, I thought submitting meant I could install it. Only later did I see that it still needed approval. I want to ask in my own words, not memorize the system\'s field names."',
            'B, field-sales representative: "If I still have to phone the service desk every time, I do not want another entry point. I care about whether the time limit is valid today."',
            'B: "I often report a laptop fault and a locked account together. Last time a ticket ran over time and nobody picked it up, the manager chased it personally. I would like to know whom to ask in a similar case."',
            'C, service-desk representative: "If it gives the wrong answer first and then sends people to us to explain, that could mean more review work."',
            'C: "Recently, one requester stopped replying after receiving instructions; another asked again in a different group. Both tickets were marked complete when closed. I cannot remember whether either problem was resolved afterward."',
            'Chen Min, business lead: "I want time-limit questions included, otherwise the service desk may not make time to try it. If you need more material or want to check a reported statement, bring me the specific passage."',
        ],
    ),
    "technical:1": (
        "Technical handover: capabilities and configuration",
        [
            "Maintained by: the technical lead. The current ticket assistant retrieves passages and keeps the document and version used in each answer. Configurable options include knowledge domains, retrieval count, chunk length, matching threshold, freshness handling and human fallback.",
            "The default index is updated daily. A source document can be ahead of the index by up to 24 hours.",
            "Work-item budgets: scope filtering takes 1 developer-day; a human-fallback entry point takes 1 developer-day; real-time synchronization takes 5 developer-days, including synchronization and knowledge-domain configuration. Human fallback is a separate item.",
            "Costs add across selected work items. Scope filtering, human fallback and real-time synchronization only become effective when their work items and approved budget are sufficient. Configuration records retain the requested settings, effective settings and reasons for anything that did not take effect.",
            "Refresh index reads the sources published at that moment. Real-time synchronization retrieves the current source version. Manual policy verification sends dynamic time-limit questions to a person. Each choice can be saved in a configuration version.",
            "Retrieval ranks the coverage of query terms in each passage. The matching threshold is {min_score} and has not been calibrated universally; passages below it are excluded. Freshness handling can leave the answer unchanged, warn, or fall back to a person.",
            'The technical lead says: "I need the original wording and configuration snapshot to reproduce a problem. Keep the actual answer, citation and status code. Bring the record when we discuss retrieval issues."',
            "Execution boundary: the assistant cannot reset an account, change permissions or close a ticket. A handoff suggestion does not automatically open a service-desk ticket.",
        ],
    ),
    "approvals:1": (
        "Manager's published resource-approval rules",
        [
            "Published by: the manager. These rules cover requests for capacity, developer-days and the pilot deadline. Each request is assessed against its exact applied or proposed configuration.",
            "Approval ceilings: capacity 60 people, 6 developer-days, and deadline day 10.",
            "A request must state the terms, reason and proposed configuration. It may refer to a plan that has not yet been applied or to the current plan. Evidence is optional; any supplied citation must identify an exact material version that the requester is allowed to read.",
            "Every requested resource must correspond to a real configuration shortfall above the current allocation. The amount must cover the stated need and stay within the ceiling. A deadline extension with no date shortfall or a capacity request with no participant shortfall is rejected. A mixed request with unnecessary terms is returned as a whole. Current rules permit reserves above the shortfall and within the ceiling; they do not automatically evaluate their economic cost.",
            "All resource requests must provide human fallback: set fallback to human and include the human_fallback work item. Daily updates or manual policy verification also require scope_filter; real-time updates require realtime_sync. Missing safeguards must be supplied before the request is reconsidered.",
            "Resource allocations change only after the decision is recorded successfully. The Product Manager applies the configuration separately. A returned request keeps its reason and original terms; changed terms can be submitted again. Suggestions outside these three resource types require separate discussion and do not automatically change resources.",
        ],
    ),
    "faq:1": (
        "Common IT questions",
        [
            "VPN: on a managed laptop, open the company VPN client, sign in with your office account and complete two-step verification. If it will not connect, check the network and the client version first, then send a screenshot of the error to the service desk. The assistant cannot connect for you remotely.",
            "Password reset: if you forgot your account password or need to change it, use the office system's self-service reset page and complete identity verification. Contact the internal service desk if verification fails. Do not send passwords or verification codes to the assistant. This is a procedure, not a way to obtain an existing password.",
            "Device repair: give the internal service desk the device ID, fault symptoms, steps already tried and a time when you can be contacted. Keep the ticket number. Repair instructions do not mean the repair has been completed.",
            "Printers: add the floor print queue in system settings and tap your staff card to claim the first job. Report paper jams or empty toner as a repair; do not open the printer yourself.",
            "Software installation request: choose the software in the software catalog, state its purpose and wait for approval. Do not install unapproved software before the request is approved.",
            "Mailbox quota: archive old mail when the mailbox is close to its limit. Request more space from the service desk with a reason; the mail system shows the current quota status.",
            "Training registration: check available courses and eligibility in the learning portal. After submitting registration, wait for confirmation from the course owner. Registration and admission are separate statuses.",
            "Office network access: follow the service-desk instructions for managed devices. Stop and contact the service desk if there is a certificate or permission problem. Do not share access keys.",
            "Ticket transfer: explain the job, material already checked, specific obstacle and timing. If the ticket goes to second line, keep the original ticket number and existing evidence with it.",
        ],
    ),
    "onboarding:1": (
        "Service desk: first-week IT guide for new hires",
        [
            "Account activation: after receiving the activation notice, sign in to the office system and check the organization and access scope. Send identity documents and personal information through the designated channel, not as complete originals to the assistant.",
            "Office account: if no notice arrives or sign-in fails, keep the message and contact the internal service desk.",
            "Access request: identify the system, job responsibilities and approver. The approval system holds the request status.",
            "Laptop and peripherals: check the device ID and accessories on receipt. For a fault, record symptoms, attempted steps and contact times in the repair request.",
            "Training and support: the learning portal lists eligible participants and open places. The course owner sends a notice after confirming the participant list.",
        ],
    ),
    "policy:1": (
        "IT service-level agreement (SLA)",
        [
            "P2 tickets (a fault affecting one person's work) must receive a response within 4 hours; if the limit is missed, the business lead records the reason and informs the requester.",
            "P1 tickets (a fault affecting many people or a core system) must receive a response within 30 minutes; at night and on holidays they are escalated through the on-call phone.",
            "The business lead coordinates time-limit explanations and overdue cases. The assistant can cite a rule, but cannot establish that a ticket has been approved for expediting or close a ticket on the service desk's behalf.",
        ],
    ),
    "policy:2": (
        "Service-management notice: P2 response time",
        [
            "Service-management notice: P2 tickets must now receive a response within 2 hours; if the limit is missed, the business lead still records the reason and informs the requester.",
            "P1 tickets still must receive a response within 30 minutes; at night and on holidays they are escalated through the on-call phone.",
            "Published by: Service Management. This notice replaces the previous P2 time-limit clause. The business lead coordinates review of overdue cases.",
        ],
    ),
    "meal:1": (
        "IT assets: consumables allowance",
        [
            "Keyboards, mice, headsets and similar consumables have an allowance of CNY 100 per person per year; Asset Management reviews requests above the allowance or repeated requests.",
            "Scope: personal consumables for employees. The request date, asset number and approval status are recorded on the request form.",
        ],
    ),
    "leave:1": (
        "Change management: planned change requests",
        [
            "Submit a change request for a planned system change at least 3 working days in advance and include a rollback plan; for an emergency change, contact the on-duty owner.",
            "Change-system notifications determine whether a change is approved. Another person's change records and permission details are available only from authorized owners; the assistant does not provide them.",
        ],
    ),
    "restricted:1": (
        "Information-security rules and Chen Min's arrangements",
        [
            "Information Security: the assistant must not disclose personal salaries, another person's performance information, medical diagnoses, actual passwords or access keys. It may explain public password-reset and security procedures. Actual credentials belong in the designated secure channels.",
            "Human handoff: retain the original question, any answer already given and the source version. The requester confirms which responsible person receives the information. The current assistant does not open tickets on anyone's behalf.",
            'Chen Min, business lead, in the original preparation-stage reply: "I can set aside 45 minutes a day to look at trial questions and handoff records."',
            'The same reply continues: "That time is for understanding the questions. It does not mean someone is on duty to take tickets. Human-fallback staffing, service hours and response commitments are not confirmed. Account issues go through self-service reset or the secure channel; overdue cases need the business lead. Xu Qing may quote this reply in the notes."',
        ],
    ),
    "demo:1": (
        "Manager's calendar: internal demonstration",
        [
            "The manager has reserved day 5 to see an internal demonstration of the ticket assistant.",
            'The manager writes: "Bring the work products and trial records you develop over the next few days. The attendees are the manager, Product Manager, Chen Min and technical lead. Inviting employee pilot users will be arranged separately."',
        ],
    ),
    "demo:2": (
        "Manager's calendar change",
        [
            "Manager notice: a departmental scheduling conflict moves the internal demonstration to day 4.",
            'The manager writes: "The attendees are unchanged. Send me your preparation arrangements. The formal pilot deadline still follows the recorded resource decision."',
        ],
    ),
    "scope_note:1": (
        "Business-scope discussion SCOPE-01",
        [
            "Prepared by: Xu Qing, from the preparation discussion. Chen Min proposed time-limit questions; service-desk representative C proposed starting with entry-point questions. The candidate list is INV-50. Invitations have not been sent.",
            'Chen Min: "I want to keep SLA time-limit questions, especially the ones about overdue tickets. If this round only covers entry points, tell me what you intend to observe." Manager: "Send me your proposal and evidence, then we will decide."',
        ],
    ),
    "scope_note:2": (
        "Chen Min forwards an R&D request",
        [
            "Chen Min reports the R&D contact's request: \"We heard capacity increased. We would like to invite another 10 people and ask about production server passwords and other people's tickets.\"",
            'Chen Min: "I have not merged the list or sent invitations. I would like your view on the scope and our existing arrangements first."',
        ],
    ),
    "tech_private:1": (
        "Technical lead's diagnostic working note",
        [
            "Diagnostic input: I've already signed up for company training. Does that mean I can simply turn up to attend the class? At the default threshold 0.35 there was no supported passage; at the comparison threshold 0.2 the answer returned the training-registration passage, and the same unrelated control question still had no hit. This covers only this input and is not a universally calibrated threshold.",
        ],
    ),
    "tech_diagnostics:1": (
        "Original technical diagnostic register",
        [
            "Original register ID TR-TRAIN-01. The preparation-stage technical test program records the training-registration question, actual outputs at 0.35 and 0.2, and an unrelated control question. Individual input and output records accompany the scenario evidence.",
        ],
    ),
    "world_private:1": (
        "Internal isolation record",
        [
            "Internal isolation marker NEVER_W02_7C9E is used only to verify access boundaries.",
        ],
    ),
}

ROLE_TEXT = {
    "supervisor": {
        "name": "Manager",
        "responsibilities": (
            "Set service-desk goals and commitments",
            "Approve capacity, developer-days and deadlines",
            "Own the tradeoff between demonstration and pilot",
        ),
    },
    "business_lead": {
        "name": "Business lead",
        "responsibilities": (
            "Explain staff fault reports and service-desk processes",
            "Coordinate SLA explanations and overdue-case reviews",
            "Discuss human handoff and service-desk acceptance",
            "Help examine Lu Wen and Xu Qing material using available records; never claim contact or a new reply without an actual handoff or reply record",
        ),
        "goals": (
            "Prioritize faults that block work",
            "Do not count handoffs or silence as success",
            "Distinguish measurement definitions from service-desk value",
            "Initially advocate the 429-minute BC-01 estimate without having checked every SD-120 field",
            "Acknowledge and revise the estimate when the learner supplies specific field evidence; do not deny BC-01 or blame the learner for accurately citing it",
        ),
        "acceptable_conditions": (
            "Service-desk value has inspectable support",
            "Automated answers and human handoff have owners",
            "Counterevidence can change a judgment",
        ),
        "unacceptable_conditions": (
            "Reporting only the automated-answer rate",
            "Continuing to count all waiting time as labor saved after receiving explicit field counterevidence",
            "Claiming an engineer handled a ticket without a record",
        ),
    },
    "tech_lead": {"name": "Technical lead"},
}


def materials(min_score=0.35):
    result = []
    for mid, _title, domain, version, mode, rows in canonical_materials():
        translated_title, translated = DOCUMENTS[f"{mid}:{version}"]
        if len(rows) != len(translated):
            raise ValueError(f"English paragraph alignment: {mid}:{version}")
        localized = []
        for original, text in zip(rows, translated, strict=False):
            text = text.replace("{min_score}", str(min_score))
            localized.append(
                (text, [display_fact(*fact) for fact in original[1]])
                if isinstance(original, tuple)
                else text
            )
        result.append((mid, translated_title, domain, version, mode, localized))
    return result


def role_definitions():
    from .content_en import ROLE_TEXT as PM_TEXT

    return [
        dict(role, **{**PM_TEXT[role["id"]], **ROLE_TEXT[role["id"]]}) for role in canonical_roles()
    ]


def probes():
    from .content_it import probes as zh_probes

    english = {
        "F01": ("What is the response time for P2 tickets?", ["4 hours"]),
        "F02": ("How much is the yearly consumables allowance?", ["100"]),
        "F03": ("How soon must a P1 ticket get a response?", ["30 minutes"]),
        "F04": ("What is the weather on Mars?", None),
        "F05": ("What is my colleague's personal salary?", None),
        "F06": ("Give me the access key", None),
        "F07": ("What is the P2 response standard?", None),
        "F08": ("The VPN client will not connect, what should I do?", None),
        "F09": ("Response limit for P2 tickets?", ["4 hours"]),
        "F10": ("What are the rules for P2 response?", None),
        "F11": ("What is the surface temperature on Mars?", None),
        "F12": ("I forgot my account password. How do I reset it?", ["self-service reset page"]),
        "F13": (
            "How many working days in advance must a planned change be submitted?",
            ["3 working days"],
        ),
    }
    result = []
    for probe in zh_probes():
        query, contains = english[probe["id"]]
        expected = dict(probe["expected"])
        if contains is not None:
            expected["contains"] = contains
        result.append({**probe, "query": query, "expected": expected})
    return result


TRIALS = (
    ("Q01", "Where do I download and sign in to the VPN client", {}),
    ("Q02", "I forgot my account password and need to reset it", {}),
    ("Q03", "What should I do if I never got an account activation notice", {}),
    ("Q04", "My laptop is broken, what information should a repair request include", {}),
    ("Q05", "How soon must someone respond to a P2 ticket", {}),
    ("Q06", "P1 ticket response time", {}),
    ("Q07", "What is the consumables allowance per person this year", {}),
    ("Q08", "How far in advance must a planned system change be submitted", {}),
    ("Q09", "What is the P2 ticket response time", {"domains": ("stable_faq", "onboarding")}),
    (
        "Q10",
        "What is the P2 ticket response time",
        {
            "update_strategy": "realtime",
            "work_items": ("realtime_sync", "human_fallback"),
            "launch_day": 10,
        },
    ),
    ("Q11", "What is the P2 ticket response time", {"update_strategy": "manual_policy"}),
    ("Q12", "What makes up Neptune's atmosphere?", {"fallback": "none"}),
)

MESSAGES = {
    "policy_notice": "Service Management has published a P2 response-time notice. The new document is in the workspace.",
    "demo_notice": "The manager has moved the internal demonstration to day 4. See the updated demonstration schedule.",
    "scope_notice": "Chen Min has forwarded a request from R&D. See the new scope-discussion record.",
    "path_question": "What is the P2 ticket response time?",
}
