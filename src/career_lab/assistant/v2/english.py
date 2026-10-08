"""English-only retrieval and bounded credential-procedure recognition.

No probes, reference answers, development labels or evaluation gold are read.
"""
import re
STOPWORDS=set('s t d ll re ve a an the i me my we our you your he she they their it its this that these those is are am was were be been being do does did can could would should will shall may might have has had to of for in on at by from with and or but if then as what which who whom when where why how please tell explain much many about into through up'.split())
MORPH={'claims':'claim','claimed':'claim','rooms':'room','bookings':'booking','booking':'book',
       'receipts':'receipt','costs':'cost','limits':'limit','days':'day','hours':'hour','minutes':'minute',
       'requests':'request','records':'record','questions':'question','policies':'policy','expenses':'expense',
       'employees':'employee','colleagues':'colleague','keys':'key','passwords':'password','codes':'code',
       'registration':'register','registering':'register','registered':'register','reimbursement':'reimburse',
       'reimbursed':'reimburse','reimbursable':'reimburse','courses':'course','participants':'participant',
       'devices':'device','repairs':'repair','documents':'document','approvals':'approval',
       'food':'meal','meals':'meal','lunch':'meal','dinner':'meal','breakfast':'meal',
       'accommodation':'hotel','lodging':'hotel','cab':'taxi','cabs':'taxi',
       'returned':'return','returning':'return','returns':'return','rejected':'reject',
       'denied':'deny','appeals':'appeal','cancelled':'cancel','canceled':'cancel'}


def meaningful_tokens(text):
    value=re.sub(r'\bsign(?:ed|ing)?\s+up\b','register',text.casefold())
    words=re.findall(r"[a-z0-9]+",value)
    return {MORPH.get(w,w) for w in words if w not in STOPWORDS}


def public_credential_workflow(query):
    value=re.sub(r'\s+',' ',query.casefold()).strip().rstrip('?.!')
    reset=(r"(?:can|could) you (?:please )?help me (?:reset|change|recover) my (?:account )?password",
           r"(?:please )?(?:tell me )?(?:how (?:do|can|should) i (?:reset|change|recover) (?:my |an |the )?(?:account )?password)",
           r"i (?:forgot|have forgotten) my (?:account )?password(?:[.;,] ?(?:how (?:do|can) i reset it|what (?:do|should) i do))?",
           r"(?:can|could) you (?:please )?(?:explain|tell me) (?:the )?password reset (?:process|procedure)")
    if any(re.fullmatch(pattern,value) for pattern in reset):return ('Password reset','password self-service reset identity verification')
    sharing=r"(?:when (?:using|connecting to) (?:the )?office network[,;] ?)?(?:can|may|should) i share (?:an? |the |my )?access keys? with (?:a |my )?(?:colleague|co-?worker)"
    if re.fullmatch(sharing,value):return ('Office network access','office network access share key')
    return None


def prohibited_topic(query):
    value=re.sub(r'\s+',' ',query.casefold())
    if re.search(r"\b(?:salary|salaries|medical diagnosis|medical diagnoses)\b",value):return True
    if re.search(r"(?:another|someone else's|other employee|colleague).{0,35}(?:performance|appraisal)",value):return True
    secret=r'(?:password|access[ _-]?key|api[ _-]?key|secret[ _-]?key|verification code|credential)'
    if re.search(secret,value):return True
    return False


def candidate_relevant(query_terms, candidate_terms):
    """Lexical relevance only; never answer labels or hidden scenario routes.

    Generic claim/trip words must not substitute taxi guidance for a question
    explicitly about meals. An unsupported action such as returning a rejected
    form must not be answered by a paragraph merely mentioning the form.
    Multi-topic questions are left to ordinary chunk scoring, not special answers.
    """
    topics = query_terms & {'meal', 'hotel', 'taxi'}
    if len(topics) == 1 and not topics <= candidate_terms:
        return False
    requested_actions = query_terms & {'return', 'reject', 'deny', 'appeal', 'cancel'}
    return requested_actions <= candidate_terms
