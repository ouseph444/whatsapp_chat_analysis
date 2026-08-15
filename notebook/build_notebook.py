"""Generate the analysis notebook.

    python build_notebook.py [OUTPUT.ipynb]

Writes an unexecuted notebook (code only, no outputs). Run it with Jupyter, or
execute it in place:

    jupyter nbconvert --to notebook --execute --inplace whatsapp_chat_analysis.ipynb

The notebook reads ./_chat.txt from its own working directory.
"""
import sys
import nbformat as nbf

nb = nbf.v4.new_notebook()
cells = []
def md(s): cells.append(nbf.v4.new_markdown_cell(s.strip('\n')))
def code(s): cells.append(nbf.v4.new_code_cell(s.strip('\n')))

md(r"""
# WhatsApp Chat Analysis

A full exploratory analysis of an exported WhatsApp chat (`_chat.txt`), centred on
**who participates how much**, and extended with time, content, media, emoji,
language and interaction analysis.

**Contents**

1. Setup, chart theme & palette
2. Parsing the export
3. Cleaning: members vs. system messages, message typing
4. **Participation — messages per member** (the headline question)
5. Volume beyond message count: words, characters, message length
6. Message-type composition per member (text / image / audio / sticker / …)
7. Activity over time — years, months, monthly share, daily timeline
8. Rhythm of the day — hour, weekday, hour×weekday heatmaps
9. Per-member daily rhythm & night-owl index
10. Interaction — who follows whom, conversation starters, response times
11. Emoji analysis
12. Words & language
13. Links, media and deleted/edited messages
14. Records, streaks and milestones
15. Master summary table & key findings
""")

# ---------------------------------------------------------------- 1. setup
md("""
## 1. Setup, chart theme & palette

All charts share one accessible palette. Each member keeps **the same colour in
every chart** (colour follows the person, never their rank), and bars carry direct
value labels so nothing depends on colour alone.
""")

code(r'''
import re, math, warnings, collections
from datetime import timedelta

import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.ticker import FuncFormatter

warnings.filterwarnings("ignore")
pd.set_option("display.max_rows", 120)
pd.set_option("display.width", 160)

# ---- palette (validated for colour-vision deficiency on a light surface) ----
SURFACE   = "#fcfcfb"
INK       = "#0b0b0b"
INK_2     = "#52514e"
MUTED     = "#898781"
GRID      = "#e1e0d9"
AXIS      = "#c3c2b7"
CATEGORICAL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4",
               "#008300", "#4a3aa7", "#e34948"]
SEQ_BLUE = LinearSegmentedColormap.from_list(
    "seq_blue", ["#eef5fe", "#cde2fb", "#9ec5f4", "#5598e7", "#2a78d6",
                 "#1c5cab", "#104281", "#0d366b"])

mpl.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
    "figure.dpi": 140, "font.size": 10,
    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
    "text.color": INK, "axes.labelcolor": INK_2, "axes.edgecolor": AXIS,
    "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.titlesize": 13, "axes.titleweight": "600",
    "axes.titlecolor": INK, "axes.titlelocation": "left", "axes.titlepad": 12,
    "axes.spines.top": False, "axes.spines.right": False,
    "grid.color": GRID, "grid.linewidth": 0.8,
    "legend.frameon": False, "figure.autolayout": False,
})

def style(ax, xgrid=False, ygrid=False, title=None, sub=None, xlabel=None, ylabel=None):
    """Recessive chrome: grid behind the marks, no box, left-aligned title."""
    ax.set_axisbelow(True)
    ax.grid(axis="x" if xgrid else "y", visible=xgrid or ygrid)
    if title:
        ax.set_title(title, pad=18 if sub else 12)
        if sub:
            ax.text(0, 1.02, sub, transform=ax.transAxes, color=INK_2,
                    fontsize=9.5, va="bottom")
    if xlabel: ax.set_xlabel(xlabel, fontsize=9.5)
    if ylabel: ax.set_ylabel(ylabel, fontsize=9.5)
    return ax

def hbar_labels(ax, bars, values, fmt="{:,.0f}", pad=None):
    """Direct labels at the end of horizontal bars."""
    span = max(values) if len(values) else 1
    pad = pad if pad is not None else span * 0.012
    for b, v in zip(bars, values):
        ax.text(b.get_width() + pad, b.get_y() + b.get_height()/2, fmt.format(v),
                va="center", ha="left", fontsize=9.5, color=INK_2)
    ax.set_xlim(0, span * 1.16)

def vbar_labels(ax, bars, values, fmt="{:,.0f}", fontsize=8.5):
    span = max(values) if len(values) else 1
    for b, v in zip(bars, values):
        ax.text(b.get_x() + b.get_width()/2, b.get_height() + span*0.015,
                fmt.format(v), ha="center", va="bottom", fontsize=fontsize, color=INK_2)
    ax.set_ylim(0, span * 1.14)

thousands = FuncFormatter(lambda x, _: f"{x:,.0f}")
print("Setup complete ·", mpl.__version__, "· pandas", pd.__version__)
''')

# ---------------------------------------------------------------- 2. parse
md("""
## 2. Parsing the export

WhatsApp's iOS export writes one message as

```
[dd/mm/yyyy, h:mm:ss AM] Sender Name: message text
```

with two complications: invisible LTR/RTL marks (`U+200E`, `U+200F`) and a narrow
no-break space before `AM`/`PM`, and **multi-line messages** whose continuation
lines carry no timestamp. The parser strips the invisible marks, matches the
header with a regex, and appends any non-matching line to the previous message.
""")

code(r'''
CHAT_FILE = "_chat.txt"

raw = open(CHAT_FILE, encoding="utf-8").read()
raw = raw.replace("‎", "").replace("‏", "").replace("\r", "")

HEADER = re.compile(
    r"^\[(\d{1,2}/\d{1,2}/\d{4}), (\d{1,2}:\d{2}:\d{2})\s*([APap][Mm])\]\s(.*)$")

records, dropped = [], 0
for line in raw.split("\n"):
    m = HEADER.match(line)
    if m:
        date, time, ampm, rest = m.groups()
        if ":" in rest:                       # "Sender: text"
            sender, text = rest.split(":", 1)
            text = text[1:] if text.startswith(" ") else text
        else:                                 # timestamped system notice
            sender, text = "", rest
        records.append({"date": date, "time": f"{time} {ampm.upper()}",
                        "sender": sender.strip(), "text": text})
    elif records:                             # continuation of a multi-line message
        records[-1]["text"] += "\n" + line
    elif line.strip():
        dropped += 1

df = pd.DataFrame(records)
df["datetime"] = pd.to_datetime(df["date"] + " " + df["time"],
                                format="%d/%m/%Y %I:%M:%S %p", errors="coerce")

print(f"raw lines           : {raw.count(chr(10)):,}")
print(f"parsed messages     : {len(df):,}")
print(f"unparsed timestamps : {df['datetime'].isna().sum()}")
print(f"dropped lines       : {dropped}")
df.head(6)
''')

# ---------------------------------------------------------------- 3. clean
md("""
## 3. Cleaning — real members vs. system notices, and message typing

The export mixes three things: **member messages**, **system notices** (group
created / icon changed / message pinned, all attributed to the group name or to
`You`), and the **Meta AI** assistant. Only the first group counts as
participation; the other two are kept aside and reported separately.

Every message is then typed — text, image, audio (voice notes), sticker, video,
GIF, document, contact card, deleted — from WhatsApp's `… omitted` placeholders.
""")

