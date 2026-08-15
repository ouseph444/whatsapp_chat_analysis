"""Build a self-contained HTML report from the executed analysis notebook.

    python build_report.py [NOTEBOOK.ipynb] [report_data.json] [OUTPUT.html]

Every figure, table and console output of the executed notebook is embedded in a
single HTML file — images inline as data URIs, so the page needs no network.
"""
import json, re, sys, html as htmllib
import nbformat, markdown

NB   = sys.argv[1] if len(sys.argv) > 1 else "whatsapp_chat_analysis.ipynb"
DATA = sys.argv[2] if len(sys.argv) > 2 else "report_data.json"
OUT  = sys.argv[3] if len(sys.argv) > 3 else "chat_report.html"

nb = nbformat.read(NB, as_version=4)
D  = json.load(open(DATA))
MD = markdown.Markdown(extensions=["tables", "sane_lists", "attr_list"])

# ---------------------------------------------------------------- helpers
STYLE_BLOCK = re.compile(r"<style scoped>.*?</style>", re.S)

def clean_table(h):
    h = STYLE_BLOCK.sub("", h)
    h = h.replace(' border="1"', "").replace(' class="dataframe"', ' class="df"')
    if ">bar</th>" in h:            # the ASCII bar column reads left-to-right
        h = h.replace(' class="df"', ' class="df has-ascii"')
    return f'<div class="table-wrap">{h.strip()}</div>'

def esc(s):
    return htmllib.escape(s)

def esc_title(s):
    """Escape, then honour the *emphasis* and `code` marks used in headings."""
    s = htmllib.escape(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"\*(.+?)\*", r"<em>\1</em>", s)
    s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    return s

def render_md(src):
    MD.reset()
    return MD.convert(src)

def highlights_block(text):
    rows = []
    for line in text.strip().split("\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            rows.append(f'<div class="hl-k">{esc(k.strip())}</div>'
                        f'<div class="hl-v">{esc(v.strip())}</div>')
    return f'<div class="highlights">{"".join(rows)}</div>'

# ---------------------------------------------------------------- walk notebook
SHORT = {  # nav labels, in notebook section order
    1: "Setup", 2: "Parsing", 3: "Cleaning", 4: "Participation", 5: "Volume",
    6: "Message types", 7: "Over time", 8: "Day & week", 9: "Rhythms",
    10: "Interaction", 11: "Emoji", 12: "Words", 13: "Links", 14: "Records",
    15: "Summary",
}

sections, notes_html, fig_count = [], "", 0
cur = None

for cell in nb.cells[1:]:                       # cell 0 is the notebook title page
    if cell.cell_type == "markdown":
        src = cell.source.strip()
        if "Method notes & caveats" in src:
            notes_html = render_md(src.lstrip("-").strip())
            continue
        m = re.match(r"^##\s+(\d+)\.\s+(.*)", src)
        if m:
            if cur: sections.append(cur)
            num, title = int(m.group(1)), m.group(2).strip()
            rest = src.split("\n", 1)[1] if "\n" in src else ""
            cur = {"num": num, "title": title, "label": SHORT.get(num, title),
                   "html": [render_md(rest.strip())] if rest.strip() else []}
            continue
        if cur is not None:
            cur["html"].append(f'<div class="prose">{render_md(src)}</div>')
        continue

    # ---- code cell: outputs first, then the collapsed source
    if cur is None:
        continue
    parts = []
    for out in cell.get("outputs", []):
        data = out.get("data", {})
        if "image/png" in data:
            fig_count += 1
            parts.append(
                f'<figure class="fig"><img loading="lazy" '
                f'src="data:image/png;base64,{data["image/png"].strip()}" '
                f'alt="Chart {fig_count}: {esc(cur["title"])}"></figure>')
        elif "text/html" in data:
            parts.append(clean_table("".join(data["text/html"])))
        elif out.get("output_type") == "stream":
            txt = out["text"]
            parts.append(highlights_block(txt) if txt.lstrip().startswith("GROUP:")
                         else f'<pre class="out">{esc(txt.rstrip())}</pre>')
        elif "text/plain" in data and out.get("output_type") == "execute_result":
            parts.append(f'<pre class="out">{esc("".join(data["text/plain"]).rstrip())}</pre>')

    code_src = cell.source.strip()
    if code_src:
        parts.append('<details class="code"><summary>Code</summary>'
                     f'<pre><code>{esc(code_src)}</code></pre></details>')
    cur["html"].append(f'<div class="block">{"".join(parts)}</div>')

if cur: sections.append(cur)

