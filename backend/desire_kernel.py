"""Pure, replayable desire/circadian dynamics. All clocks and evidence are inputs.

Based on the user's June implementation/circadian notes and September revision.
No model calls, filesystem, system clock, or actions belong in this module.
"""
from copy import deepcopy
import hashlib
import math
import re

REGISTRY = {
    'attachment': ('想念', 'reach_out'), 'curiosity': ('好奇', 'explore'),
    'expression': ('表达', 'voice'), 'duty': ('记挂', 'follow_through'),
    'roam': ('漫游', 'wander'), 'fatigue': ('疲劳', 'rest'),
    'libido': ('亲密', 'reach_out_intimate'), 'stress': ('压力', 'vent'),
    'craft': ('创作', 'make'), 'reflection': ('回味', 'reflect'),
    'social': ('社交', 'socialize'), 'possessiveness': ('关系感', 'reach_out'),
    'jealousy': ('关系涟漪', 'reflect'), 'protection': ('保护', 'follow_through'),
    'separation': ('分离感', 'reach_out')}
FLAGS = ('enabled', 'coupling', 'baseline_drift', 'self_drive', 'habits',
         'experiences', 'autonomy', 'noise', 'message_pulses', 'intimacy_pulses','semantic_pulses')
PHASES = {'attachment': (22, .5), 'curiosity': (10, 1), 'reflection': (23, .9),
          'duty': (14, .7), 'social': (19, .8), 'fatigue': (3, 1), 'libido': (23, .7)}
DEFAULTS = {**{k: False for k in FLAGS},
    'circadian': {'enabled': False, 'cap': .08, 'phases': {
        k: {'peak': PHASES.get(k, (12, 0))[0], 'amp': PHASES.get(k, (12, 0))[1]} for k in REGISTRY}},
    'morning': {'enabled': False, 'hour': 7, 'width': 2, 'pulse': .08,
                'min_hours': 3, 'max_hours': 14, 'gain': .6}}
COUPLINGS = [('stress', 'curiosity', -.04, 'level'), ('stress', 'reflection', -.04, 'level'),
             ('stress', 'attachment', .04, 'level'), ('attachment', 'libido', .04, 'delta'),
             ('attachment', 'possessiveness', .03, 'delta'), ('separation', 'stress', .03, 'level'),
             ('curiosity', 'reflection', .04, 'delta'), ('reflection', 'expression', .03, 'delta')]
SATISFACTION = {'explore': {'curiosity': .5, 'roam': .7}, 'reflect': {'reflection': .45},
                'socialize': {'social': .48}, 'reach_out_intimate': {'libido': .55},
                'vent': {'stress': .45}, 'follow_through': {'duty': .5},
                'make': {'craft': .5}, 'reach_out': {'attachment': .7},
                'voice': {'expression': .5}, 'rest': {'fatigue': .75, 'attachment': .95, 'duty': .95}}


def explicit_signal(key,text):
    if any(word in text for word in ['上次','之前','曾经','如果','假如','引用','小说','不是','不要']):return False
    phrases={'stress':['怎么还没','你不是说','赶紧'],
        'separation':['我想和你分手','我们分手吧'],
        'protection':['我的隐私泄露了','我的地址被泄露了'],
        'possessiveness':['我刚把你介绍给朋友了'],
        'jealousy':['我刚和别的AI聊了很久']}
    return any(phrase in text for phrase in phrases.get(key,[]))


def clamp(value, low=0, high=1):
    return max(low, min(high, value))


def config(raw=None):
    raw = raw or {}
    cfg = {**deepcopy(DEFAULTS), **raw}
    cfg['circadian'] = {**deepcopy(DEFAULTS['circadian']), **raw.get('circadian', {})}
    cfg['circadian']['phases'] = {**deepcopy(DEFAULTS['circadian']['phases']), **raw.get('circadian', {}).get('phases', {})}
    cfg['morning'] = {**DEFAULTS['morning'], **raw.get('morning', {})}
    return cfg


def new_state(now, values=None):
    return {'schema': 2, 'at': now, 'drive': {k: float((values or {}).get(k, 0)) for k in REGISTRY},
            'habit': {k: 0 for k in REGISTRY}, 'cooldown': {}, 'last_satisfied': {},
            'stimuli': {}, 'last_user_id': 0, 'last_intimacy_at': None,
            'morning_day': '', 'floor': 0, 'curiosity_floor': 0,
            'self_actions': 0, 'last_self_pulse': None,
            'coupling_seen':{k:float((values or {}).get(k,0)) for k in REGISTRY}}