code(r'''
SYSTEM_PAT = re.compile(
    r"(created this group|added|left$|left the group|removed|joined using|"
    r"changed the group|changed this group|changed the subject|pinned a message|"
    r"You were|end-to-end encrypted|changed their phone number|now an admin|"
    r"no longer an admin|security code|deleted this group|Tap to learn more|"
    r"turned on|turned off|You blocked|You unblocked)")

# WhatsApp attributes notices to the group's own name (and some to "You"), so those
# names appear as senders. Find them structurally — a "sender" whose messages are
# almost entirely notices — rather than hard-coding any chat's group name. A real
# person's messages never look like that, even if they happen to write "added".
looks_system = df["text"].str.contains(SYSTEM_PAT, na=False)
sys_ratio    = looks_system.groupby(df["sender"]).mean()
sender_n     = df["sender"].value_counts()
notice_senders = {s for s in sys_ratio.index
                  if s != "" and sys_ratio[s] > 0.75
                  and (sender_n[s] < 400 or sys_ratio[s] > 0.95)}

df["is_system"] = df["sender"].isin(notice_senders) | (df["sender"] == "")
print("notice senders:", ", ".join(sorted(notice_senders)) or "none")

system_df = df[df["is_system"]].copy()
msgs = df[~df["is_system"]].copy()

# tidy sender names ("~ Name" is a push name, not a contact; drop stray no-break spaces)
msgs["sender"] = (msgs["sender"].str.replace(" ", " ", regex=False)
                                .str.lstrip("~").str.strip())

BOTS = {"Meta AI"}
members_all = [s for s in msgs["sender"].unique() if s not in BOTS]

# ---- message typing -------------------------------------------------------
MEDIA_MARKERS = {
    "image":   "image omitted",   "video":  "video omitted",
    "audio":   "audio omitted",   "sticker": "sticker omitted",
    "GIF":     "GIF omitted",     "document": "document omitted",
    "contact": "Contact card omitted",
}
def classify(t):
    for kind, marker in MEDIA_MARKERS.items():
        if marker in t:
            return kind
    if "This message was deleted" in t or "You deleted this message" in t:
        return "deleted"
    return "text"

msgs["type"]    = msgs["text"].map(classify)
msgs["is_media"] = msgs["type"].isin(MEDIA_MARKERS)
msgs["edited"]  = msgs["text"].str.contains("<This message was edited>", regex=False)

# clean body text: strip placeholders/edit tags so word stats measure real writing
def clean_body(t):
    t = re.sub(r"<This message was edited>", "", t)
    for marker in list(MEDIA_MARKERS.values()) + ["This message was deleted",
                                                  "You deleted this message"]:
        t = t.replace(marker, "")
    return t.strip()

msgs["body"] = msgs["text"].map(clean_body)

# ---- time features --------------------------------------------------------
msgs["date_only"] = msgs["datetime"].dt.date
msgs["year"]      = msgs["datetime"].dt.year
msgs["month"]     = msgs["datetime"].dt.to_period("M")
msgs["hour"]      = msgs["datetime"].dt.hour
msgs["weekday"]   = msgs["datetime"].dt.day_name()
msgs["n_chars"]   = msgs["body"].str.len()
msgs["n_words"]   = msgs["body"].str.split().map(len)

WEEK_ORDER = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]

# members ordered by volume — this order fixes every colour in the notebook
MEMBERS = (msgs[msgs["sender"].isin(members_all)]["sender"]
           .value_counts().index.tolist())
COLOR = {m: (CATEGORICAL[i] if i < len(CATEGORICAL) else MUTED)
         for i, m in enumerate(MEMBERS)}
COLOR["Meta AI"] = MUTED
PANEL = MEMBERS[:len(CATEGORICAL)]   # per-member panels & stacked series

member_msgs = msgs[msgs["sender"].isin(MEMBERS)].copy()

print(f"member messages : {len(member_msgs):,}")
print(f"system notices  : {len(system_df):,}")
print(f"Meta AI replies : {(msgs['sender'] == 'Meta AI').sum():,}")
print(f"members ({len(MEMBERS)})    : {', '.join(MEMBERS)}")
if len(MEMBERS) > len(PANEL):
    print(f"note            : per-member panels show the top {len(PANEL)} by volume")
print(f"period          : {msgs['datetime'].min():%d %b %Y} → {msgs['datetime'].max():%d %b %Y}")
member_msgs[["datetime","sender","type","n_words","body"]].head()
''')

md("""
### 3.1 Dataset at a glance
""")

code(r'''
span_days = (msgs["datetime"].max() - msgs["datetime"].min()).days
active_days = member_msgs["date_only"].nunique()

overview = pd.Series({
    "Group created":             f"{df['datetime'].min():%d %b %Y}",
    "Messages (members)":        f"{len(member_msgs):,}",
    "Members":                   len(MEMBERS),
    "First message":             f"{msgs['datetime'].min():%d %b %Y, %I:%M %p}",
    "Last message":              f"{msgs['datetime'].max():%d %b %Y, %I:%M %p}",
    "Calendar span":             f"{span_days:,} days ({span_days/365.25:.1f} years)",
    "Days with ≥1 message":      f"{active_days:,} ({active_days/span_days:.0%} of days)",
    "Messages per active day":   f"{len(member_msgs)/active_days:.1f}",
    "Words written":             f"{member_msgs['n_words'].sum():,}",
    "Characters written":        f"{member_msgs['n_chars'].sum():,}",
    "Media shared":              f"{member_msgs['is_media'].sum():,}",
    "Deleted messages":          f"{(member_msgs['type']=='deleted').sum():,}",
    "Edited messages":           f"{member_msgs['edited'].sum():,}",
    "System notices":            f"{len(system_df):,}",
}, name="value").to_frame()
overview.index.name = "metric"
overview
''')

# ---------------------------------------------------------------- 4. participation
md("""
## 4. Participation — messages per member

The headline question: **how much does each member talk?** Message count first,
then the same volume seen as a share of the group.
""")

code(r'''
counts = member_msgs["sender"].value_counts().reindex(MEMBERS)
share  = counts / counts.sum() * 100

participation = pd.DataFrame({"messages": counts, "share_%": share.round(2)})
participation.loc["TOTAL"] = [counts.sum(), 100.0]
participation["messages"] = participation["messages"].astype(int)
participation
''')

code(r'''
order = counts.sort_values()                       # smallest at the bottom of an hbar
fig, ax = plt.subplots(figsize=(9, 4.2))
bars = ax.barh(order.index, order.values,
               color=[COLOR[m] for m in order.index], height=0.62)
hbar_labels(ax, bars, order.values)
ax.xaxis.set_major_formatter(thousands)
style(ax, xgrid=True,
      title=f"{counts.index[0]} writes {share.iloc[0]/10:.0f} in every 10 messages",
      sub=f"Messages sent per member · {len(member_msgs):,} messages, "
          f"{msgs['datetime'].min():%b %Y} – {msgs['datetime'].max():%b %Y}",
      xlabel="messages")
for s in ("left",): ax.spines[s].set_color(AXIS)
plt.tight_layout(); plt.show()
''')

code(r'''
# Share of all messages — the same numbers, normalised
fig, ax = plt.subplots(figsize=(9, 1.9))
left = 0
for m in MEMBERS:
    w = share[m]
    ax.barh([0], [w], left=left, color=COLOR[m], height=0.5,
            edgecolor=SURFACE, linewidth=2)          # 2px surface gap between fills
    if w > 4:
        ax.text(left + w/2, 0, f"{m}\n{w:.1f}%", ha="center", va="center",
                fontsize=9, color="white", fontweight="600")
    left += w
ax.set_xlim(0, 100); ax.set_ylim(-0.5, 0.5)
ax.set_yticks([]); ax.set_xticks([0,25,50,75,100])
ax.set_xticklabels(["0%","25%","50%","75%","100%"])
for s in ax.spines.values(): s.set_visible(False)
style(ax, title="Share of the conversation",
      sub="Every message ever sent in the group, split by author")
plt.tight_layout(); plt.show()

print("Concentration — top talker: {:.1f}% · top two: {:.1f}% of all messages"
      .format(share.iloc[0], share.iloc[:2].sum()))
''')

# ---------------------------------------------------------------- 5. volume
md("""
## 5. Volume beyond message count

Message count rewards people who send many short messages. Words and characters
tell a second story: who *writes* the most versus who *pings* the most.
""")

code(r'''
vol = member_msgs.groupby("sender").agg(
    messages=("body", "size"),
    words=("n_words", "sum"),
    characters=("n_chars", "sum"),
    avg_words=("n_words", "mean"),
    median_chars=("n_chars", "median"),
    longest_msg_chars=("n_chars", "max"),
).reindex(MEMBERS).round(2)
vol["words_share_%"] = (vol["words"] / vol["words"].sum() * 100).round(1)
vol["msg_share_%"]   = (vol["messages"] / vol["messages"].sum() * 100).round(1)
vol
''')