# ---------------------------------------------------------------- page pieces
TITLE = D.get("current_name") or D.get("group_created_name") or "This Chat"
members = D["members"]
top = members[0]
max_msgs = max(m["messages"] for m in members)

leader_rows = "".join(f'''
      <li class="lb-row">
        <span class="lb-name">{esc(m["name"])}</span>
        <span class="lb-track"><span class="lb-bar" style="width:{m["messages"]/max_msgs*100:.2f}%;background:{m["color"]}"></span></span>
        <span class="lb-val">{m["messages"]:,}</span>
        <span class="lb-share">{m["share"]:.1f}%</span>
      </li>''' for m in members)

STATS = [
    (f'{D["total_messages"]:,}', "messages"),
    (str(D["n_members"]), "members"),
    (f'{D["active_days"]:,}', "days with chat"),
    (str(D["msgs_per_active_day"]), "messages / active day"),
    (f'{D["words"]:,}', "words typed"),
    (f'{D["media"]:,}', "photos, voice notes, stickers"),
]
stat_tiles = "".join(f'''
      <div class="stat"><div class="stat-n">{n}</div><div class="stat-l">{l}</div></div>'''
      for n, l in STATS)

card_rows = "".join(f'''
      <article class="mcard" style="--c:{m["color"]}">
        <header><span class="dot"></span><h3>{esc(m["name"])}</h3><span class="rank">#{i+1}</span></header>
        <dl>
          <div><dt>messages</dt><dd>{m["messages"]:,}</dd></div>
          <div><dt>share of chat</dt><dd>{m["share"]:.1f}%</dd></div>
          <div><dt>words</dt><dd>{m["words"]:,}</dd></div>
          <div><dt>words / message</dt><dd>{m["avg_words"]}</dd></div>
          <div><dt>media sent</dt><dd>{m["media"]:,}</dd></div>
          <div><dt>links shared</dt><dd>{m["links"]:,}</dd></div>
          <div><dt>threads started</dt><dd>{m["starters"]:,}</dd></div>
          <div><dt>median reply</dt><dd>{m["median_reply_min"]} min</dd></div>
          <div><dt>days present</dt><dd>{m["active_days"]:,}</dd></div>
          <div><dt>peak hour</dt><dd>{m["peak_hour"]:02d}:00</dd></div>
          <div><dt>after midnight</dt><dd>{m["night_pct"]}%</dd></div>
          <div><dt>emoji / 100 msgs</dt><dd>{m["emoji_per_100"]:.1f}</dd></div>
        </dl>
        <p class="mcard-foot"><span class="lab">favourite emoji</span> <span class="emo">{esc(m["top_emoji"])}</span></p>
        <p class="mcard-foot"><span class="lab">most-typed words</span> {esc(m["top_words"])}</p>
      </article>''' for i, m in enumerate(members))

nav_links = "".join(
    f'<a href="#s{s["num"]}"><i>{s["num"]:02d}</i>{esc(s["label"])}</a>' for s in sections)

section_html = "".join(f'''
    <section id="s{s["num"]}">
      <div class="sec-head">
        <span class="sec-num">{s["num"]:02d}</span>
        <h2>{esc_title(s["title"])}</h2>
      </div>
      {"".join(s["html"])}
    </section>''' for s in sections)