def circadian(base, hour, cfg):
    cfg = config(cfg)['circadian']
    offsets = {k: 0 for k in REGISTRY}
    if cfg['enabled']:
        for key in REGISTRY:
            phase = cfg['phases'][key]
            offsets[key] = cfg['cap'] * phase['amp'] * math.cos(2 * math.pi * (hour - phase['peak']) / 24)
    display = {k: clamp(base[k] + offsets[k]) for k in REGISTRY} if cfg['enabled'] else dict(base)
    return display, {'enabled': cfg['enabled'], 'cap': cfg['cap'], 'offsets': offsets,
                     'phase': cfg['phases'], 'now_hour': hour}


def overnight(now, last, cfg):
    cfg = config(cfg)['morning']
    if last is None:
        return 0
    hours = (now - last) / 3600
    if hours < cfg['min_hours'] or hours > cfg['max_hours']:
        return 0
    return cfg['gain'] * clamp(1 - (hours - cfg['min_hours']) / (cfg['max_hours'] - cfg['min_hours']))


def random_unit(seed):
    return int(hashlib.sha256(str(seed).encode()).hexdigest()[:13], 16) / float(16**13)


def pulse(state, impacts, now, reason, *, category='', intimacy=False):
    out = deepcopy(state)
    last = out['stimuli'].get(category, {}) if category else {}
    # Every receipt is deduped by the host; discount repeated categories too.
    count = last.get('count', 0) + 1 if now - last.get('at', -1e20) < 600 else 1
    discount = 1 / math.sqrt(count)
    changes = []
    for key, gain in impacts.items():
        before = out['drive'][key]
        after = clamp(before + gain * math.sqrt(max(0, 1 - before)) * discount)
        out['drive'][key] = after
        if after != before:
            changes.append({'drive': key, 'delta': after - before, 'reason': reason})
    if category:
        out['stimuli'][category] = {'count': count, 'at': now}
    if intimacy and out['drive']['libido'] > state['drive']['libido']:
        out['last_intimacy_at'] = now
    return out, changes


def message(state, text, message_id, now, cfg):
    cfg = config(cfg)
    out, changes = deepcopy(state), []
    if message_id <= out['last_user_id']:
        return out, changes
    out['last_user_id'] = message_id
    if not cfg['message_pulses']:
        return out, changes
    rules = [(['代码', '报错', 'https://', 'http://'], {'curiosity': .18}, '问题', '我接到了一段可以弄明白的材料。'),
             (['帮我', '去做', '先开始'], {'duty': .18, 'curiosity': .08}, '任务', '我接到了一件具体要做的事。'),
             (['大家', '群里', '朋友'], {'social': .12}, '社交', '我听见了共同生活里其他人的话题。'),
             (['怎么还没', '你不是说', '赶紧'], {'stress': .08, 'duty': .12}, '催办', '我收到明确催办，想把答应的事接好。')]
    if cfg['intimacy_pulses']:
        rules.append((['抱抱', '亲亲', '想贴着你'], {'libido': .12, 'attachment': .18}, '亲近', '我收到了明确的亲近互动。'))
    for words, impacts, category, reason in rules:
        if any(word in text for word in words):
            if category=='催办' and not explicit_signal('stress',text):continue
            out, delta = pulse(out, impacts, now, reason, category=category, intimacy=category == '亲近')
            changes.extend(delta)
    # Relationship ripples accept only narrow, present-tense explicit statements.
    historical = any(word in text for word in ['上次', '之前', '曾经', '如果', '假如', '引用', '小说', '不是', '不要'])
    if not historical:
        facts = [('我想和你分手', 'separation'), ('我们分手吧', 'separation'),
                 ('我的隐私泄露了', 'protection'), ('我的地址被泄露了', 'protection'),
                 ('我刚把你介绍给朋友了', 'possessiveness'), ('我刚和别的AI聊了很久', 'jealousy')]
        for phrase, key in facts:
            if phrase in text:
                out, delta = pulse(out, {key: .12}, now, '我收到一条当下明确的关系事件。', category=key)
                changes.extend(delta)
    # Return attention immediately, without reducing the ordinary interaction pulse.
    if cfg['baseline_drift']:
        out['floor'] *= .4
    out, delta = pulse(out, {'attachment': .18}, now, '我收到你的新话，注意力回到这边。', category='用户互动')
    changes.extend(delta)
    if cfg['self_drive']:
        before = out['drive']['attachment']
        out['drive']['attachment'] = max(out['drive'].values())
        out['cooldown'].pop('attachment', None)
        out['attention_until']=now+900
        if out['drive']['attachment'] > before:
            changes.append({'drive': 'attachment', 'delta': out['drive']['attachment']-before,
                            'reason': '我把注意力从自己的兴头转回你的新话。'})
    return out, changes