code(r'''
fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.2))

specs = [("words",     "Words written",        "{:,.0f}"),
         ("avg_words", "Average words / message", "{:.1f}"),
         ("median_chars", "Median message length (chars)", "{:.0f}")]
for ax, (col, title, fmt) in zip(axes, specs):
    s = vol[col].sort_values()
    bars = ax.barh(s.index, s.values, color=[COLOR[m] for m in s.index], height=0.6)
    hbar_labels(ax, bars, s.values, fmt=fmt)
    ax.xaxis.set_major_formatter(thousands)
    style(ax, xgrid=True, title=title)
    ax.tick_params(labelsize=9)
fig.suptitle("Talkers vs. writers", x=0.005, ha="left", fontsize=13,
             fontweight="600", color=INK, y=1.02)
plt.tight_layout(); plt.show()
''')

code(r'''
# Distribution of message length per member (log scale — lengths are heavy-tailed)
fig, ax = plt.subplots(figsize=(9.5, 4.4))
data = [member_msgs.loc[member_msgs["sender"] == m, "n_chars"]
        .replace(0, np.nan).dropna().values for m in MEMBERS]
bp = ax.boxplot(data, vert=False, labels=MEMBERS, widths=0.55, showfliers=False,
                patch_artist=True, medianprops=dict(color=SURFACE, linewidth=2))
for patch, m in zip(bp["boxes"], MEMBERS):
    patch.set_facecolor(COLOR[m]); patch.set_edgecolor(COLOR[m])
for w in bp["whiskers"] + bp["caps"]: w.set_color(AXIS)
ax.set_xscale("log")
ax.set_xlim(0.9, 400)
ax.set_xticks([1, 5, 10, 25, 50, 100, 250])
ax.get_xaxis().set_major_formatter(mpl.ticker.ScalarFormatter())
style(ax, xgrid=True, title="How long is a typical message?",
      sub="Character count per message, log scale · box = middle 50%, line = median",
      xlabel="characters (log)")
plt.tight_layout(); plt.show()
''')

# ---------------------------------------------------------------- 6. types
md("""
## 6. What kind of messages does each member send?

Voice notes, images and stickers are a big share of this chat — the composition
differs sharply from person to person.
""")

code(r'''
type_counts = (member_msgs.groupby(["sender", "type"]).size()
               .unstack(fill_value=0).reindex(MEMBERS))
ranked = type_counts.sum().sort_values(ascending=False).index.tolist()
KEEP = ranked[:6]                      # 6 named types + one "other" bucket
tail = [t for t in ranked if t not in KEEP]
if tail:
    type_counts["other"] = type_counts[tail].sum(axis=1)
    type_counts = type_counts.drop(columns=tail)
type_order = KEEP + (["other"] if tail else [])
type_counts = type_counts[type_order]
print("folded into 'other':", ", ".join(tail) if tail else "nothing")
type_pct = (type_counts.T / type_counts.sum(axis=1)).T * 100
type_counts.assign(TOTAL=type_counts.sum(axis=1))
''')

code(r'''
fig, ax = plt.subplots(figsize=(10, 4.6))
left = np.zeros(len(MEMBERS)); ypos = np.arange(len(MEMBERS))[::-1]
for i, t in enumerate(type_order):
    vals = type_pct[t].values
    fill = MUTED if t == "other" else CATEGORICAL[i]
    ax.barh(ypos, vals, left=left, height=0.6, color=fill,
            edgecolor=SURFACE, linewidth=2, label=t)
    for y, v, l in zip(ypos, vals, left):
        if v >= 6:
            ax.text(l + v/2, y, f"{v:.0f}%", ha="center", va="center",
                    fontsize=9, color="white", fontweight="600")
    left += vals
ax.set_yticks(ypos); ax.set_yticklabels(MEMBERS)
ax.set_xlim(0, 100); ax.set_xticks([0,25,50,75,100])
ax.set_xticklabels(["0%","25%","50%","75%","100%"])
ax.legend(ncol=len(type_order), loc="upper left", bbox_to_anchor=(0, -0.12),
          fontsize=9, labelcolor=INK_2)
style(ax, xgrid=True, title="Message mix per member",
      sub="Share of each member's messages by type")
plt.tight_layout(); plt.show()
''')

code(r'''
media = member_msgs[member_msgs["is_media"]]
mt = media.groupby(["sender", "type"]).size().unstack(fill_value=0).reindex(MEMBERS)
mt = mt[mt.sum().sort_values(ascending=False).index]

fig, ax = plt.subplots(figsize=(11, 4.4))
x = np.arange(len(mt.columns)); w = 0.8 / len(PANEL)
for i, m in enumerate(PANEL):
    bars = ax.bar(x + i*w - 0.4 + w/2, mt.loc[m].values, width=w*0.86,
                  color=COLOR[m], label=m)
ax.set_xticks(x); ax.set_xticklabels(mt.columns)
ax.yaxis.set_major_formatter(thousands)
ax.legend(ncol=min(len(PANEL), 5), fontsize=9, labelcolor=INK_2, loc="upper right")
style(ax, ygrid=True, title="Who shares which media",
      sub=f"{len(media):,} media messages · counts per member",
      ylabel="messages")
plt.tight_layout(); plt.show()
mt.assign(TOTAL=mt.sum(axis=1))
''')

# ---------------------------------------------------------------- 7. time
md("""
## 7. Activity over time

The group was created in December 2019 but only came alive later — the yearly and
monthly views show when, and whose voice dominated in each era.
""")

code(r'''
per_year = (member_msgs.groupby(["year", "sender"]).size()
            .unstack(fill_value=0).reindex(columns=MEMBERS))

fig, ax = plt.subplots(figsize=(11, 4.8))
bottom = np.zeros(len(per_year))
for m in PANEL:
    ax.bar(per_year.index.astype(str), per_year[m].values, bottom=bottom,
           color=COLOR[m], label=m, width=0.66,
           edgecolor=SURFACE, linewidth=2)
    bottom += per_year[m].values
for xi, tot in enumerate(bottom):
    ax.text(xi, tot + bottom.max()*0.015, f"{int(tot):,}", ha="center",
            va="bottom", fontsize=9.5, color=INK_2)
ax.set_ylim(0, bottom.max()*1.12)
ax.yaxis.set_major_formatter(thousands)
ax.legend(ncol=min(len(PANEL), 6), fontsize=9, labelcolor=INK_2, loc="upper left")
style(ax, ygrid=True, title="Messages per year, stacked by member",
      sub="2026 is a partial year (up to the export date)", ylabel="messages")
plt.tight_layout(); plt.show()
per_year.assign(TOTAL=per_year.sum(axis=1))
''')

code(r'''
per_month = (member_msgs.groupby(["month", "sender"]).size()
             .unstack(fill_value=0).reindex(columns=MEMBERS))
full_idx = pd.period_range(member_msgs["month"].min(), member_msgs["month"].max(), freq="M")
per_month = per_month.reindex(full_idx, fill_value=0)
total_month = per_month.sum(axis=1)

fig, ax = plt.subplots(figsize=(13, 4.4))
ax.fill_between(range(len(total_month)), total_month.values, color="#cde2fb")
ax.plot(range(len(total_month)), total_month.values, color="#2a78d6", linewidth=2)
peak = int(total_month.values.argmax())
ax.scatter([peak], [total_month.iloc[peak]], s=42, color="#2a78d6",
           zorder=3, edgecolor=SURFACE, linewidth=2)
ax.annotate(f"{total_month.index[peak]} · {total_month.iloc[peak]:,} msgs",
            (peak, total_month.iloc[peak]), textcoords="offset points",
            xytext=(-8, 10), ha="right", fontsize=9.5, color=INK_2)
ticks = [i for i, p in enumerate(total_month.index) if p.month == 1]
ax.set_xticks(ticks); ax.set_xticklabels([str(total_month.index[i].year) for i in ticks])
ax.yaxis.set_major_formatter(thousands)
style(ax, ygrid=True, title="Monthly message volume",
      sub=f"Group total per calendar month · median {total_month.median():,.0f} messages/month",
      ylabel="messages")
plt.tight_layout(); plt.show()
''')