CSS = """
/* Committed to a single light theme: the 31 charts are baked in as images on a
   #fcfcfb surface, so the page adopts that exact paper tone and every colour is
   painted explicitly — the sheet looks the same on any host background. */
:root{
  --paper:#fcfcfb;      /* identical to the charts' own surface */
  --ground:#e9e8e2;     /* the desk the sheet sits on */
  --ink:#0b0b0b;
  --ink-2:#52514e;
  --ink-3:#898781;
  --rule:#e1e0d9;
  --rule-2:#c9c8c0;
  --accent:#104281;     /* deepest step of the charts' blue ramp */
  --accent-soft:#cde2fb;
  --serif:"Iowan Old Style","Palatino Linotype",Palatino,"Book Antiqua",Georgia,serif;
  --sans:-apple-system,BlinkMacSystemFont,"Helvetica Neue",Helvetica,Arial,sans-serif;
  --mono:ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,monospace;
  --col:1180px;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
body{
  margin:0;background:var(--ground);color:var(--ink);overflow-x:hidden;
  font-family:var(--sans);font-size:16px;line-height:1.62;
  -webkit-font-smoothing:antialiased;
}
.sheet{max-width:var(--col);margin:0 auto;background:var(--paper);
  border-left:1px solid var(--rule);border-right:1px solid var(--rule)}
.pad{padding:0 clamp(18px,4.5vw,64px)}
h1,h2,h3{text-wrap:balance;margin:0}
a{color:var(--accent);text-underline-offset:3px;text-decoration-thickness:1px}
a:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:3px;border-radius:2px}

/* ---------- masthead ---------- */
.masthead{padding-top:clamp(36px,6vw,76px);padding-bottom:clamp(28px,4vw,44px)}
.eyebrow{font-family:var(--mono);font-size:.7rem;letter-spacing:.16em;
  text-transform:uppercase;color:var(--ink-3);margin:0 0 18px}
.eyebrow b{color:var(--accent);font-weight:600}
h1{font-family:var(--serif);font-weight:400;font-size:clamp(1.95rem,6.4vw,4.4rem);
  overflow-wrap:break-word;
  line-height:1.02;letter-spacing:-.015em}
h1 em{font-style:italic;color:var(--accent)}
.deck{max-width:56ch;margin:20px 0 0;font-size:clamp(1.02rem,1.7vw,1.2rem);
  color:var(--ink-2);line-height:1.55}
.byline{font-family:var(--mono);font-size:.72rem;letter-spacing:.08em;color:var(--ink-3);
  margin-top:26px;padding-top:14px;border-top:1px solid var(--rule)}

/* ---------- stat strip ---------- */
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(148px,100%),1fr));
  border-top:1px solid var(--rule-2);border-bottom:1px solid var(--rule-2)}
.stat{padding:22px 22px 20px;border-right:1px solid var(--rule)}
.stat:last-child{border-right:0}
.stat-n{font-family:var(--mono);font-size:clamp(1.5rem,2.6vw,2rem);
  font-variant-numeric:tabular-nums;letter-spacing:-.02em;line-height:1.1}
.stat-l{font-size:.78rem;color:var(--ink-3);margin-top:6px;line-height:1.35}

/* ---------- leaderboard ---------- */
.lead{padding-top:clamp(34px,5vw,54px);padding-bottom:8px}
.kicker{font-family:var(--mono);font-size:.7rem;letter-spacing:.16em;text-transform:uppercase;
  color:var(--accent);margin:0 0 10px}
.lead h2{font-family:var(--serif);font-weight:400;font-size:clamp(1.5rem,3vw,2.1rem);line-height:1.15}
.lead p.note{max-width:64ch;color:var(--ink-2);margin:12px 0 26px}
.lb{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:12px}
.lb-row{display:grid;grid-template-columns:minmax(96px,150px) 1fr auto auto;
  align-items:center;gap:14px}
.lb-name{font-size:.95rem;font-weight:600}
.lb-track{height:22px;background:#f2f1ec;border-radius:2px}
.lb-bar{display:block;height:100%;border-radius:2px 4px 4px 2px}
.lb-val,.lb-share{font-family:var(--mono);font-variant-numeric:tabular-nums;font-size:.9rem}
.lb-val{color:var(--ink)}
.lb-share{color:var(--ink-3);min-width:52px;text-align:right}

/* ---------- member cards ---------- */
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(202px,100%),1fr));
  gap:1px;background:var(--rule);border-top:1px solid var(--rule);
  border-bottom:1px solid var(--rule);margin-top:clamp(34px,5vw,54px)}
.mcard{background:var(--paper);padding:22px 22px 24px}
.mcard header{display:flex;align-items:center;gap:9px;margin-bottom:14px}
.mcard h3{font-size:1rem;font-weight:600;flex:1}
.mcard .dot{width:11px;height:11px;border-radius:50%;background:var(--c);flex:none}
.mcard .rank{font-family:var(--mono);font-size:.72rem;color:var(--ink-3)}
.mcard dl{margin:0;display:grid;grid-template-columns:1fr;gap:0}
.mcard dl>div{display:flex;justify-content:space-between;gap:10px;
  padding:5px 0;border-bottom:1px dotted var(--rule)}
.mcard dt{font-size:.8rem;color:var(--ink-3)}
.mcard dd{margin:0;font-family:var(--mono);font-size:.82rem;font-variant-numeric:tabular-nums}
.mcard-foot{margin:12px 0 0;font-size:.8rem;color:var(--ink-2);line-height:1.5}
.mcard-foot .lab{display:block;font-family:var(--mono);font-size:.66rem;
  letter-spacing:.12em;text-transform:uppercase;color:var(--ink-3);margin-bottom:2px}
.mcard-foot .emo{font-size:1.15rem;letter-spacing:.12em}

/* ---------- nav ---------- */
nav{position:sticky;top:0;z-index:20;background:rgba(252,252,251,.94);
  backdrop-filter:blur(8px);border-top:1px solid var(--rule-2);
  border-bottom:1px solid var(--rule-2);margin-top:clamp(34px,5vw,54px)}
.nav-inner{display:flex;gap:2px;overflow-x:auto;scrollbar-width:thin}
nav a{flex:none;display:flex;align-items:baseline;gap:6px;padding:11px 14px;
  font-size:.8rem;color:var(--ink-2);text-decoration:none;white-space:nowrap;
  border-bottom:2px solid transparent}
nav a i{font-family:var(--mono);font-style:normal;font-size:.66rem;color:var(--ink-3)}
nav a:hover{color:var(--ink);background:#f4f3ef}
nav a.on{color:var(--accent);border-bottom-color:var(--accent)}
nav a.on i{color:var(--accent)}

/* ---------- sections ---------- */
main{padding-bottom:20px}
section{padding:clamp(38px,5.5vw,64px) clamp(18px,4.5vw,64px);border-bottom:1px solid var(--rule);
  scroll-margin-top:56px}
.sec-head{display:grid;grid-template-columns:auto 1fr;gap:16px;align-items:baseline;
  margin-bottom:22px}
.sec-num{font-family:var(--mono);font-size:.82rem;color:var(--accent);
  padding-top:6px;letter-spacing:.06em}
.sec-head h2{font-family:var(--serif);font-weight:400;
  font-size:clamp(1.45rem,2.9vw,2.05rem);line-height:1.14;letter-spacing:-.01em}
.prose,section>p,section>ul,section>ol,section>h3,section>h4,section>blockquote{max-width:70ch}
.prose p,section>p{margin:0 0 14px;color:var(--ink-2)}
.prose h3,section h3{font-size:1rem;font-weight:600;color:var(--ink);margin:26px 0 8px}
.prose ul,.prose ol,section>ul,section>ol{color:var(--ink-2);padding-left:20px;margin:0 0 14px}
.prose li,section li{margin-bottom:6px}
.prose code,section code{font-family:var(--mono);font-size:.86em;background:#f2f1ec;
  padding:1px 5px;border-radius:3px;color:var(--ink)}
.prose pre code{background:none;padding:0}
.prose pre{background:#f6f5f1;border:1px solid var(--rule);border-radius:4px;
  padding:12px 14px;overflow-x:auto;font-size:.82rem}
.prose strong{color:var(--ink)}

.block{margin:22px 0 0}
.fig{margin:0 0 6px}
.fig img{display:block;width:100%;max-width:100%;height:auto;background:var(--paper)}
.out{font-family:var(--mono);font-size:.78rem;line-height:1.55;color:var(--ink-2);
  background:#f6f5f1;border-left:2px solid var(--rule-2);padding:12px 14px;
  overflow-x:auto;margin:0 0 8px;white-space:pre}

/* ---------- tables ---------- */
.table-wrap{overflow-x:auto;margin:0 0 10px;border:1px solid var(--rule);border-radius:3px}
table.df{border-collapse:collapse;width:100%;font-size:.8rem;
  font-variant-numeric:tabular-nums;background:var(--paper)}
table.df th,table.df td{padding:7px 12px;text-align:right;white-space:nowrap;
  border-bottom:1px solid var(--rule)}
table.df thead th{position:sticky;top:0;background:#f4f3ef;color:var(--ink);
  font-weight:600;font-size:.74rem;letter-spacing:.02em;text-align:right;
  border-bottom:1px solid var(--rule-2)}
table.df tbody th{text-align:left;font-weight:600;color:var(--ink);
  font-family:var(--sans);white-space:nowrap}
table.df tbody tr:last-child td,table.df tbody tr:last-child th{border-bottom:0}
table.df tbody tr:hover td,table.df tbody tr:hover th{background:#f7f6f2}
table.has-ascii td:last-child{text-align:left;font-family:var(--mono);
  letter-spacing:-1px;color:var(--accent);width:60%}

/* ---------- highlights ---------- */
.highlights{display:grid;grid-template-columns:minmax(150px,220px) 1fr;gap:0 18px;
  border-top:1px solid var(--rule-2);margin:6px 0 10px}
.hl-k{font-family:var(--mono);font-size:.72rem;letter-spacing:.06em;text-transform:uppercase;
  color:var(--ink-3);padding:9px 0;border-bottom:1px solid var(--rule)}
.hl-v{font-size:.92rem;color:var(--ink);padding:9px 0;border-bottom:1px solid var(--rule)}

/* ---------- code toggle ---------- */
details.code{margin:6px 0 0;border-top:1px solid var(--rule)}
details.code summary{cursor:pointer;list-style:none;font-family:var(--mono);
  font-size:.7rem;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-3);
  padding:8px 0}
details.code summary::-webkit-details-marker{display:none}
details.code summary::before{content:"+ ";color:var(--accent)}
details.code[open] summary::before{content:"– "}
details.code summary:hover{color:var(--ink)}
details.code pre{background:#f6f5f1;border:1px solid var(--rule);border-radius:4px;
  padding:14px 16px;overflow-x:auto;font-size:.78rem;line-height:1.55;margin:0 0 14px}
details.code code{font-family:var(--mono);color:var(--ink-2)}

/* ---------- footer ---------- */
footer{padding:clamp(38px,5.5vw,64px) clamp(18px,4.5vw,64px) 72px}
footer h3{font-family:var(--serif);font-weight:400;font-size:1.4rem;margin-bottom:14px}
footer .prose{max-width:72ch}
.colophon{margin-top:34px;padding-top:16px;border-top:1px solid var(--rule);
  font-family:var(--mono);font-size:.7rem;letter-spacing:.06em;color:var(--ink-3);
  display:flex;flex-wrap:wrap;gap:8px 18px;justify-content:space-between}

@media (max-width:640px){
  .stat{border-right:0;border-bottom:1px solid var(--rule)}
  section{padding-left:18px;padding-right:18px}
  .lb-row{grid-template-columns:minmax(78px,1fr) 2fr auto;gap:10px}
  .lb-share{display:none}
  .sec-head{grid-template-columns:1fr;gap:4px}
  .sec-num{padding-top:0}
  .highlights{grid-template-columns:1fr;gap:0}
  .hl-k{padding-bottom:0;border-bottom:0}
  .hl-v{padding-top:2px}
}
@media print{
  body{background:#fff}
  nav{display:none}
  .sheet{border:0;max-width:none}
  section{break-inside:auto;border-bottom:0}
  .fig,.table-wrap,.mcard{break-inside:avoid}
  details.code{display:none}
}
"""

