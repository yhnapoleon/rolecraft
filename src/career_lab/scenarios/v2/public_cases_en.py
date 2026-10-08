"""English-only initial trial questions; actual answers come from Assistant.run."""
TRIALS_EN = (
    ('Q01','Where is the meeting-room booking page?',{}),
    ('Q02','I forgot my password. How do I reset it?',{}),
    ('Q03','My office account activation notice has not arrived. What should I do?',{}),
    ('Q04','My device has broken. What information should I include in a repair request?',{}),
    ('Q05','How much can I claim per night for a hotel on a domestic business trip?',{}),
    ('Q06','What is the taxi reimbursement limit per trip?',{}),
    ('Q07','What is the daily meal reimbursement amount?',{}),
    ('Q08','How early must I submit planned leave?',{}),
    ('Q09','What is the hotel reimbursement ceiling for domestic travel?',{'domains':('stable_faq','onboarding')}),
    ('Q10','What is the hotel reimbursement ceiling for domestic travel?',{'update_strategy':'realtime','work_items':('realtime_sync','human_fallback'),'launch_day':10}),
    ('Q11','What is the hotel reimbursement ceiling for domestic travel?',{'update_strategy':'manual_policy'}),
    ('Q12',"What makes up Neptune's atmosphere?",{'fallback':'none'}),
)