code(r'''
# Monthly participation share — who owned each era (100% stacked)
pct_month = (per_month.T / per_month.sum(axis=1).replace(0, np.nan)).T * 100
pct_month = pct_month.fillna(0)

fig, ax = plt.subplots(figsize=(13, 4.6))
ax.stackplot(range(len(pct_month)), [pct_month[m].values for m in PANEL],
             colors=[COLOR[m] for m in PANEL], labels=PANEL)
ax.set_xlim(0, len(pct_month)-1); ax.set_ylim(0, 100)
ticks = [i for i, p in enumerate(pct_month.index) if p.month in (1, 7)]
ax.set_xticks(ticks)
ax.set_xticklabels([pct_month.index[i].strftime("%b %y") for i in ticks],
                   rotation=0, fontsize=8.5)
ax.set_yticks([0,25,50,75,100]); ax.set_yticklabels(["0%","25%","50%","75%","100%"])
ax.legend(ncol=min(len(PANEL), 6), fontsize=9, labelcolor=INK_2,
          loc="upper left", bbox_to_anchor=(0, -0.10))
style(ax, title="Who dominated the group, month by month",
      sub="Each member's share of that month's messages")
plt.tight_layout(); plt.show()
''')

code(r'''
# Per-member monthly trajectory — small multiples, shared scale
fig, axes = plt.subplots(len(PANEL), 1, figsize=(12.5, 1.55*len(PANEL)),
                         sharex=True, sharey=True, squeeze=False)
axes = axes.ravel()
xs = range(len(per_month))
ymax = per_month[PANEL].max().max()
for ax, m in zip(axes, PANEL):
    ax.fill_between(xs, per_month[m].values, color=COLOR[m], alpha=0.22)
    ax.plot(xs, per_month[m].values, color=COLOR[m], linewidth=1.8)
    ax.text(0.004, 0.80, m, transform=ax.transAxes, fontsize=10,
            fontweight="600", color=INK)
    ax.text(0.004, 0.52, f"{per_month[m].sum():,} total", transform=ax.transAxes,
            fontsize=8.5, color=MUTED)
    ax.set_ylim(0, ymax*1.05); ax.set_axisbelow(True)
    ax.grid(axis="y", color=GRID, linewidth=0.7)
    ax.spines["left"].set_visible(False); ax.tick_params(length=0)
ticks = [i for i, p in enumerate(per_month.index) if p.month == 1]
axes[-1].set_xticks(ticks)
axes[-1].set_xticklabels([str(per_month.index[i].year) for i in ticks])
axes[0].set_title("Monthly messages per member — same scale for all",
                  pad=14)
plt.tight_layout(); plt.show()
''')

code(r'''
# Daily volume with a 30-day rolling average
daily = member_msgs.groupby("date_only").size()
daily.index = pd.to_datetime(daily.index)
daily = daily.reindex(pd.date_range(daily.index.min(), daily.index.max()), fill_value=0)
roll = daily.rolling(30, center=True).mean()

fig, ax = plt.subplots(figsize=(13, 4.2))
ax.plot(daily.index, daily.values, color="#cde2fb", linewidth=0.8)
ax.plot(roll.index, roll.values, color="#2a78d6", linewidth=2, label="30-day average")
top = daily.nlargest(1)
ax.annotate(f"busiest day · {top.index[0]:%d %b %Y} ({top.iloc[0]:,} msgs)",
            (top.index[0], top.iloc[0]), textcoords="offset points",
            xytext=(-10, -4), ha="right", fontsize=9.5, color=INK_2)
ax.legend(fontsize=9, labelcolor=INK_2, loc="upper left")
style(ax, ygrid=True, title="Daily messages, 2019 – today",
      sub="Pale line: raw daily count · bold line: 30-day rolling average",
      ylabel="messages / day")
plt.tight_layout(); plt.show()
''')

# ---------------------------------------------------------------- 8. rhythm
md("""
## 8. The rhythm of the day and week
""")

code(r'''
by_hour = member_msgs["hour"].value_counts().reindex(range(24), fill_value=0)
by_wday = member_msgs["weekday"].value_counts().reindex(WEEK_ORDER)

fig, axes = plt.subplots(1, 2, figsize=(13.5, 4.2),
                         gridspec_kw={"width_ratios": [1.5, 1]})

ax = axes[0]
bars = ax.bar(by_hour.index, by_hour.values, color="#2a78d6", width=0.72)
peak_h = int(by_hour.idxmax())
bars[peak_h].set_color("#eb6834")
ax.text(peak_h, by_hour.max()*1.02, f"{by_hour.max():,}", ha="center",
        va="bottom", fontsize=9.5, color=INK_2)
ax.set_xticks(range(0, 24, 2))
ax.set_xticklabels([f"{h:02d}" for h in range(0, 24, 2)])
ax.yaxis.set_major_formatter(thousands)
style(ax, ygrid=True, title="Messages by hour of day",
      sub=f"Peak hour: {peak_h:02d}:00–{peak_h:02d}:59", xlabel="hour", ylabel="messages")

ax = axes[1]
bars = ax.bar(range(7), by_wday.values, color="#2a78d6", width=0.68)
bars[int(np.argmax(by_wday.values))].set_color("#eb6834")
vbar_labels(ax, bars, by_wday.values)
ax.set_xticks(range(7)); ax.set_xticklabels([d[:3] for d in WEEK_ORDER])
ax.yaxis.set_major_formatter(thousands)
style(ax, ygrid=True, title="Messages by weekday",
      sub=f"Busiest: {by_wday.idxmax()}", ylabel="messages")
plt.tight_layout(); plt.show()
''')

code(r'''
heat = (member_msgs.groupby(["weekday", "hour"]).size()
        .unstack(fill_value=0).reindex(WEEK_ORDER).reindex(columns=range(24), fill_value=0))

fig, ax = plt.subplots(figsize=(13, 3.9))
im = ax.imshow(heat.values, cmap=SEQ_BLUE, aspect="auto")
ax.set_xticks(range(24)); ax.set_xticklabels([f"{h:02d}" for h in range(24)], fontsize=8.5)
ax.set_yticks(range(7)); ax.set_yticklabels(WEEK_ORDER, fontsize=9.5)
for s in ax.spines.values(): s.set_visible(False)
ax.tick_params(length=0)
cb = fig.colorbar(im, ax=ax, pad=0.012, shrink=0.85)
cb.outline.set_visible(False); cb.ax.tick_params(color=MUTED, labelcolor=MUTED, length=0)
cb.set_label("messages", color=INK_2, fontsize=9)
r, c = np.unravel_index(heat.values.argmax(), heat.values.shape)
ax.text(c, r, f"{heat.values[r, c]:,}", ha="center", va="center",
        fontsize=8.5, color="white", fontweight="600")
style(ax, title="When is the group alive?",
      sub=f"Weekday × hour · hottest cell: {WEEK_ORDER[r]} {c:02d}:00 "
          f"({heat.values[r, c]:,} messages)", xlabel="hour of day")
plt.tight_layout(); plt.show()
''')

code(r'''
ym = (member_msgs.groupby(["year", member_msgs["datetime"].dt.month]).size()
      .unstack(fill_value=0).reindex(columns=range(1, 13), fill_value=0))
MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

fig, ax = plt.subplots(figsize=(11, 3.6))
im = ax.imshow(ym.values, cmap=SEQ_BLUE, aspect="auto")
ax.set_xticks(range(12)); ax.set_xticklabels(MONTHS, fontsize=9)
ax.set_yticks(range(len(ym))); ax.set_yticklabels(ym.index, fontsize=9.5)
for i in range(ym.shape[0]):
    for j in range(ym.shape[1]):
        v = ym.values[i, j]
        if v:
            ax.text(j, i, f"{v:,}", ha="center", va="center", fontsize=7.5,
                    color="white" if v > ym.values.max()*0.5 else INK_2)
for s in ax.spines.values(): s.set_visible(False)
ax.tick_params(length=0)
style(ax, title="Month × year activity grid", sub="Message count per calendar month")
plt.tight_layout(); plt.show()
''')

# ---------------------------------------------------------------- 9. per member rhythm
md("""
## 9. Each member's daily rhythm

Normalised per member (each row sums to 100%) so a quiet member's shape is still
readable next to the group's loudest voice.
""")