JS = """
const links=[...document.querySelectorAll('nav a')];
const map=new Map(links.map(a=>[a.getAttribute('href').slice(1),a]));
const io=new IntersectionObserver(es=>{
  es.forEach(e=>{
    if(e.isIntersecting){
      links.forEach(a=>a.classList.remove('on'));
      const a=map.get(e.target.id);
      if(a){a.classList.add('on');
        a.scrollIntoView({block:'nearest',inline:'nearest',behavior:'auto'});}
    }
  });
},{rootMargin:'-52px 0px -75% 0px'});
document.querySelectorAll('main section').forEach(s=>io.observe(s));
"""

PAGE = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(TITLE)} in Numbers</title>
<style>{CSS}</style>
</head>
<body>
<div class="sheet">

  <header class="masthead pad">
    <p class="eyebrow">WhatsApp group report &nbsp;·&nbsp; <b>{D["first_message"]} — {D["last_message"]}</b></p>
    <h1>Who is really<br>talking in <em>{esc(TITLE)}</em>?</h1>
    <p class="deck">{D["total_messages"]:,} messages from {D["n_members"]} people over
      {D["span_days"]:,} days — counted, split by author, and pulled apart by hour,
      weekday, media type, emoji, vocabulary and reply speed.</p>
    <p class="byline">Group created {D["created"]} &nbsp;·&nbsp; renamed {D["renames"]} times
      &nbsp;·&nbsp; first message in this export {D["first_message"]}</p>
  </header>

  <div class="stats">{stat_tiles}
  </div>

  <section class="lead pad" style="border-bottom:0">
    <p class="kicker">The headline answer</p>
    <h2>Participation, by message count</h2>
    <p class="note">Every message anyone ever sent, split by author. {esc(top["name"])} alone
      accounts for {top["share"]:.1f}% of the chat; the top two together carry
      {members[0]["share"] + members[1]["share"]:.1f}%.</p>
    <ol class="lb">{leader_rows}
    </ol>
  </section>

  <div class="cards">{card_rows}
  </div>

  <nav aria-label="Report sections"><div class="nav-inner">{nav_links}</div></nav>

  <main>{section_html}
  </main>

  <footer>
    <h3>Method notes &amp; caveats</h3>
    <div class="prose">{notes_html}</div>
    <div class="colophon">
      <span>Source: _chat.txt &nbsp;·&nbsp; {D["total_messages"]:,} messages parsed</span>
      <span>Full analysis: whatsapp_chat_analysis.ipynb</span>
    </div>
  </footer>

</div>
<script>{JS}</script>
</body>
</html>
"""

open(OUT, "w").write(PAGE)
print(f"wrote {OUT}")
print(f"{len(sections)} sections · {fig_count} figures · {len(PAGE)/1e6:.2f} MB")
