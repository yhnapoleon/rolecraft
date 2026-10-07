"""English-only retrieval and bounded credential-procedure recognition.

No probes, reference answers, development labels or evaluation gold are read.
"""
import re
STOPWORDS=set('a an the i me my we our you your he she they their it its this that these those is are am was were be been being do does did can could would should will shall may might have has had to of for in on at by from with and or but if then as what which who whom when where why how please tell explain much many about into through up'.split())
MORPH={'claims':'claim','claimed':'claim','rooms':'room','bookings':'booking','booking':'book',
       'receipts':'receipt','costs':'cost','limits':'limit','days':'day','hours':'hour','minutes':'minute',
       'requests':'request','records':'record','questions':'question','policies':'policy','expenses':'expense',
       'employees':'employee','colleagues':'colleague','keys':'key','passwords':'password','codes':'code',
       'registration':'register','registering':'register','registered':'register','reimbursement':'reimburse',
       'reimbursed':'reimburse','reimbursable':'reimburse','courses':'course','participants':'participant',
       'devices':'device','repairs':'repair','documents':'document','approvals':'approval'}


def meaningful_tokens(text):
    words=re.findall(r"[a-z0-9]+",text.casefold())
    return {MORPH.get(w,w) for w in words if w not in STOPWORDS}


def public_credential_workflow(query):
    value=re.sub(r'\s+',' ',query.casefold()).strip().rstrip('?.!')
    reset=(r"(?:please )?(?:tell me )?(?:how (?:do|can|should) i (?:reset|change|recover) (?:my |an |the )?(?:account )?password)",
           r"i (?:forgot|have forgotten) my (?:account )?password(?:[.;,] ?(?:how (?:do|can) i reset it|what (?:do|should) i do))?",
           r"(?:can|could) you (?:please )?(?:explain|tell me) (?:the )?password reset (?:process|procedure)")
    if any(re.fullmatch(pattern,value) for pattern in reset):return ('Password reset','password self-service reset identity verification')
    sharing=r"(?:when (?:using|connecting to) (?:the )?office network[,;] ?)?(?:can|may|should) i share (?:an? |the |my )?access key with (?:a |my )?(?:colleague|coworker)"
    if re.fullmatch(sharing,value):return ('Office network access','office network access share key')
    return None


def prohibited_topic(query):
    value=re.sub(r'\s+',' ',query.casefold())
    if re.search(r"\b(?:salary|salaries|medical diagnosis|medical diagnoses)\b",value):return True
    if re.search(r"(?:another|someone else's|other employee|colleague).{0,35}(?:performance|appraisal)",value):return True
    secret=r'(?:password|access[ _-]?key|api[ _-]?key|secret[ _-]?key|verification code|credential)'
    if re.search(secret,value):return True
    return False