code(r'''
mh = (member_msgs.groupby(["sender", "hour"]).size().unstack(fill_value=0)
      .reindex(MEMBERS).reindex(columns=range(24), fill_value=0))
mh_pct = (mh.T / mh.sum(axis=1)).T * 100

fig, axes = plt.subplots(len(PANEL), 1, figsize=(12, 1.35*len(PANEL)),
                         sharex=True, sharey=True, squeeze=False)
axes = axes.ravel()
for ax, m in zip(axes, PANEL):
    ax.bar(range(24), mh_pct.loc[m].values, color=COLOR[m], width=0.72)
    ax.text(0.004, 0.72, m, transform=ax.transAxes, fontsize=10,
            fontweight="600", color=INK)
    pk = int(mh_pct.loc[m].idxmax())
    ax.text(0.999, 0.72, f"peak {pk:02d}:00", transform=ax.transAxes,
            fontsize=8.5, color=MUTED, ha="right")
    ax.set_axisbelow(True); ax.grid(axis="y", color=GRID, linewidth=0.7)
    ax.spines["left"].set_visible(False); ax.tick_params(length=0)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}%"))
axes[-1].set_xticks(range(0, 24, 2))
axes[-1].set_xticklabels([f"{h:02d}" for h in range(0, 24, 2)])
axes[0].set_title("Daily rhythm per member — share of that member's own messages", pad=14)
plt.tight_layout(); plt.show()
''')

code(r'''
# Night-owl index: share of a member's messages sent between 00:00 and 05:59
night = member_msgs.assign(night=member_msgs["hour"].between(0, 5))
owl = (night.groupby("sender")["night"].mean() * 100).reindex(MEMBERS).sort_values()
early = (member_msgs.assign(am=member_msgs["hour"].between(5, 9))
         .groupby("sender")["am"].mean() * 100).reindex(owl.index)

fig, axes = plt.subplots(1, 2, figsize=(12.5, 3.6))
for ax, s, t, sub in [
        (axes[0], owl,   "Night owls",   "share of own messages sent 00:00–05:59"),
        (axes[1], early, "Early birds",  "share of own messages sent 05:00–09:59")]:
    bars = ax.barh(s.index, s.values, color=[COLOR[m] for m in s.index], height=0.6)
    hbar_labels(ax, bars, s.values, fmt="{:.1f}%")
    style(ax, xgrid=True, title=t, sub=sub)
    ax.tick_params(labelsize=9)
plt.tight_layout(); plt.show()
''')

# ---------------------------------------------------------------- 10. interaction
md("""
## 10. Interaction — who talks *to* whom

WhatsApp exports carry no reply threading, so interaction is inferred from
sequence: a message is treated as a **response** to the previous message when a
different member sent it. That gives three views — a who-follows-whom matrix,
who *starts* conversations (first message after a ≥3-hour lull), and how fast
each member replies.
""")

code(r'''
seq = member_msgs.sort_values("datetime").reset_index(drop=True)
seq["prev_sender"] = seq["sender"].shift()
seq["gap_min"] = seq["datetime"].diff().dt.total_seconds() / 60

trans = (seq.dropna(subset=["prev_sender"])
         .query("sender != prev_sender")
         .groupby(["prev_sender", "sender"]).size()
         .unstack(fill_value=0).reindex(index=PANEL, columns=PANEL, fill_value=0))
trans_pct = (trans.T / trans.sum(axis=1).replace(0, np.nan)).T * 100

fig, ax = plt.subplots(figsize=(7.6, 5.4))
im = ax.imshow(trans_pct.values, cmap=SEQ_BLUE, aspect="auto", vmin=0)
ax.set_xticks(range(len(PANEL))); ax.set_xticklabels(PANEL, rotation=25, ha="right", fontsize=9)
ax.set_yticks(range(len(PANEL))); ax.set_yticklabels(PANEL, fontsize=9)
for i in range(len(PANEL)):
    for j in range(len(PANEL)):
        v = trans_pct.values[i, j]
        if not np.isnan(v):
            ax.text(j, i, "—" if i == j else f"{v:.0f}%", ha="center", va="center",
                    fontsize=9,
                    color="white" if v > np.nanmax(trans_pct.values)*0.5 else INK_2)
for s in ax.spines.values(): s.set_visible(False)
ax.tick_params(length=0)
style(ax, title="Who answers whom",
      sub="Row = speaker, column = who spoke next (row sums to 100%)",
      xlabel="next speaker", ylabel="speaker")
plt.tight_layout(); plt.show()
trans
''')

code(r'''
GAP_HOURS = 3
seq["is_starter"] = seq["gap_min"].isna() | (seq["gap_min"] > GAP_HOURS*60)
starters = seq[seq["is_starter"]]["sender"].value_counts().reindex(MEMBERS).fillna(0)
starter_rate = (starters / counts * 100).reindex(MEMBERS)

fig, axes = plt.subplots(1, 2, figsize=(12.5, 3.8))
s = starters.sort_values()
bars = axes[0].barh(s.index, s.values, color=[COLOR[m] for m in s.index], height=0.6)
hbar_labels(axes[0], bars, s.values)
style(axes[0], xgrid=True, title="Conversation starters",
      sub=f"Messages that broke a silence of {GAP_HOURS}h+ · {int(starters.sum()):,} conversations")

s2 = starter_rate.reindex(s.index)
bars = axes[1].barh(s2.index, s2.values, color=[COLOR[m] for m in s2.index], height=0.6)
hbar_labels(axes[1], bars, s2.values, fmt="{:.1f}%")
style(axes[1], xgrid=True, title="…as a share of the member's own messages",
      sub="High = starts threads; low = mostly joins in")
for ax in axes: ax.tick_params(labelsize=9)
plt.tight_layout(); plt.show()
''')

code(r'''
# Response time: gap to the previous message when it came from someone else,
# capped at 6 hours so overnight silences don't masquerade as slow replies.
resp = seq[(seq["prev_sender"].notna()) & (seq["sender"] != seq["prev_sender"]) &
           (seq["gap_min"] <= 360)]
rt = resp.groupby("sender")["gap_min"].agg(median="median", mean="mean",
                                           replies="size").reindex(MEMBERS)
rt["under_1_min_%"] = (resp.assign(f=resp["gap_min"] <= 1)
                       .groupby("sender")["f"].mean() * 100).reindex(MEMBERS)

fig, axes = plt.subplots(1, 2, figsize=(12.5, 3.8))
s = rt["median"].sort_values(ascending=False)
bars = axes[0].barh(s.index, s.values, color=[COLOR[m] for m in s.index], height=0.6)
hbar_labels(axes[0], bars, s.values, fmt="{:.1f} min")
style(axes[0], xgrid=True, title="Median response time",
      sub="Time to reply to someone else, replies within 6h only · lower = faster")

s2 = rt["under_1_min_%"].reindex(s.index)
bars = axes[1].barh(s2.index, s2.values, color=[COLOR[m] for m in s2.index], height=0.6)
hbar_labels(axes[1], bars, s2.values, fmt="{:.0f}%")
style(axes[1], xgrid=True, title="Instant replies",
      sub="Share of that member's replies sent within 60 seconds")
for ax in axes: ax.tick_params(labelsize=9)
plt.tight_layout(); plt.show()
rt.round(2)
''')

code(r'''
# Bursts: how often does a member send several messages in a row?
runs = (seq["sender"] != seq["sender"].shift()).cumsum().rename("turn_id")
burst = seq.groupby(runs).agg(sender=("sender", "first"), length=("sender", "size"))
burst_stats = burst.groupby("sender").agg(
    bursts=("length", "size"), avg_burst=("length", "mean"),
    longest_burst=("length", "max")).reindex(MEMBERS).round(2)

fig, ax = plt.subplots(figsize=(9, 3.6))
s = burst_stats["avg_burst"].sort_values()
bars = ax.barh(s.index, s.values, color=[COLOR[m] for m in s.index], height=0.6)
hbar_labels(ax, bars, s.values, fmt="{:.2f}")
style(ax, xgrid=True, title="Messages per uninterrupted turn",
      sub="Average run length before someone else speaks · higher = types in bursts")
plt.tight_layout(); plt.show()
burst_stats
''')

# ---------------------------------------------------------------- 11. emoji
md("""
## 11. Emoji

Emoji are shown in tables rather than on chart axes — matplotlib cannot render
colour emoji glyphs, but the notebook's HTML tables can.
""")

