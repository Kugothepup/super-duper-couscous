(function(){
const D = JSON.parse(document.getElementById('data').textContent);
const M = D.meta, L = D.lens, S = D.study || {}, main = document.getElementById('main');
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pct = v => (v == null ? '—' : (Math.round(v*10)/10) + '%');
const people = n => n + ' ' + (n === 1 ? (M.mode === 'reddit' ? 'person' : 'participant') : M.unit);
const asp = a => a ? `<button type="button" class="asp" data-focus="${esc(a)}">${esc(a)}</button>` : '';
const DEFAULT_NAMES = {verdict:'Summary', stance:'Where people stand', drivers:'What drives sentiment', associations:'Brand associations',
  direction:'Direction of travel', themes:'Themes', pains:'Pain points', successes:'Success moments', jobs:'Jobs to be done',
  opportunities:'Opportunities', entities:L.entity_title || 'Entities', framing:'How the story is framed', questions:'Questions people ask',
  outlook:'Outlook', language:'Language used', trust:'How much to trust this', hypotheses:'Hypotheses for discovery'};
const NAME = id => (L.names && L.names[id]) || DEFAULT_NAMES[id];
const sections = [];
function section(id, lede, html){
  const s = document.createElement('section'); s.id = id;
  s.innerHTML = `<h2>${esc(NAME(id))}</h2>${lede ? `<p class="lede">${lede}</p>` : ''}${html}`;
  main.appendChild(s); sections.push([id, NAME(id)]);
  return s;
}
const empty = msg => `<div class="empty">${msg}</div>`;
// Outside the product lens, sections with no data are left out rather than shown empty.
function none(id, msg){ if (L.type === 'product') section(id, '', empty(msg)); }
function evList(items, label){
  if (!items || !items.length) return '';
  return `<details><summary>${esc(label || ('Evidence: ' + items.length + ' coded ' + (items.length === 1 ? 'comment' : 'comments')))}</summary><ul class="ev">` +
    items.map(e => `<li>${esc(e.obs)} <span class="tag">${esc(e.id)}${e.aspect ? ', ' + esc(e.aspect) : ''}, ${esc((e.ev||'').replace('_',' '))}${e.score != null ? ', ^' + e.score : ''}</span>${e.quote ? `<q>${esc(e.quote)}</q>` : ''}</li>`).join('') +
    `</ul></details>`;
}
function withAspects(el, list){ el.dataset.aspects = (list || []).join('|'); return el; }
const dv = D.drivers, ov = dv && dv.overall, st = dv && dv.stance, evt = dv && dv.event;
const R = {};

/* ---------- verdict ---------- */
R.verdict = () => {
  let verdict = 'Findings: ' + M.title;
  if (L.stance && st){
    const g = st.for_pct - st.against_pct;
    verdict = (g > 15 ? 'Mostly for' : g < -15 ? 'Mostly against' : 'Divided') + ': ' + pct(st.for_pct) + ' for, ' + pct(st.against_pct) + ' against';
  } else if (ov){
    const gap = ov.negative_pct - ov.positive_pct;
    const mood = ov.small_sample ? (gap > 15 ? 'Leaning negative' : gap < -15 ? 'Leaning positive' : 'Mixed')
                                 : (gap > 15 ? 'Mostly negative' : gap < -15 ? 'Mostly positive' : 'Mixed');
    const tops = (dv.drivers || []).slice(0, ov.small_sample ? 2 : 3).map(a => a.aspect);
    verdict = mood + (tops.length ? (ov.small_sample ? ', mostly about ' : ', driven by ') + (tops.length > 1 ? tops.slice(0, -1).join(', ') + ' and ' + tops[tops.length-1] : tops[0]) : '') + (ov.small_sample ? ', in a small sample' : '');
  }
  let strip = '';
  if (ov){
    const n = ov.negative_pct, p = ov.positive_pct, u = Math.max(0, 100 - n - p);
    strip = `${L.stance ? '<h3 style="margin:0 0 6px">Tone of discussion</h3>' : ''}<div class="strip" role="img" aria-label="${pct(n)} negative, range ${ov.negative_ci[0]} to ${ov.negative_ci[1]} percent; ${pct(u)} neutral; ${pct(p)} positive">
      <div class="bar"><span class="n" style="flex-basis:${n}%"></span><span class="u" style="flex-basis:${u}%"></span><span class="p" style="flex-basis:${p}%"></span></div>
      <div class="ci" style="left:${ov.negative_ci[0]}%;width:${Math.max(0.5, ov.negative_ci[1]-ov.negative_ci[0])}%"></div>
      <div class="ci" style="left:${100-ov.positive_ci[1]}%;width:${Math.max(0.5, ov.positive_ci[1]-ov.positive_ci[0])}%"></div>
      <div class="legend"><span><i style="background:var(--neg)"></i>Negative ${pct(n)} (likely ${ov.negative_ci[0]}–${ov.negative_ci[1]}%)</span><span><i style="background:var(--neu)"></i>Neutral ${pct(u)}</span><span><i style="background:var(--pos)"></i>Positive ${pct(p)} (likely ${ov.positive_ci[0]}–${ov.positive_ci[1]}%)</span></div>
    </div>`;
  }
  const dir = dv && dv.direction;
  const dirText = !dir ? 'Not measured' : dir.status === 'ok' ? (dir.negative_trend.charAt(0).toUpperCase() + dir.negative_trend.slice(1)) : 'Snapshot only';
  const hv = document.createElement('header'); hv.className = 'verdict'; hv.id = 'verdict';
  hv.innerHTML = `<div class="topline"><p class="subject">${esc(L.label)}: ${esc(M.title)}. ${esc(M.sources.join(', '))}${M.window ? ', ' + esc(M.window[0]) + ' to ' + esc(M.window[1]) : ''}</p><button class="theme-t" id="themeT" type="button">Light or dark</button></div>
    <h1>${esc(verdict)}</h1>${S.stance_target ? `<p class="proposition">On the proposition: ${esc(S.stance_target)}</p>` : ''}${strip}
    <ul class="facts">
      <li><b>${M.n_people}</b>${esc(M.unit)}</li>
      <li><b>${M.n_items}</b>${M.mode === 'reddit' ? 'posts and comments' : 'turns'}</li>
      ${ov ? `<li><b>${ov.n_comments}</b>sampled for sentiment</li>` : ''}
      ${M.n_read ? `<li><b>${M.n_read}</b>read in detail</li>` : ''}
      <li><b>${esc(dirText)}</b>direction</li>
      ${S.event_date ? `<li><b>${esc(S.event_date)}</b>event date</li>` : ''}
    </ul>`;
  const notes = [];
  if (ov && ov.small_sample) notes.push(`Small sample (${ov.n_comments} comments): percentages are rough, so lean on the ranges.`);
  if (ov && ov.dominant_source) notes.push(`Most of the sample comes from ${esc(ov.dominant_source)}, so overall figures mostly reflect it. See the split by source.`);
  if (notes.length) hv.insertAdjacentHTML('beforeend', `<p class="caution">${notes.join(' ')}</p>`);
  // wording that stays within what the data supports
  if (ov){
    const who = `Among ${M.n_people} ${M.unit} posting in ${M.sources.join(', ')}${M.window ? ' between ' + M.window[0] + ' and ' + M.window[1] : ''}`;
    let claim;
    if (L.stance && st) claim = `${who}, ${pct(st.for_pct)} of those taking a position supported "${S.stance_target}" and ${pct(st.against_pct)} opposed it (likely ranges ${st.for_ci[0]}–${st.for_ci[1]}% and ${st.against_ci[0]}–${st.against_ci[1]}%).`;
    else {
      const top = (dv.drivers || [])[0];
      const k = Math.round(ov.negative_pct * ov.n_comments / 100);
      claim = ov.small_sample
        ? `${who}, ${k} of ${ov.n_comments} sampled comments were negative` + (top ? `, most often about ${top.aspect}.` : '.') + ' This is an early signal from a small sample, not a measured share.'
        : `${who}, ${pct(ov.negative_pct)} of a random sample of comments were negative (likely ${ov.negative_ci[0]}–${ov.negative_ci[1]}%)` +
          (top ? `, with ${top.aspect} the largest source of negativity (${pct(top.share_of_negative_pct)} of negative mentions).` : '.');
    }
    hv.insertAdjacentHTML('beforeend', `<div class="safe"><p class="safe-h">Safe wording for a deck</p><p class="safe-t" id="safeT">${esc(claim)}</p>
      <p class="safe-n">Describes people who chose to post, not all ${L.type === 'news' || L.type === 'topic' ? 'the public' : 'customers'}. Avoid "users think" or "most people".</p>
      <button type="button" class="chip" id="copySafe">Copy wording</button></div>`);
  }
  main.appendChild(hv); sections.push(['verdict', 'Summary']);
};

/* ---------- hypotheses (the handover to discovery) ---------- */
R.hypotheses = () => {
  const HY = D.hypotheses;
  if (!HY || !HY.hypotheses.length) return;
  const origin = {stated:'Your belief, written down before reading', formed:'Suggested by this data'};
  const H = HY.hypotheses;
  // assumption map: importance (up) against evidence (right)
  const W = 560, Ht = 260, pl = 30, pb = 30, pr = 10, pt = 10;
  // x = tested evidence. Hypotheses suggested by this data have none yet, so they stay left of the line.
  const ev = h => { const v = ({weak:0, moderate:1, strong:2}[h.strength]) + (h.lean === 'leans for' || h.lean === 'leans against' ? 0.5 : 0); return h.origin === 'formed' ? Math.min(v, 0.85) : v; };
  const im = h => ({low:0, medium:1, high:2}[h.importance]);
  const px = v => pl + (v + 0.25) / 2.75 * (W - pl - pr), py = v => pt + (2.5 - v) / 2.75 * (Ht - pt - pb);
  const seen = {};
  const dots = H.map(h => {
    const k = ev(h) + ':' + im(h); seen[k] = (seen[k] || 0) + 1; const off = (seen[k] - 1) * 18;
    return `<g><circle cx="${px(ev(h)) + off}" cy="${py(im(h))}" r="13" fill="${h.origin === 'stated' ? 'var(--prob)' : 'var(--ink)'}"/><text x="${px(ev(h)) + off}" y="${py(im(h)) + 4}" font-size="11" text-anchor="middle" fill="var(--bg)" font-weight="600">${esc(h.id)}</text></g>`;
  }).join('');
  const map = `<svg class="amap" viewBox="0 0 ${W} ${Ht}" role="img" aria-label="Assumption map: ${H.map(h => h.id + ' ' + h.importance + ' importance, ' + h.strength + ' evidence').join('; ')}">
    <rect x="${pl}" y="${pt}" width="${(W-pl-pr)/2}" height="${(Ht-pt-pb)/2}" fill="var(--neg-soft)"/>
    <line x1="${pl}" x2="${W-pr}" y1="${pt+(Ht-pt-pb)/2}" y2="${pt+(Ht-pt-pb)/2}" stroke="var(--rule)"/><line x1="${pl+(W-pl-pr)/2}" x2="${pl+(W-pl-pr)/2}" y1="${pt}" y2="${Ht-pb}" stroke="var(--rule)"/>
    <text x="${pl+8}" y="${pt+16}" font-size="12" fill="var(--neg)" font-weight="600">Test first</text>
    <text x="${W-pr-8}" y="${pt+16}" font-size="12" fill="var(--muted)" text-anchor="end">Build on it, keep checking</text>
    <text x="${pl+8}" y="${Ht-pb-8}" font-size="12" fill="var(--muted)">Park for now</text>
    <text x="${pl}" y="${Ht-8}" font-size="11" fill="var(--muted)">Little tested evidence</text><text x="${W-pr}" y="${Ht-8}" font-size="11" fill="var(--muted)" text-anchor="end">More tested evidence</text>
    <text x="12" y="${pt+(Ht-pt-pb)/2}" font-size="11" fill="var(--muted)" transform="rotate(-90 12 ${pt+(Ht-pt-pb)/2})" text-anchor="middle">Importance</text>${dots}</svg>
    <div class="keyline"><span><span class="sw" style="background:var(--prob);border-radius:50%;width:10px"></span>your belief</span><span><span class="sw" style="background:var(--ink);border-radius:50%;width:10px"></span>suggested by the data (stays left: this data can't also be its test)</span></div>
    <div class="keyline"><span><span class="sw" style="background:var(--neg);opacity:.35"></span>below 20% of re-draws: leans against</span><span><span class="sw" style="background:var(--pos);opacity:.35"></span>above 80%: leans for</span><span><span class="sw" style="background:var(--prob)"></span>likely range of a count</span></div>`;
  const s = section('hypotheses', 'Where to take discovery next. These findings can suggest and prioritise hypotheses; they can\'t prove them. Each one shows how strongly the signals lean, and how to test it properly. Ones suggested by this data are never tested by it.' +
    (HY.warnings && HY.warnings.length ? ' <span class="warnline">' + HY.warnings.map(esc).join(' ') + '</span>' : ''), `<div class="scroll">${map}</div><div></div>`);
  const box = s.lastElementChild;
  const leanClass = l => l === 'leans for' ? 'v-supported' : l === 'leans against' ? 'v-contradicted' : l === 'mixed' ? 'v-mixed' : 'v-not-testable';
  H.forEach(h => {
    const sig = h.signals.map(g => {
      let viz = '', val = '';
      if (g.prob !== undefined){
        if (g.prob == null){ val = esc(g.note || 'not computable'); }
        else {
          val = `${g.prob}% of re-draws`;
          viz = `<div class="pbar" role="img" aria-label="${g.prob} percent"><span class="zone lo"></span><span class="zone hi"></span><span class="mark" style="left:${g.prob}%"></span></div>`;
        }
      } else if (g.k !== undefined){
        val = `${g.k} of ${g.n} (likely ${g.ci[0]}–${g.ci[1]}%)`;
        viz = `<div class="pbar" role="img" aria-label="likely ${g.ci[0]} to ${g.ci[1]} percent"><span class="range" style="left:${g.ci[0]}%;width:${Math.max(1, g.ci[1]-g.ci[0])}%"></span><span class="mid"></span></div>`;
      } else {
        const t = Math.max(1, g.voices_for + g.voices_against);
        val = `${people(g.voices_for)} for, ${g.voices_against} against`;
        viz = `<div class="pred-bar"><span style="width:${100*g.voices_for/t}%;background:var(--pos)"></span><span style="width:${100*g.voices_against/t}%;background:var(--neg)"></span></div>`;
      }
      const lean = g.lean === 'for' ? 'leans for' : g.lean === 'against' ? 'leans against' : 'unclear';
      return `<li class="pred"><div class="pred-h"><span class="vchip ${leanClass(lean)}">${lean}</span> ${esc(g.text)}</div>${viz}<div class="num" style="white-space:normal">${val}</div></li>`;
    }).join('');
    const ns = h.next_step || {};
    const d = document.createElement('div'); d.className = 'item hyp';
    d.innerHTML = `<p class="owner">${esc(h.id)}: ${esc(origin[h.origin] || h.origin)}, ${esc(h.importance)} importance</p>
      <p class="stmt">${esc(h.statement)}</p>
      <p class="hverdict ${leanClass(h.lean)}">${esc(h.lean.charAt(0).toUpperCase() + h.lean.slice(1))}${h.lean !== "can't tell from this data" ? ', <span class="strength s-' + esc(h.strength) + '">' + esc(h.strength) + ' evidence</span>' : ''} <span class="prio p-${esc(h.priority.split(',')[0].replace(/ /g, '-'))}">${esc(h.priority)}</span></p>
      <p class="num" style="white-space:normal;margin:-4px 0 6px">${people(h.voices)} behind the signals${h.small_sample ? ', small sample' : ''}.</p>
      <ul class="preds">${sig}</ul>
      ${h.not_distinguishing.length ? `<p class="num" style="white-space:normal">Fits other explanations too, so it doesn't help decide: ${h.not_distinguishing.map(esc).join(', ')}</p>` : ''}
      <div class="next"><p class="safe-h">How to test it</p>
        <p><b>Method:</b> ${esc(ns.method)}</p>${ns.recruit ? `<p><b>Who:</b> ${esc(ns.recruit)}</p>` : ''}
        <p><b>Would support it:</b> ${esc(ns.confirm)}</p><p><b>Would count against it:</b> ${esc(ns.disconfirm)}</p>
        ${ns.questions && ns.questions.length ? `<p><b>Starting questions:</b></p><ul>${ns.questions.map(q => `<li>${esc(q)}</li>`).join('')}</ul>` : ''}</div>`;
    box.appendChild(d);
  });
};

/* ---------- stance ---------- */
R.stance = () => {
  if (!st){
    section('stance', '', empty(S.stance_target ? 'Add "stance" to sentiment records (−2 against to +2 for, null when no position is taken), then run drivers.py.' : 'Set a proposition with init_study.py --stance-target to measure where people stand.'));
    return;
  }
  const f = st.for_pct, a = st.against_pct, u = Math.max(0, 100 - f - a);
  const talk = (obj, cls) => Object.keys(obj || {}).length ? `<div class="rows">${Object.entries(obj).map(([k, v]) => `<div class="drow stack" data-aspects="${esc(k)}">${asp(k)}<div class="track"><div class="fill ${cls}" style="width:${v}%"></div></div><span class="num">raised in ${pct(v)} of their comments</span></div>`).join('')}</div>` : empty('Too few comments on this side.');
  section('stance', `Of ${st.n_sample} sampled comments, ${pct(st.expressing_pct)} take a position on the proposition. Stance is separate from tone: someone can be angry and in favour.`,
    `<div class="strip" role="img" aria-label="${pct(f)} for, ${pct(u)} neutral or unclear, ${pct(a)} against">
       <div class="bar"><span style="flex-basis:${f}%;background:var(--for)"></span><span class="u" style="flex-basis:${u}%"></span><span style="flex-basis:${a}%;background:var(--against)"></span></div>
       <div class="ci" style="left:${st.for_ci[0]}%;width:${Math.max(0.5, st.for_ci[1]-st.for_ci[0])}%"></div>
       <div class="ci" style="left:${100-st.against_ci[1]}%;width:${Math.max(0.5, st.against_ci[1]-st.against_ci[0])}%"></div>
       <div class="legend"><span><i style="background:var(--for)"></i>For ${pct(f)} (likely ${st.for_ci[0]}–${st.for_ci[1]}%)</span><span><i style="background:var(--neu)"></i>Neutral or unclear ${pct(u)}</span><span><i style="background:var(--against)"></i>Against ${pct(a)} (likely ${st.against_ci[0]}–${st.against_ci[1]}%)</span></div>
     </div>
     <div class="two" style="margin-top:28px"><div><h3 style="margin-bottom:12px">What the for side talks about</h3>${talk(st.for_talks_about, 'for')}</div>
     <div><h3 style="margin-bottom:12px">What the against side talks about</h3>${talk(st.against_talks_about, 'against')}</div></div>`);
};

/* ---------- drivers ---------- */
R.drivers = () => {
  if (!dv){ none('drivers', 'Code the random sentiment sample, then run drivers.py to fill this.'); return; }
  const maxN = Math.max(1, ...(dv.drivers||[]).map(a => a.share_of_negative_pct));
  const maxP = Math.max(1, ...(dv.strengths||[]).map(a => a.share_of_positive_pct));
  const row = (a, share, max, cls, extra, ci) => `<div class="drow stack" data-aspects="${esc(a.aspect)}">${asp(a.aspect)}
      <div class="track rel" aria-hidden="true"><div class="fill ${cls}${a.authors < 3 ? ' thin' : ''}" style="width:${100*share/max}%"></div>${ci ? `<span class="whisk" style="left:${Math.min(100, 100*ci[0]/max)}%;width:${Math.max(0.5, Math.min(100, 100*ci[1]/max) - 100*ci[0]/max)}%"></span>` : ''}</div>
      <span class="num">${pct(share)}${ci ? ` (likely ${ci[0]}–${ci[1]}%)` : ''}, ${extra}${a.top_driver_prob ? `, top driver in ${a.top_driver_prob}% of re-draws` : ''}</span></div>`;
  const maxN2 = Math.max(maxN, ...(dv.drivers||[]).slice(0, 8).map(a => (a.share_of_negative_ci || [0,0])[1]));
  const dHtml = (dv.drivers||[]).slice(0, 8).map(a => row(a, a.share_of_negative_pct, maxN2, 'neg', `${people(a.authors)}, ${a.negative_rate_pct >= 100 ? 'always negative' : 'negative ' + pct(a.negative_rate_pct) + ' of the time'}`, a.share_of_negative_ci)).join('');
  const sHtml = (dv.strengths||[]).slice(0, 6).map(a => row(a, a.share_of_positive_pct, maxP, 'pos', people(a.authors))).join('');
  section('drivers', 'Each bar is that ' + esc(L.aspect_word || 'aspect') + '\'s share of all negative (or positive) mentions in the random sample; the bracket is its likely range. "Top driver in X% of re-draws" comes from resampling people, so overlapping ranges mean the order isn\'t settled. Tap one to focus the whole page on it.',
    `<div class="two"><div><h3 style="margin-bottom:12px">Drivers of negativity</h3><div class="rows">${dHtml || empty('Nothing with enough mentions.')}</div></div>
     <div><h3 style="margin-bottom:12px">${L.type === 'brand' ? 'What the brand is valued for' : 'What people value'}</h3><div class="rows">${sHtml || empty('Nothing with enough mentions.')}</div></div></div>
     ${(dv.by_source || []).length > 1 ? `<h3 style="margin:28px 0 10px">By source</h3><div class="scroll"><table class="tbl"><thead><tr><th>Source</th><th>Share of sample</th><th>Negative</th></tr></thead><tbody>${dv.by_source.map(b => `<tr><td>${esc(b.source)}</td><td>${pct(b.share_pct)} <span class="num">(${b.n})</span></td><td>${pct(b.negative_pct)} <span class="num">(likely ${b.negative_ci[0]}–${b.negative_ci[1]}%)</span></td></tr>`).join('')}</tbody></table></div>` : ''}`);
};

/* ---------- brand associations ---------- */
R.associations = () => {
  const A = ((dv && dv.all_aspects) || []).filter(a => a.mentions >= 3);
  if (A.length < 3){ none('associations', 'Needs the sentiment sample with at least three associations.'); return; }
  const W = 640, H = 320, pl = 40, pr = 16, pt = 16, pb = 40;
  const maxX = Math.max(...A.map(a => a.mention_rate_pct)) * 1.1;
  const x = v => pl + v / maxX * (W - pl - pr), y = v => pt + (2 - v) / 4 * (H - pt - pb);
  const sorted = A.map(a => a.mention_rate_pct).sort((p, q) => p - q), med = sorted[Math.floor(sorted.length / 2)];
  const pts = A.map(a => `<g class="pt" data-focus="${esc(a.aspect)}" role="button" tabindex="0" aria-label="${esc(a.aspect)}: mentioned in ${a.mention_rate_pct}% of comments, favourability ${a.mean}">
      <circle cx="${x(a.mention_rate_pct)}" cy="${y(a.mean)}" r="${4 + Math.sqrt(a.authors)}" fill="${a.mean < 0 ? 'var(--neg)' : 'var(--pos)'}" fill-opacity=".85"/>
      <text x="${x(a.mention_rate_pct) + 8 + Math.sqrt(a.authors)}" y="${y(a.mean) + 4}" font-size="12" fill="var(--ink)">${esc(a.aspect)}</text></g>`).join('');
  const q = (tx, ty, t, anchor) => `<text x="${tx}" y="${ty}" font-size="11" fill="var(--muted)" text-anchor="${anchor}">${t}</text>`;
  const svg = `<svg class="scatter" viewBox="0 0 ${W} ${H}" role="group" aria-label="Associations by strength and favourability">
    <line x1="${pl}" x2="${W-pr}" y1="${y(0)}" y2="${y(0)}" stroke="var(--rule)" stroke-width="1.5"/>
    <line x1="${x(med)}" x2="${x(med)}" y1="${pt}" y2="${H-pb}" stroke="var(--rule)" stroke-width="1.5" stroke-dasharray="4 4"/>
    ${q(W-pr, pt+10, 'Strong and favourable', 'end')}${q(W-pr, H-pb-6, 'Strong but unfavourable', 'end')}${q(pl+4, pt+10, 'Weak but favourable', 'start')}${q(pl+4, H-pb-6, 'Weak and unfavourable', 'start')}
    ${q(pl, H-12, 'Rarely mentioned', 'start')}${q(W-pr, H-12, 'Often mentioned (strength)', 'end')}
    ${q(pl-6, y(2)+4, '+2', 'end')}${q(pl-6, y(0)+4, '0', 'end')}${q(pl-6, y(-2)+4, '−2', 'end')}
    ${pts}</svg>`;
  section('associations', 'What people connect with the brand, placed by how often it comes up (strength) and how positively (favourability), after Keller\'s brand-equity model. Uniqueness needs comparable data on competitors; Language shows what is distinctive within this data. Dot size reflects how many people raised it.',
    `<div class="scroll">${svg}</div>`);
};

/* ---------- direction ---------- */
R.direction = () => {
  const dir = dv && dv.direction;
  let html = '', lede = '';
  if (dir && dir.status === 'ok'){
    const P = dir.periods, W = 640, H = 130, pad = 28;
    const x = i => pad + (P.length === 1 ? 0 : i * (W - 2*pad) / (P.length - 1));
    const y = v => H - 18 - v * (H - 34) / 100;
    const band = P.map((p,i) => `${x(i)},${y(p.negative_ci[1])}`).join(' ') + ' ' + P.slice().reverse().map((p,j) => `${x(P.length-1-j)},${y(p.negative_ci[0])}`).join(' ');
    const line = P.map((p,i) => `${x(i)},${y(p.negative_pct)}`).join(' ');
    const sw = dir.switching_rate_per_100 || {};
    const sline = P.map((p,i) => sw[p.period] != null ? `${x(i)},${y(sw[p.period])}` : null).filter(Boolean).join(' ');
    const labels = P.map((p,i) => `<text x="${x(i)}" y="${H-2}" font-size="11" text-anchor="middle" fill="var(--muted)">${esc(p.period)}</text>`).join('');
    const ei = evt && evt.period ? P.findIndex(p => p.period >= evt.period) : -1;
    const mark = ei >= 0 ? `<line x1="${x(ei)}" x2="${x(ei)}" y1="6" y2="${H-16}" stroke="var(--ink)" stroke-dasharray="3 3"/><text x="${x(ei)+5}" y="14" font-size="11" fill="var(--ink)">event</text>` : '';
    html += `<div class="keyline"><span><span class="sw" style="background:var(--neg)"></span>% negative comments</span>${L.jtbd ? '<span><span class="sw" style="background:var(--prob);height:3px"></span>switching talk per 100 comments</span>' : ''}</div>
      <svg class="spark" viewBox="0 0 ${W} ${H}" role="img" aria-label="Share of negative comments per ${esc(dir.unit)}: ${P.map(p => p.period + ' ' + p.negative_pct + '%').join(', ')}">
      <polygon points="${band}" fill="var(--neg-soft)"/><polyline points="${line}" fill="none" stroke="var(--neg)" stroke-width="2.5"/>
      ${sline && L.jtbd ? `<polyline points="${sline}" fill="none" stroke="var(--prob)" stroke-width="2" stroke-dasharray="5 4"/>` : ''}
      ${P.map((p,i) => `<circle cx="${x(i)}" cy="${y(p.negative_pct)}" r="3.5" fill="var(--neg)"/>`).join('')}${labels}${mark}</svg>`;
    lede = `Negativity per ${esc(dir.unit)} is <b>${esc(dir.negative_trend)}</b>. The shaded band is the likely range; only periods with enough comments count towards the verdict.`;
  } else {
    html += empty(esc(dir && dir.note ? dir.note : 'No timestamps, so direction can\'t be shown. Collect material spread over several months.'));
  }
  if (evt){
    const label = {negative:'Negative comments', 'for':'Comments for the proposition'};
    const rows = evt.measures.map(m => `<tr><td>${esc(label[m.measure] || m.measure)}</td><td>${pct(m.before_pct)} <span class="num">(${m.n_before})</span></td><td>${pct(m.after_pct)} <span class="num">(${m.n_after})</span></td><td>${m.diff_pts > 0 ? '+' : ''}${m.diff_pts} pts${m.diff_ci ? ` <span class="num">(${m.diff_ci[0]} to ${m.diff_ci[1]})</span>` : ''}</td><td><b>${esc(m.verdict)}</b></td></tr>`).join('');
    const shifts = (evt.aspect_shifts || []).map(c => `<li>${asp(c.measure)} ${c.verdict === 'rose' ? 'rose' : 'fell'} from ${pct(c.before_pct)} to ${pct(c.after_pct)} of comments</li>`).join('');
    html += `<h3 style="margin:28px 0 10px">Before and after ${esc(evt.date)}</h3>
      <div class="scroll"><table class="tbl"><thead><tr><th>Measure</th><th>Before</th><th>After</th><th>Change (95% range)</th><th>Verdict</th></tr></thead><tbody>${rows}</tbody></table></div>
      ${shifts ? `<p style="margin:14px 0 6px;font-size:14px"><b>Topics that shifted</b></p><ul class="shifts">${shifts}</ul>` : ''}
      <p class="num" style="white-space:normal;margin-top:10px">${esc(evt.note)}</p>`;
  }
  section('direction', lede, html);
};

/* ---------- themes ---------- */
R.themes = () => {
  const I = D.insights;
  if (!I.length){ section('themes', '', empty('Write insights.json during synthesis to fill this.')); return; }
  const maxV = Math.max(...I.map(i => i.voices), 1);
  const s = section('themes', 'The main patterns, strongest first. Bars show how many different people support each; hatched means one voice or low confidence.', '<div></div>');
  const box = s.lastElementChild;
  const order = {high:0, medium:1, low:2};
  I.slice().sort((a,b) => (order[a.confidence]-order[b.confidence]) || (b.voices-a.voices)).forEach(i => {
    const d = document.createElement('div'); d.className = 'item';
    const thin = i.voices <= 1 || i.confidence === 'low';
    d.innerHTML = `<p class="stmt">${esc(i.statement)}</p>
      <div class="metaline"><span class="conf-${esc(i.confidence)}">${esc(i.confidence)} confidence</span>
      <span class="cov"><span class="track"><span class="fill ink${thin ? ' thin' : ''}" style="display:block;width:${100*i.voices/maxV}%"></span></span>${people(i.voices)}</span>
      <span>${i.strong} of ${i.n} from specific incidents</span>
      ${i.aspects.length ? '<span>' + i.aspects.map(asp).join(', ') + '</span>' : ''}</div>
      ${i.recs.length ? `<ul class="recs">${i.recs.map(r => `<li>${esc(r)}</li>`).join('')}</ul>` : ''}
      ${evList(i.evidence)}${i.counter.length ? evList(i.counter, 'Counter-evidence: ' + i.counter.length) : ''}`;
    box.appendChild(withAspects(d, i.aspects));
  });
};

/* ---------- pains & successes ---------- */
function moments(id, lede, groups, cls, withSev, emptyMsg){
  if (!groups.length){ none(id, emptyMsg); return; }
  const maxV = Math.max(...groups.map(g => g.voices), 1);
  const s = section(id, lede, '<div></div><details class="more hide"><summary></summary><div></div></details>');
  const top = s.children[s.children.length - 2], more = s.lastElementChild, moreBox = more.lastElementChild;
  const cap = 8;
  if (groups.length > cap){ more.classList.remove('hide'); more.querySelector('summary').textContent = 'Show ' + (groups.length - cap) + ' more, mostly single voices'; }
  groups.forEach((g, gi) => {
    const box = gi < cap ? top : moreBox;
    const d = document.createElement('div'); d.className = 'item';
    const pips = withSev ? `<span class="pips" aria-label="worst severity ${g.max_sev} of 3">${[1,2,3].map(k => `<span class="${k <= g.max_sev ? 'on' : ''}"></span>`).join('')}</span>` : '';
    d.innerHTML = `<div class="drow">${asp(g.aspect)}
        <div class="track"><div class="fill ${cls}${g.voices <= 1 ? ' thin' : ''}" style="width:${100*g.voices/maxV}%"></div></div>
        <span class="num">${people(g.voices)} ${pips}</span></div>
      ${evList(g.evidence, g.evidence.map(e => e.obs).slice(0,1).join('') + (g.evidence.length > 1 ? ` (+${g.evidence.length-1} more)` : ''))}`;
    box.appendChild(withAspects(d, [g.aspect]));
  });
}
R.pains = () => moments('pains', 'Ranked by people affected times the worst severity. Dots show severity: one is minor, three blocks the goal or causes real harm.', D.pains, 'neg', true, 'No friction coded yet.');
R.successes = () => moments('successes', 'Where things work well enough that people say so.', D.successes, 'pos', false, 'No success moments coded yet. Mark nuggets with "success": true.');

/* ---------- jobs ---------- */
R.jobs = () => {
  const J = D.jobs;
  if (!J.length){ none('jobs', 'Write jobs.json during synthesis to fill this.'); return; }
  const s = section('jobs', 'What people are trying to get done. The balance shows forces pushing towards change on the left and forces holding them in place on the right.',
    `<div class="forces-key"><span><i class="f-push"></i>Push: pain now</span><span><i class="f-pull"></i>Pull: attraction of something new</span><span><i class="f-anxiety"></i>Anxiety about switching</span><span><i class="f-habit"></i>Habit</span></div><div></div>`);
  const box = s.lastElementChild;
  J.forEach(j => {
    const f = j.forces, tot = Math.max(1, f.push + f.pull, f.anxiety + f.habit);
    const seg = (k, v) => v ? `<span class="seg f-${k}" style="width:${100*v/tot}%" title="${k} ${v}">${v}</span>` : '';
    const lean = (f.push + f.pull) > (f.anxiety + f.habit) ? 'Leaning towards change' : (f.push + f.pull) < (f.anxiety + f.habit) ? 'Held in place' : 'Balanced';
    const d = document.createElement('div'); d.className = 'item';
    d.innerHTML = `<p class="stmt">${esc(j.job)}</p>
      <div class="forces" role="img" aria-label="push ${f.push}, pull ${f.pull}, anxiety ${f.anxiety}, habit ${f.habit}">
        <div class="side l">${seg('pull', f.pull)}${seg('push', f.push)}</div><div class="side">${seg('anxiety', f.anxiety)}${seg('habit', f.habit)}</div></div>
      <div class="metaline"><span>${lean}</span><span>${people(j.voices)}</span>${j.aspects.length ? '<span>' + j.aspects.map(asp).join(', ') + '</span>' : ''}</div>
      ${evList(j.evidence)}`;
    box.appendChild(withAspects(d, j.aspects));
  });
};

/* ---------- framing ---------- */
R.framing = () => {
  const F = D.frames;
  if (!F.length){ section('framing', '', empty('Add "frame" (problem, cause, moral, remedy) to nuggets that frame the story.')); return; }
  const label = {problem:'Defining the problem', cause:'Diagnosing causes', moral:'Moral judgements: who is to blame or praised', remedy:'Proposed remedies'};
  const maxV = Math.max(...F.map(f => f.voices), 1);
  const s = section('framing', 'How people make sense of the story, using Entman\'s four functions of a frame: what the problem is, what caused it, who deserves blame or credit, and what should be done.', '<div></div>');
  const box = s.lastElementChild;
  F.forEach(f => {
    const d = document.createElement('div'); d.className = 'item';
    d.innerHTML = `<h3>${esc(label[f.frame] || f.frame)}</h3>
      <div class="drow" style="margin-top:8px;grid-template-columns:minmax(0,1fr) auto"><div class="track"><div class="fill ink${f.voices <= 1 ? ' thin' : ''}" style="width:${100*f.voices/maxV}%"></div></div><span class="num">${people(f.voices)}</span></div>
      <ul class="ev" style="border-left-color:var(--rule)">${f.evidence.slice(0, 3).map(e => `<li>${esc(e.obs)} <span class="tag">${esc(e.id)}</span></li>`).join('')}</ul>
      ${f.evidence.length > 3 ? evList(f.evidence.slice(3), 'Show ' + (f.evidence.length - 3) + ' more') : ''}
      ${f.aspects.length ? '<div class="metaline" style="margin-top:8px"><span>' + f.aspects.map(asp).join(', ') + '</span></div>' : ''}`;
    box.appendChild(withAspects(d, f.aspects));
  });
};

/* ---------- questions ---------- */
R.questions = () => {
  const Q = D.questions;
  if (!Q.length){ section('questions', '', empty('Tag nuggets "question" when people ask something or say they\'re unsure.')); return; }
  const s = section('questions', 'What people ask or say they\'re unsure about: gaps that clearer information could fill.', '<div></div>');
  const box = s.lastElementChild;
  Q.forEach(g => {
    const d = document.createElement('div'); d.className = 'item';
    d.innerHTML = `<h3>${asp(g.aspect)} <span class="num">${g.evidence.length} ${g.evidence.length === 1 ? 'question' : 'questions'}</span></h3>
      <ul class="ev" style="border-left-color:var(--rule)">${g.evidence.slice(0, 4).map(e => `<li>${esc(e.obs)} <span class="tag">${esc(e.id)}</span></li>`).join('')}</ul>`;
    box.appendChild(withAspects(d, [g.aspect]));
  });
};

/* ---------- opportunities / implications ---------- */
R.opportunities = () => {
  const O = D.opportunities;
  if (!O.length){ none('opportunities', 'Write opportunities.json during synthesis to fill this.'); return; }
  const maxR = Math.max(...O.map(o => o.rank_score), 1);
  const s = section('opportunities', 'Ranked by people affected × (1 + average severity of the pain behind it). A transparent heuristic, not a measured score; items without a pain behind them, such as strengths to build on, rank lower by design.', '<div></div>');
  const box = s.lastElementChild;
  O.forEach(o => {
    const d = document.createElement('div'); d.className = 'item';
    d.innerHTML = `<p class="stmt">${esc(o.statement)}</p>
      <div class="track" style="max-width:520px;margin:4px 0 10px"><div class="fill ink${o.voices <= 1 ? ' thin' : ''}" style="width:${100*o.rank_score/maxR}%"></div></div>
      <div class="metaline"><span>${esc(o.kind)}</span>${o.aspect ? '<span>' + asp(o.aspect) + '</span>' : ''}<span>${people(o.voices)}</span>
      ${o.mean_sev ? `<span>severity ${o.mean_sev} of 3</span>` : ''}${o.neg_rate != null ? `<span>negative ${pct(o.neg_rate)} of the time</span>` : ''}
      ${o.insights.length ? `<span>from ${o.insights.map(esc).join(', ')}</span>` : ''}</div>${evList(o.evidence)}`;
    box.appendChild(withAspects(d, o.aspects));
  });
};

/* ---------- entities ---------- */
R.entities = () => {
  const P = D.products;
  if (!P.length) return;
  let head, rows;
  if (L.jtbd){
    head = '<th>Name</th><th>Mentioned by</th><th>Forces</th><th>Counts</th>';
    rows = P.map(p => {
      const t = Math.max(1, p.push + p.pull + p.anxiety + p.habit);
      const seg = k => p[k] ? `<span class="f-${k}" style="width:${100*p[k]/t}%"></span>` : '';
      return `<tr><td><b>${esc(p.name)}</b></td><td>${people(p.voices)}</td><td><span class="mini" role="img" aria-label="push ${p.push}, pull ${p.pull}, anxiety ${p.anxiety}, habit ${p.habit}">${seg('push')}${seg('pull')}${seg('anxiety')}${seg('habit')}</span></td><td class="num">${p.push} / ${p.pull} / ${p.anxiety} / ${p.habit}</td></tr>`;
    }).join('');
  } else {
    head = '<th>Name</th><th>Mentioned by</th><th>Tone when mentioned (−2 to +2)</th>';
    rows = P.map(p => {
      const m = p.mean, w = m == null ? 0 : Math.abs(m) / 2 * 50;
      const bar = m == null ? '<span class="num">not scored</span>' : `<span class="dvg" role="img" aria-label="mean tone ${m}"><span style="${m < 0 ? `right:50%;width:${w}%;background:var(--neg)` : `left:50%;width:${w}%;background:var(--pos)`}"></span></span> <span class="num">${m}</span>`;
      return `<tr><td><b>${esc(p.name)}</b></td><td>${people(p.voices)}</td><td>${bar}</td></tr>`;
    }).join('');
  }
  section('entities', esc(L.entity_lede || ''), `<div class="scroll"><table class="tbl"><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table></div>`);
};

/* ---------- outlook ---------- */
R.outlook = () => {
  const O = D.outlook;
  if (!O.length){ section('outlook', '', empty('Write outlook.json after running drivers.py to fill this.')); return; }
  const s = section('outlook', 'Judgements, not measurements. Each likelihood word stands for a fixed range (ICD 203), shown as the band on a 0–100% scale. Check each call on its review date.', '<div></div>');
  const box = s.lastElementChild;
  O.forEach(o => {
    const r = o.range || [0,0];
    const d = document.createElement('div'); d.className = 'item';
    d.innerHTML = `<p class="stmt">${esc(o.statement)}</p>
      <div class="metaline"><span class="likely">${esc(o.likelihood)} (${r[0]}–${r[1]}%)</span><span>${esc(o.horizon)}</span>${o.review_by ? `<span>check on ${esc(o.review_by)}</span>` : ''}</div>
      <div class="probaxis" role="img" aria-label="${esc(o.likelihood)}, ${r[0]} to ${r[1]} percent"><div class="band" style="left:${r[0]}%;width:${r[1]-r[0]}%"></div>
        <span class="tick" style="left:0;transform:none">0</span><span class="tick" style="left:50%">50</span><span class="tick" style="left:auto;right:0;transform:none">100%</span></div>
      <p style="margin:26px 0 0;font-size:14px"><b>Would change if:</b> ${esc(o.change)}</p>
      <p class="num" style="margin:4px 0 0;white-space:normal">Based on ${o.basis.map(esc).join(', ')}</p>`;
    box.appendChild(withAspects(d, o.aspects));
  });
};

/* ---------- language ---------- */
R.language = () => {
  const G = D.language;
  if (!G){ section('language', '', empty('Run language.py to fill this.')); return; }
  const K = G.keyness;
  const wl = (arr, cls) => {
    if (!arr || !arr.length) return empty('Nothing distinctive at p < .05.');
    const m = Math.max(...arr.map(x => x.g2));
    return `<ul class="words">${arr.slice(0, 12).map(x => `<li><span class="w">${esc(x.term)}</span><span class="track"><span class="fill ${cls}${x.reach < 3 ? ' thin' : ''}" style="display:block;width:${100*x.g2/m}%"></span></span><span class="num">${people(x.reach)}</span></li>`).join('')}</ul>`;
  };
  const sr = G.signal_rates || {};
  const labels = L.jtbd
    ? {switching_language:'Talk of switching or leaving', workaround_language:'Workarounds', constraint_language:'Being blocked ("had to", "couldn\'t")', implicit_request:'Implicit requests ("I wish", "is there a way")'}
    : {implicit_request:'Wishes and requests ("I wish", "why can\'t")', constraint_language:'Constraint ("had to", "couldn\'t")', switching_language:'Leaving or switching'};
  const maxS = Math.max(1, ...Object.keys(labels).map(k => sr[k] || 0));
  const sig = Object.keys(labels).map(k => `<div class="drow" style="grid-template-columns:minmax(0,220px) minmax(0,1fr) auto"><span>${labels[k]}</span><div class="track"><div class="fill prob" style="width:${100*(sr[k]||0)/maxS}%"></div></div><span class="num">${pct(sr[k])}</span></div>`).join('');
  section('language', 'Words statistically over-used in negative versus positive comments (log-likelihood, p < .05), phrases many people share, and how often certain kinds of language appear.',
    `${K ? `<div class="two"><div><h3 style="margin-bottom:10px">Marks negative comments</h3>${wl(K.negative, 'neg')}</div><div><h3 style="margin-bottom:10px">Marks positive comments</h3>${wl(K.positive, 'pos')}</div></div>` : empty('Needs the sentiment sample for the negative/positive comparison.')}
     <h3 style="margin:28px 0 10px">Phrases many people use</h3><div class="phrases">${(G.phrases||[]).slice(0, 18).map(p => `<span>${esc(p.phrase)}<small>${p.reach}</small></span>`).join('') || empty('No phrase used by three or more people.')}</div>
     <h3 style="margin:28px 0 10px">Kinds of language, % of ${M.mode === 'reddit' ? 'comments' : 'turns'}</h3><div class="rows">${sig}</div>`);
};

/* ---------- trust ---------- */
R.trust = () => {
  const T = D.trust, v = T.validation;
  const agree = v && v.alpha != null
    ? `Krippendorff's alpha ${v.alpha} on ${v.n} comments${v.alpha < 0.667 ? ' <span class="warnline">(below 0.667: treat sentiment figures as unreliable)</span>' : v.alpha < 0.8 ? ' (tentative; 0.8 is the usual bar)' : ''}`
    : '<span class="warnline">Not measured yet.</span> Hand-code a blind sample and compare with the AI before relying on sentiment figures.';
  const mix = Object.entries(T.evidence_mix || {}).map(([k, n]) => `${k.replace('_',' ')} ${n}`).join(', ');
  const rows = [
    ['Subject and lens', `${esc(M.title)} (${esc(L.label)})`],
    S.questions && S.questions.length ? ['Research questions', S.questions.map(esc).join('<br>')] : null,
    S.stance_target ? ['Proposition for stance', esc(S.stance_target)] : null,
    ['How material was found', (T.collection || []).map(c => `${esc(c.site)}: ${c.threads} ${c.threads === 1 ? 'thread' : 'threads'}, ${c.posts} posts${c.kinds.length ? ' (' + c.kinds.join(', ') + ')' : ''}${c.queries.length ? '; searched for ' + c.queries.map(q => '"' + esc(q) + '"').join(', ') : ''}`).join('<br>') +
      ((T.collection || []).some(c => !c.queries.length) ? '<br><span class="warnline">Some sources have no recorded search, so how they were chosen is unknown.</span>' : '') +
      (T.collection_log && T.collection_log.length ? `<br>${T.collection_log.length} searches logged, including ones that yielded nothing kept.` : '')],
    T.forum_checks ? ['Capture checks', `Pasted posts checked word-for-word against the originals. ${T.forum_checks.screenshot_posts_unverified ? `<span class="warnline">${T.forum_checks.screenshot_posts_unverified} screenshot posts not cross-checked with OCR.</span> ` : 'Screenshot transcriptions cross-checked with OCR' + (T.forum_checks.warnings.length ? ` (<span class="warnline">${T.forum_checks.warnings.length} flagged for a human look</span>)` : '') + '. '}${Object.values(T.forum_checks.duplicates_dropped || {}).reduce((a, b) => a + b, 0)} duplicates dropped; ${T.forum_checks.promotional_flagged} promotional posts flagged.`] : null,
    ['Sentiment measured on', T.sentiment_sample ? `a random sample of ${T.sentiment_sample} comments${T.sample_of ? ' out of ' + T.sample_of : ''}` : 'no random sample yet'],
    ['Read in detail', T.read_in_detail ? `${T.read_in_detail} of ${T.candidates}, chosen for signals, votes and topic spread, max ${T.per_author_cap} per person${T.echoes ? '; ' + T.echoes + ' short agree/disagree replies counted, not read' : ''}` : 'all material'],
    ['AI coding checked against a human', agree],
    ['Evidence behind coded comments', mix || '—'],
    ['Direction', T.direction_status === 'ok' ? 'Several periods compared' : 'Snapshot: no trend can be claimed'],
    ['Topic clusters', T.silhouette != null ? `separation score ${T.silhouette} (${T.silhouette < 0.1 ? 'loose' : T.silhouette < 0.3 ? 'moderate' : 'clear'})` : 'not run'],
    ['Quotes', T.quotes === 'withheld' ? 'Withheld. Evidence is paraphrased with ids that trace to source files kept privately.' : 'Included for internal use'],
    ['Who this describes', S.population ? esc(S.population) : (M.mode === 'reddit' ? 'People who chose to post in these communities. They skew vocal and are not a sample of all users, customers or the public.' : 'The participants interviewed, not the whole population.')],
  ].filter(Boolean);
  const s = section('trust', '', `<div class="trust"><dl>${rows.map(r => `<dt>${r[0]}</dt><dd>${r[1]}</dd>`).join('')}</dl></div>`);
  s.querySelector('h2').insertAdjacentHTML('afterend', `<div class="keyline" style="margin-top:10px"><span><span class="sw"></span>solid: several voices</span><span><span class="sw thin" style="background:none;background-image:repeating-linear-gradient(135deg,var(--ink) 0 2px,transparent 2px 6px)"></span>hatched: one voice or low confidence</span></div>`);
};

(L.sections || Object.keys(R)).forEach(id => { if (R[id]) R[id](); });

/* ---------- nav ---------- */
document.getElementById('rail').innerHTML = sections.map(([id, t]) => `<a href="#${id}">${esc(t)}</a>`).join('');

/* ---------- focus ---------- */
const bar = document.getElementById('focusbar'), ftext = document.getElementById('focustext');
function setFocus(a){
  document.querySelectorAll('[data-aspects]').forEach(el => {
    const list = el.dataset.aspects ? el.dataset.aspects.split('|') : [];
    el.classList.toggle('hide', !!a && !list.includes(a));
  });
  bar.classList.toggle('on', !!a);
  ftext.textContent = a ? 'Focused on ' + a : '';
}
main.addEventListener('click', e => {
  const b = e.target.closest('[data-focus]');
  if (b){ setFocus(b.getAttribute('data-focus')); bar.scrollIntoView({block:'nearest'}); }
});
main.addEventListener('keydown', e => {
  const b = e.target.closest('g[data-focus]');
  if (b && (e.key === 'Enter' || e.key === ' ')){ e.preventDefault(); setFocus(b.getAttribute('data-focus')); }
});
document.getElementById('clearFocus').addEventListener('click', () => setFocus(null));

/* ---------- copy safe wording ---------- */
const cs = document.getElementById('copySafe');
if (cs) cs.addEventListener('click', async () => {
  const t = document.getElementById('safeT').textContent;
  try { await navigator.clipboard.writeText(t); cs.textContent = 'Copied'; }
  catch(e){ const r = document.createRange(); r.selectNodeContents(document.getElementById('safeT')); const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r); cs.textContent = 'Selected: copy with your keyboard'; }
});

/* ---------- theme toggle ---------- */
const root = document.documentElement;
try { const t = localStorage.getItem('dash-theme'); if (t) root.dataset.theme = t; } catch(e){}
const tt = document.getElementById('themeT');
if (tt) tt.addEventListener('click', () => {
  const dark = root.dataset.theme ? root.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
  root.dataset.theme = dark ? 'light' : 'dark';
  try { localStorage.setItem('dash-theme', root.dataset.theme); } catch(e){}
});
})();