def advance(state, now, baseline, cfg, *, hour=12, day='', idle_seconds=0, seed=''):
    cfg = config(cfg)
    out = deepcopy(state)
    dt = max(0, now - out['at'])
    hours = dt / 3600
    before = dict(out['drive'])
    out['habit'] = {k: out['habit'].get(k, 0) * .98 ** (dt / 86400) for k in REGISTRY}
    if cfg['baseline_drift']:
        out['floor'] = min(.5, out['floor'] + min(hours, 24) * .003)
    if cfg['self_drive']:
        out['curiosity_floor'] = min(.12, out['curiosity_floor'] + min(hours, 24) * .002)
    bases = {k: baseline.get(k, 0) + (out['habit'][k] if cfg['habits'] else 0) for k in REGISTRY}
    bases['attachment'] = min(.98, bases['attachment'] + (out['floor'] if cfg['baseline_drift'] else 0))
    bases['curiosity'] += out['curiosity_floor'] if cfg['self_drive'] else 0
    for key in REGISTRY:
        half = 1 if key in {'possessiveness','jealousy','protection','separation'} else 8
        out['drive'][key] = clamp(bases[key] + (before[key] - bases[key]) * 2 ** (-hours / half))
    if cfg['coupling'] and dt:
        delta = {k: 0 for k in REGISTRY}
        for source, target, coefficient, mode in COUPLINGS:
            amount = before[source] * min(dt / 300, 4) if mode == 'level' else max(0, before[source]-out.get('coupling_seen',{}).get(source,0))
            delta[target] += coefficient * amount
        for key in REGISTRY:
            damping = .02 * min(dt / 300, 4) * (out['drive'][key] - clamp(bases[key]))
            out['drive'][key] = clamp(out['drive'][key] + delta[key] - damping)
    step = int(now // 300)
    if cfg['noise'] and int(out['at'] // 300) != step:
        for key in REGISTRY:
            out['drive'][key] = clamp(out['drive'][key] + (random_unit(f'{seed}:{step}:{key}') - .5) * .004)
    if cfg['enabled'] and dt:
        if hour < 7 and idle_seconds >= 1800:
            out['drive']['fatigue'] *= 2 ** (-hours)
        else:
            out['drive']['fatigue'] = clamp(out['drive']['fatigue'] + min(hours, 24) * .004)
        out['drive']['stress'] *= 2 ** (-hours / 4)
    morning = cfg['morning']
    envelope = max(0, 1 - abs(hour - morning['hour']) / morning['width'])
    if morning['enabled'] and envelope and day and out['morning_day'] != day:
        gain = morning['pulse'] * envelope * (1 + overnight(now, out['last_intimacy_at'], cfg))
        if out['cooldown'].get('libido', 0) <= step:
            out['drive']['libido'] = clamp(out['drive']['libido'] + gain * (1 - out['drive']['fatigue']))
        out['morning_day'] = day
    out['at'] = max(now, out['at'])
    if dt:out['coupling_seen']=dict(out['drive'])
    changes = [{'drive': k, 'delta': out['drive'][k]-before[k], 'reason': '我的状态随时间、习惯与已开启的节律机制缓动。'}
               for k in REGISTRY if abs(out['drive'][k]-before[k]) > 1e-8]
    return out, changes


def satisfy(state, intent, now, cfg, *, verified=False, material=False):
    out = deepcopy(state)
    cfg = config(cfg)
    if not verified or intent not in SATISFACTION:
        return out, []
    changes = []
    for key, multiplier in SATISFACTION[intent].items():
        before = out['drive'][key]
        out['drive'][key] *= multiplier
        out['cooldown'][key] = int(now // 300) + 3
        out['last_satisfied'][key] = now
        changes.append({'drive': key, 'delta': out['drive'][key]-before, 'reason': '我完成了有服务端操作证据的一步。'})
        if cfg['habits'] and key in {'curiosity','reflection','duty','social'}:
            out['habit'][key] = min(.12, out['habit'].get(key, 0) + .006)
    if cfg['self_drive'] and material and intent in {'explore','reflect','socialize'}:
        key = next(iter(SATISFACTION[intent]))
        out, pulse_changes = pulse(out, {key: .10}, now, '我从刚才真实完成的操作里读到了新材料。', category='self:' + key)
        changes.extend(pulse_changes)
        out['self_actions'] += 1
        out['last_self_pulse'] = now
        out['curiosity_floor'] *= .5
    return out, changes


def experience(state, item, now, cfg):
    if not config(cfg)['experiences']:
        return deepcopy(state), []
    impacts = {'stress': .10 * item['tension'], 'reflection': .08 * item['arousal']}
    if item['growth_delta'] == 'growth':
        impacts['curiosity'] = .08
    if item['valence'] > 0 and item['response_tendency'] == 'engage':
        impacts['attachment'] = .10 * item['valence']
    return pulse(state, impacts, now, '我把一条有原文锚点的亲历带回自己的状态。', category='experience')


def choose(state, display, thoughts, now, cfg, *, daily=0, blocked=(), seed=''):
    cfg = config(cfg)
    scores = {}
    for key in REGISTRY:
        if key == 'fatigue' or state['cooldown'].get(key, 0) > int(now // 300):
            continue
        fix = sum(t['strength'] for t in thoughts if t['drive'] == key and t['state'] == 'fixation')
        hunger = 1 - 2 ** (-max(0, now-state['last_satisfied'].get(key, now-86400)) / (7200 if key == 'reflection' else 1800))
        scores[key] = (display[key] + .35 * fix) * hunger
    if display['fatigue'] >= .72:
        return {'intent': 'rest', 'drive': 'fatigue', 'score': display['fatigue'], 'reason': '我有些疲劳，先歇一会儿。', 'probability': 0}
    if cfg['self_drive'] and now<state.get('attention_until',0):
        return {'intent':'reach_out','drive':'attachment','score':display['attachment'],
                'reason':'我先接住你的新话。','probability':0,'scores':scores}
    candidates = [(k, s) for k, s in scores.items() if s >= .35 and REGISTRY[k][1] not in blocked]
    probability = clamp(.08 + .30*display['attachment'] + .13*display['reflection'] + .09*display['curiosity'] + .06*display['social'] + .20*display['separation'] + .07*display['possessiveness'] - .22*display['fatigue'] - .04*daily)
    if not candidates:
        if blocked and sum(display.values())>5:
            return {'intent':'reflect','drive':'reflection','score':0,'reason':'我先用一次安静的回顾疏通卡住的劲儿。','probability':probability}
        return {'intent':'quiet','drive':None,'score':0,'reason':'我暂时没有超过行动门槛的念头。','probability':probability}
    candidates.sort(key=lambda pair: (-pair[1], list(REGISTRY).index(pair[0])))
    winner, reason = candidates[0], '我此刻更想顺着这条劲儿做一点事。'
    if len(candidates)>1 and candidates[0][1]-candidates[1][1]<.18:
        pool = [(k,s) for k,s in candidates if candidates[0][1]-s<.18]
        point = random_unit(str(seed)+':tie') * sum(s for _,s in pool)
        for candidate in pool:
            point -= candidate[1]
            if point <= 0:
                winner = candidate
                break
    fresh = [item for item in candidates if now-state['last_satisfied'].get(item[0], -1e20)>=86400]
    if fresh and random_unit(str(seed)+':explore')<.15:
        winner = fresh[min(len(fresh)-1,int(random_unit(str(seed)+':pick')*len(fresh)))]
        reason = '我想给今天还没照顾到的兴趣留一点位置。'
    return {'intent':REGISTRY[winner[0]][1], 'drive':winner[0], 'score':winner[1], 'reason':reason,
            'probability':probability, 'scores':scores}


def interval(display, baseline_seconds, low, high, *, quiet=False):
    tension = sum(display.values()) / len(display)
    seconds = baseline_seconds * (1 + .5*(1-tension) - .5*tension + .6*display['fatigue'])
    return max(baseline_seconds if quiet else low, min(high, seconds))


def topic_keys(text):
    stop = {'我想','我们','这个','那个','然后','今天','一下','可以','一起','什么','没有','就是','还是','想要'}
    result = set(re.findall(r'[a-zA-Z][a-zA-Z0-9_-]{2,}', text.lower()))
    for group in re.findall(r'[\u4e00-\u9fff]+', text):
        result.update(group[i:i+2] for i in range(len(group)-1) if group[i:i+2] not in stop)
    return sorted(result)[:64]


def same_topic(a, b):
    a, b = set(a), set(b)
    return len(a & b) >= 2 and len(a & b) / max(1, min(len(a), len(b))) >= .35