code(r'''
try:
    import emoji as emoji_lib
    def extract_emojis(t):
        return [d["emoji"] for d in emoji_lib.emoji_list(t)]
except ImportError:                     # regex fallback if the package is absent
    EMOJI_RE = re.compile("[" "\U0001F300-\U0001FAFF" "☀-➿"
                          "\U0001F1E6-\U0001F1FF" "←-⇿" "⬀-⯿" "]")
    def extract_emojis(t):
        return EMOJI_RE.findall(t)

member_msgs["emojis"] = member_msgs["body"].map(extract_emojis)
member_msgs["n_emoji"] = member_msgs["emojis"].map(len)

emoji_stats = member_msgs.groupby("sender").agg(
    total_emoji=("n_emoji", "sum"),
    msgs_with_emoji=("n_emoji", lambda s: (s > 0).sum()),
).reindex(MEMBERS)
emoji_stats["emoji_per_100_msgs"] = (emoji_stats["total_emoji"] / counts * 100).round(1)
emoji_stats["%_msgs_with_emoji"]  = (emoji_stats["msgs_with_emoji"] / counts * 100).round(1)
emoji_stats["distinct_emoji"] = (member_msgs.groupby("sender")["emojis"]
                                 .apply(lambda s: len({e for lst in s for e in lst}))
                                 .reindex(MEMBERS))
emoji_stats["top_emoji"] = (member_msgs.groupby("sender")["emojis"]
    .apply(lambda s: " ".join(e for e, _ in collections.Counter(
        [e for lst in s for e in lst]).most_common(6))).reindex(MEMBERS))
emoji_stats
''')

code(r'''
fig, axes = plt.subplots(1, 2, figsize=(12.5, 3.8))
s = emoji_stats["emoji_per_100_msgs"].sort_values()
bars = axes[0].barh(s.index, s.values, color=[COLOR[m] for m in s.index], height=0.6)
hbar_labels(axes[0], bars, s.values, fmt="{:.1f}")
style(axes[0], xgrid=True, title="Emoji intensity",
      sub="Emoji used per 100 messages")

s2 = emoji_stats["%_msgs_with_emoji"].reindex(s.index)
bars = axes[1].barh(s2.index, s2.values, color=[COLOR[m] for m in s2.index], height=0.6)
hbar_labels(axes[1], bars, s2.values, fmt="{:.1f}%")
style(axes[1], xgrid=True, title="Messages containing at least one emoji",
      sub="Share of the member's own messages")
for ax in axes: ax.tick_params(labelsize=9)
plt.tight_layout(); plt.show()
''')

code(r'''
all_emoji = collections.Counter(e for lst in member_msgs["emojis"] for e in lst)
top_emoji = pd.DataFrame(all_emoji.most_common(20), columns=["emoji", "count"])
top_emoji["share_%"] = (top_emoji["count"] / sum(all_emoji.values()) * 100).round(2)
top_emoji["bar"] = (top_emoji["count"] / top_emoji["count"].max() * 40).round().astype(int).map(lambda n: "█"*n)
print(f"{sum(all_emoji.values()):,} emoji used · {len(all_emoji):,} distinct")
top_emoji
''')

code(r'''
# Who uses each of the group's favourite emoji
top10 = [e for e, _ in all_emoji.most_common(10)]
rows = {}
for m in MEMBERS:
    c = collections.Counter(e for lst in member_msgs.loc[member_msgs["sender"]==m, "emojis"]
                            for e in lst)
    rows[m] = [c.get(e, 0) for e in top10]
emoji_by_member = pd.DataFrame(rows, index=top10).T
emoji_by_member["TOTAL"] = emoji_by_member.sum(axis=1)
emoji_by_member
''')

# ---------------------------------------------------------------- 12. words
md("""
## 12. Words & language

The chat is mostly **Manglish** (Malayalam typed in Latin script) with some
Malayalam script and English. Word statistics below use the Latin-script tokens;
a separate count tracks how much native Malayalam script each member types.
""")

code(r'''
STOP = set("""a about after all also am an and any are as at be because been but by can cant cause come
could did do does doing done dont for from get go going got had has have he her here him his how i
id if ilk ill im in into is it its ive just know like ll me more most my no not now of oh ok okay on
one only or our out over re said say see she should so some such than that the their them then there
these they this those to too us ve very was we well were what when where which while who why will
with would yes you your youre u ur its im na nn""".split())

# URL debris would otherwise dominate every word chart
URL_RE = re.compile(r"https?://\S+|www\.\S+")
STOP |= set("""https http www com net org youtu youtube instagram facebook igsh
mibextid fbclid utm amp app whatsapp link https www""".split())

TOKEN = re.compile(r"[A-Za-z']{2,}")
text_msgs = member_msgs[member_msgs["type"] == "text"]

def tokens(s):
    s = URL_RE.sub(" ", s)                      # links out, words only
    return [w for w in TOKEN.findall(s.lower()) if w not in STOP and len(w) > 2]

word_counter = collections.Counter()
per_member_words = {m: collections.Counter() for m in MEMBERS}
for sender, body in zip(text_msgs["sender"], text_msgs["body"]):
    ws = tokens(body)
    word_counter.update(ws); per_member_words[sender].update(ws)

top_words = pd.DataFrame(word_counter.most_common(25), columns=["word", "count"])

fig, ax = plt.subplots(figsize=(9, 6.4))
tw = top_words.iloc[:20][::-1]
bars = ax.barh(tw["word"], tw["count"], color="#2a78d6", height=0.66)
hbar_labels(ax, bars, tw["count"].values)
ax.xaxis.set_major_formatter(thousands)
style(ax, xgrid=True, title="Top 20 words in the group",
      sub=f"Latin-script tokens · URLs and stop-words removed · "
          f"{sum(word_counter.values()):,} words counted")
plt.tight_layout(); plt.show()
''')

code(r'''
# Each member's signature words: frequent for them, rare for everyone else
sig = {}
totals = {m: sum(per_member_words[m].values()) for m in MEMBERS}
grand = sum(totals.values())
for m in MEMBERS:
    scores = []
    for w, c in per_member_words[m].items():
        if c < 15: continue
        others = sum(per_member_words[o][w] for o in MEMBERS if o != m)
        rate_m = c / max(totals[m], 1)
        rate_o = (others + 1) / max(grand - totals[m], 1)
        scores.append((w, c, rate_m / rate_o))
    sig[m] = ", ".join(w for w, _, _ in sorted(scores, key=lambda x: -x[2])[:8])

pd.DataFrame({
    "top words":  {m: ", ".join(w for w, _ in per_member_words[m].most_common(8)) for m in MEMBERS},
    "signature words (distinctively theirs)": sig,
    "words counted": {m: f"{totals[m]:,}" for m in MEMBERS},
}).reindex(MEMBERS)
''')

code(r'''
MALAYALAM = re.compile(r"[ഀ-ൿ]")
member_msgs["has_ml"] = member_msgs["body"].str.contains(MALAYALAM)
member_msgs["ml_chars"] = member_msgs["body"].map(lambda t: len(MALAYALAM.findall(t)))

script = pd.DataFrame({
    "msgs_with_malayalam_script": member_msgs.groupby("sender")["has_ml"].sum(),
    "malayalam_chars": member_msgs.groupby("sender")["ml_chars"].sum(),
}).reindex(MEMBERS)
script["%_of_own_msgs"] = (script["msgs_with_malayalam_script"] / counts * 100).round(2)

fig, ax = plt.subplots(figsize=(9, 3.4))
s = script["%_of_own_msgs"].sort_values()
bars = ax.barh(s.index, s.values, color=[COLOR[m] for m in s.index], height=0.6)
hbar_labels(ax, bars, s.values, fmt="{:.2f}%")
style(ax, xgrid=True, title="Who types in Malayalam script?",
      sub="Share of the member's messages containing Malayalam characters (the rest is Manglish/English)")
plt.tight_layout(); plt.show()
script
''')

code(r'''
# Word cloud (Latin-script tokens; Malayalam script is handled in the table above)
try:
    from wordcloud import WordCloud
    wc = WordCloud(width=1600, height=760, background_color=SURFACE,
                   colormap="Blues", max_words=180, prefer_horizontal=0.92,
                   relative_scaling=0.45, min_font_size=10
                   ).generate_from_frequencies(word_counter)
    fig, ax = plt.subplots(figsize=(13, 6.2))
    ax.imshow(wc, interpolation="bilinear"); ax.axis("off")
    ax.set_title("The group's vocabulary", pad=12)
    plt.tight_layout(); plt.show()
except ImportError:
    print("wordcloud not installed — `pip install wordcloud` to render this chart")
''')

code(r'''
# One word cloud per member
try:
    from wordcloud import WordCloud
    n = len(MEMBERS); ncol = 2; nrow = math.ceil(n/ncol)
    fig, axes = plt.subplots(nrow, ncol, figsize=(13, 3.1*nrow))
    for ax, m in zip(axes.ravel(), MEMBERS):
        wc = WordCloud(width=900, height=460, background_color=SURFACE,
                       color_func=lambda *a, **k: COLOR[m],
                       max_words=90, prefer_horizontal=0.95, min_font_size=9
                       ).generate_from_frequencies(per_member_words[m])
        ax.imshow(wc, interpolation="bilinear"); ax.axis("off")
        ax.set_title(m, fontsize=11, color=INK)
    for ax in axes.ravel()[n:]: ax.axis("off")
    plt.tight_layout(); plt.show()
except ImportError:
    print("wordcloud not installed — skipping")
''')

# ---------------------------------------------------------------- 13. links etc
md("""
## 13. Links, deletions and edits
""")

code(r'''
URL = re.compile(r"https?://\S+|www\.\S+")
member_msgs["links"] = member_msgs["body"].map(URL.findall)
member_msgs["n_links"] = member_msgs["links"].map(len)

link_stats = pd.DataFrame({
    "links_shared": member_msgs.groupby("sender")["n_links"].sum(),
    "msgs_with_link": member_msgs.groupby("sender")["n_links"].apply(lambda s: (s > 0).sum()),
    "deleted": member_msgs[member_msgs["type"] == "deleted"].groupby("sender").size(),
    "edited": member_msgs.groupby("sender")["edited"].sum(),
}).reindex(MEMBERS).fillna(0).astype(int)
link_stats["links_per_100_msgs"] = (link_stats["links_shared"] / counts * 100).round(1)

fig, axes = plt.subplots(1, 3, figsize=(13.5, 3.6))
for ax, col, title, fmt in [
        (axes[0], "links_shared", "Links shared", "{:,.0f}"),
        (axes[1], "deleted", "Messages deleted", "{:,.0f}"),
        (axes[2], "edited", "Messages edited", "{:,.0f}")]:
    s = link_stats[col].sort_values()
    bars = ax.barh(s.index, s.values, color=[COLOR[m] for m in s.index], height=0.6)
    hbar_labels(ax, bars, s.values, fmt=fmt)
    style(ax, xgrid=True, title=title); ax.tick_params(labelsize=9)
plt.tight_layout(); plt.show()
link_stats
''')

code(r'''
def domain(u):
    m = re.match(r"https?://(?:www\.)?([^/\s]+)", u) or re.match(r"www\.([^/\s]+)", u)
    return m.group(1).lower() if m else None

domains = collections.Counter(
    d for lst in member_msgs["links"] for u in lst if (d := domain(u)))
top_dom = pd.Series(dict(domains.most_common(15))).sort_values()

fig, ax = plt.subplots(figsize=(9.5, 5))
bars = ax.barh(top_dom.index, top_dom.values, color="#2a78d6", height=0.66)
hbar_labels(ax, bars, top_dom.values)
style(ax, xgrid=True, title="Where the links point",
      sub=f"{sum(domains.values()):,} links · {len(domains):,} distinct domains")
plt.tight_layout(); plt.show()
''')

# ---------------------------------------------------------------- 14. records
md("""
## 14. Records, streaks and milestones
""")

code(r'''
busiest = member_msgs.groupby("date_only").size().nlargest(10)
busiest_df = pd.DataFrame({
    "date": [f"{pd.Timestamp(d):%a, %d %b %Y}" for d in busiest.index],
    "messages": busiest.values,
    "top author": [member_msgs[member_msgs["date_only"] == d]["sender"].value_counts().idxmax()
                   for d in busiest.index],
})

fig, ax = plt.subplots(figsize=(10, 4.6))
b = busiest_df[::-1]
bars = ax.barh(b["date"], b["messages"],
               color=[COLOR[a] for a in b["top author"]], height=0.64)
hbar_labels(ax, bars, b["messages"].values)
handles = [mpl.patches.Patch(color=COLOR[m], label=m)
           for m in MEMBERS if m in set(b["top author"])]
ax.legend(handles=handles, fontsize=9, labelcolor=INK_2, loc="lower right")
style(ax, xgrid=True, title="The 10 busiest days ever",
      sub="Bar colour = who wrote the most that day")
plt.tight_layout(); plt.show()
busiest_df
''')

code(r'''
active_dates = pd.Index(sorted(member_msgs["date_only"].unique()))
ad = pd.to_datetime(pd.Series(active_dates))
gaps = ad.diff().dt.days
brk = (gaps != 1).cumsum()
streaks = ad.groupby(brk).agg(["size", "min", "max"])
best = streaks.sort_values("size", ascending=False).head(5)
best.columns = ["days", "from", "to"]

silence = pd.DataFrame({
    "silence_days": gaps.values - 1, "resumed": ad.values,
}).dropna().sort_values("silence_days", ascending=False).head(5)
silence["from"] = silence["resumed"] - pd.to_timedelta(silence["silence_days"], unit="D")
silence = silence[["silence_days", "from", "resumed"]].astype({"silence_days": int})

print("Longest daily-activity streaks")
display(best.reset_index(drop=True))
print("\nLongest silences")
display(silence.reset_index(drop=True))
''')

code(r'''
# Member lifespans — first and last message, and their most active month
life = member_msgs.groupby("sender").agg(
    first=("datetime", "min"), last=("datetime", "max"), messages=("body", "size")
).reindex(MEMBERS)
life["active_days"] = member_msgs.groupby("sender")["date_only"].nunique().reindex(MEMBERS)
life["busiest_month"] = (member_msgs.groupby(["sender", "month"]).size()
                         .groupby(level=0).idxmax().map(lambda t: str(t[1])).reindex(MEMBERS))
life["msgs_per_active_day"] = (life["messages"] / life["active_days"]).round(1)

fig, ax = plt.subplots(figsize=(11.5, 3.4))
ypos = np.arange(len(MEMBERS))[::-1]
for y, m in zip(ypos, MEMBERS):
    ax.plot([life.loc[m, "first"], life.loc[m, "last"]], [y, y],
            color=COLOR[m], linewidth=9, alpha=0.85, solid_capstyle="round")
    ax.text(life.loc[m, "last"], y + 0.32, f"  {life.loc[m,'messages']:,} msgs",
            va="center", fontsize=9, color=INK_2)
ax.set_yticks(ypos); ax.set_yticklabels(MEMBERS)
ax.tick_params(length=0)
style(ax, xgrid=True, title="Each member's span in the group",
      sub="From first to last message sent")
plt.tight_layout(); plt.show()
life
''')

code(r'''
# Per-member consistency: how many of the group's active days each one showed up on
consistency = (member_msgs.groupby("sender")["date_only"].nunique()
               / member_msgs["date_only"].nunique() * 100).reindex(MEMBERS).sort_values()

fig, ax = plt.subplots(figsize=(9, 3.4))
bars = ax.barh(consistency.index, consistency.values,
               color=[COLOR[m] for m in consistency.index], height=0.6)
hbar_labels(ax, bars, consistency.values, fmt="{:.1f}%")
style(ax, xgrid=True, title="Consistency — presence on the group's active days",
      sub=f"Of the {member_msgs['date_only'].nunique():,} days the group spoke at all")
plt.tight_layout(); plt.show()
''')

code(r'''
# System notices: the group's own history (renames, icon changes, pins)
renames = system_df[system_df["text"].str.contains("changed the group name", na=False)].copy()
renames["name"] = renames["text"].str.extract(r"changed the group name to [“\"](.+)[”\"]")
print(f"{len(renames)} group renames · {len(system_df)} system notices in total")
renames[["datetime", "name"]].tail(15).reset_index(drop=True)
''')

# ---------------------------------------------------------------- 15. summary
md("""
## 15. Master summary table
""")

code(r'''
summary = pd.DataFrame({
    "messages": counts,
    "share_%": share.round(1),
    "words": vol["words"],
    "avg_words/msg": vol["avg_words"].round(1),
    "media": member_msgs[member_msgs["is_media"]].groupby("sender").size().reindex(MEMBERS).fillna(0).astype(int),
    "emoji/100msg": emoji_stats["emoji_per_100_msgs"],
    "links": link_stats["links_shared"],
    "deleted": link_stats["deleted"],
    "active_days": life["active_days"],
    "msgs/active_day": life["msgs_per_active_day"],
    "starters": starters.astype(int),
    "median_reply_min": rt["median"].round(1),
    "avg_burst": burst_stats["avg_burst"],
    "night_%": owl.reindex(MEMBERS).round(1),
    "peak_hour": mh_pct.idxmax(axis=1).map(lambda h: f"{h:02d}:00"),
}).reindex(MEMBERS)
summary
''')

code(r'''
# Normalised profile: each metric scaled 0–100 across members, so shapes compare
prof_cols = ["messages", "words", "avg_words/msg", "media", "emoji/100msg",
             "links", "msgs/active_day", "starters", "avg_burst", "night_%"]
prof = summary[prof_cols].astype(float)
prof_n = (prof - prof.min()) / (prof.max() - prof.min()) * 100

fig, ax = plt.subplots(figsize=(11.5, 4.2))
im = ax.imshow(prof_n.values, cmap=SEQ_BLUE, aspect="auto", vmin=0, vmax=100)
ax.set_xticks(range(len(prof_cols))); ax.set_xticklabels(prof_cols, rotation=28, ha="right", fontsize=9)
ax.set_yticks(range(len(MEMBERS))); ax.set_yticklabels(MEMBERS, fontsize=9.5)
for i in range(prof_n.shape[0]):
    for j in range(prof_n.shape[1]):
        raw = prof.values[i, j]
        ax.text(j, i, f"{raw:,.0f}" if raw >= 100 else f"{raw:,.1f}",
                ha="center", va="center", fontsize=8,
                color="white" if prof_n.values[i, j] > 45 else INK_2)
for s in ax.spines.values(): s.set_visible(False)
ax.tick_params(length=0)
style(ax, title="Member profile matrix",
      sub="Colour = rank within the column (0–100 scaled); printed value = the real number")
plt.tight_layout(); plt.show()
''')

code(r'''
lines = []
lines.append(f"GROUP: {msgs['datetime'].min():%b %Y} – {msgs['datetime'].max():%b %Y} · "
             f"{len(member_msgs):,} messages from {len(MEMBERS)} members")
lines.append(f"Most active member  : {counts.index[0]} — {counts.iloc[0]:,} messages ({share.iloc[0]:.1f}%)")
lines.append(f"Quietest member     : {counts.index[-1]} — {counts.iloc[-1]:,} messages ({share.iloc[-1]:.1f}%)")
lines.append(f"Top two together    : {share.iloc[:2].sum():.1f}% of everything said")
lines.append(f"Wordiest per message: {vol['avg_words'].idxmax()} ({vol['avg_words'].max():.1f} words/msg)")
lines.append(f"Biggest media sharer: {summary['media'].idxmax()} ({summary['media'].max():,} media messages)")
lines.append(f"Most emoji-happy    : {emoji_stats['emoji_per_100_msgs'].idxmax()} "
             f"({emoji_stats['emoji_per_100_msgs'].max():.1f} emoji per 100 messages)")
lines.append(f"Fastest replier     : {rt['median'].idxmin()} (median {rt['median'].min():.1f} min)")
lines.append(f"Top conversation starter: {starters.idxmax()} ({int(starters.max()):,} threads opened)")
lines.append(f"Biggest night owl   : {owl.idxmax()} ({owl.max():.1f}% of messages after midnight)")
lines.append(f"Busiest day         : {pd.Timestamp(busiest.index[0]):%d %b %Y} — {busiest.iloc[0]:,} messages")
lines.append(f"Busiest month       : {total_month.idxmax()} — {total_month.max():,} messages")
lines.append(f"Busiest hour        : {int(by_hour.idxmax()):02d}:00 · busiest weekday: {by_wday.idxmax()}")
lines.append(f"Longest active streak: {int(best.iloc[0]['days'])} days "
             f"({best.iloc[0]['from']:%d %b %Y} → {best.iloc[0]['to']:%d %b %Y})")
lines.append(f"Longest silence     : {int(silence.iloc[0]['silence_days'])} days")
print("\n".join(lines))
''')

md("""
### 15.1 Export the headline numbers

Written to `report_data.json` so the HTML report and any other downstream view
read exactly the numbers computed here — one source of truth.
""")

code(r'''
import json

report_data = {
    "current_name": (renames["name"].dropna().iloc[-1] if len(renames)
                     else (sorted(notice_senders)[0] if notice_senders else "This chat")),
    "created": f"{df['datetime'].min():%d %b %Y}",
    "first_message": f"{msgs['datetime'].min():%d %b %Y}",
    "last_message":  f"{msgs['datetime'].max():%d %b %Y}",
    "total_messages": int(len(member_msgs)),
    "n_members": len(MEMBERS),
    "span_days": int(span_days),
    "active_days": int(active_days),
    "msgs_per_active_day": round(len(member_msgs)/active_days, 1),
    "words": int(member_msgs["n_words"].sum()),
    "media": int(member_msgs["is_media"].sum()),
    "emoji": int(sum(all_emoji.values())),
    "links": int(link_stats["links_shared"].sum()),
    "renames": int(len(renames)),
    "busiest_day": f"{pd.Timestamp(busiest.index[0]):%d %b %Y}",
    "busiest_day_msgs": int(busiest.iloc[0]),
    "busiest_month": str(total_month.idxmax()),
    "busiest_month_msgs": int(total_month.max()),
    "peak_hour": int(by_hour.idxmax()),
    "busiest_weekday": str(by_wday.idxmax()),
    "longest_streak_days": int(best.iloc[0]["days"]),
    "longest_silence_days": int(silence.iloc[0]["silence_days"]),
    "highlights": lines,
    "members": [{
        "name": m,
        "color": COLOR[m],
        "messages": int(counts[m]),
        "share": round(float(share[m]), 1),
        "words": int(vol.loc[m, "words"]),
        "avg_words": round(float(vol.loc[m, "avg_words"]), 1),
        "media": int(summary.loc[m, "media"]),
        "emoji_per_100": float(emoji_stats.loc[m, "emoji_per_100_msgs"]),
        "links": int(link_stats.loc[m, "links_shared"]),
        "starters": int(starters[m]),
        "median_reply_min": round(float(rt.loc[m, "median"]), 1),
        "active_days": int(life.loc[m, "active_days"]),
        "peak_hour": int(mh_pct.loc[m].idxmax()),
        "night_pct": round(float(owl[m]), 1),
        "top_emoji": emoji_stats.loc[m, "top_emoji"],
        "top_words": ", ".join(w for w, _ in per_member_words[m].most_common(6)),
    } for m in MEMBERS],
}
with open("report_data.json", "w") as f:
    json.dump(report_data, f, indent=2, ensure_ascii=False)
print("wrote report_data.json ·", len(report_data), "keys")
''')

md("""
---

### Method notes & caveats

- **Participation = messages sent.** Reactions are not in WhatsApp exports, so a
  member who mostly reacts looks quieter than they are.
- **Media are placeholders.** An export made without media stores `image omitted`
  etc.; counts are exact, but the content is not analysable.
- **Replies are inferred from sequence,** not from WhatsApp's quote metadata
  (absent in exports). Response times are capped at 6 hours so overnight gaps
  don't distort the medians.
- **Timestamps are local to the exporting phone**, and the export uses
  `dd/mm/yyyy`.
- **`Meta AI` and system notices** (renames, pins, icon changes) are excluded from
  member statistics and reported separately.
- Deleted messages survive as a placeholder line — they are counted as a message
  type, but contribute no words.
""")

nb["cells"] = cells
nb["metadata"] = {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python", "version": "3.9"},
}
out = sys.argv[1] if len(sys.argv) > 1 else "whatsapp_chat_analysis.ipynb"
nbf.write(nb, out)
print("wrote", out, "with", len(cells), "cells")
