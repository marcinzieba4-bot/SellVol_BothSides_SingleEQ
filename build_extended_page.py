#!/usr/bin/env python3
"""Regenerate InsideSPX report content for the Feb 2015 - Feb 2026 window."""
import json, re, sys

SP = "/tmp/claude-0/-home-user-SellVol-BothSides-SingleEQ/f5a4bfe8-ea76-52ba-bd0e-c6ceb8a77cba/scratchpad"
D = json.load(open(f"{SP}/extended_report_data.json"))
S, arch, capin = D["stats"], D["arch"], D["capin"]

def rep1(s, old, new, label):
    if s.count(old) != 1:
        print(f"FAIL [{label}]: {s.count(old)}"); sys.exit(1)
    print("ok  ", label)
    return s.replace(old, new)

idx = open(f"{SP}/tb_cur/static/strategies/index.html").read()
start = idx.find("{", idx.find("_CONTENT = "))
dec = json.JSONDecoder()
obj, consumed = dec.raw_decode(idx[start:])
c = obj["insidespx"]

# hero tiles (1x)
c = rep1(c, ">+103.9%</div>", ">+135.1%</div>", "hero total")
c = rep1(c, ">+7.5%</div>\n          <div class=\"text-vr-faint text-xs uppercase tracking-wide\">Ann. Return (1&times;)</div>",
            ">+8.0%</div>\n          <div class=\"text-vr-faint text-xs uppercase tracking-wide\">Ann. Return (1&times;)</div>", "hero ann")
c = rep1(c, ">1.65</div>\n          <div class=\"text-vr-faint text-xs uppercase tracking-wide\">Sharpe (1&times;, 0% RF)</div>",
            ">1.80</div>\n          <div class=\"text-vr-faint text-xs uppercase tracking-wide\">Sharpe (1&times;, 0% RF)</div>", "hero sharpe")

# window texts
c = rep1(c, "Backtest Feb 2015 – Dec 2024 (119 months). Premiums before Sep 2020 scaled by realised VIX ratio to avoid vol-environment bias.",
            "Backtest Feb 2015 – Feb 2026 (133 months). Premiums before Sep 2020 scaled by realised VIX ratio to avoid vol-environment bias.", "perf intro")
c = rep1(c, "Feb 2015 – Dec 2024 (119 months)</td>", "Feb 2015 – Feb 2026 (133 months)</td>", "params window")
c = rep1(c, "Showing 119 of 119 months.", "Showing 133 of 133 months.", "showing")

# summary tbody rebuild
def row(label, v1, v4, vr, cls="text-vr-text", bold=False):
    w = "font-bold " if bold else ""
    tds = "".join(
        f'\n              <td class="px-5 py-3 text-right font-mono {w}{cl}">{v}</td>'
        for v, cl in ((v1, cls if not isinstance(cls, tuple) else cls[0]),
                      (v4, cls if not isinstance(cls, tuple) else cls[1]),
                      (vr, cls if not isinstance(cls, tuple) else cls[2])))
    return (f'\n            <tr class="border-b border-vr-border">'
            f'\n              <td class="px-5 py-3 text-vr-muted">{label}</td>{tds}\n            </tr>')

def pct(v, sign=True):
    s = "+" if (sign and v >= 0) else ("&#8722;" if v < 0 else "")
    return f"{s}{abs(v):.1f}%"

G, R, T = "text-vr-green", "text-vr-red", "text-vr-text"
body = ""
body += row("Total Return (compound, 133 mo.)", pct(S['x1']['total']), pct(S['x4']['total']), pct(S['rec']['total']), G, bold=True)
body += row("Ann. Return", pct(S['x1']['ann']), pct(S['x4']['ann']), pct(S['rec']['ann']), G, bold=True)
body += row("Ann. Volatility", f"{S['x1']['vol']:.1f}%", f"{S['x4']['vol']:.1f}%", f"{S['rec']['vol']:.1f}%")
body += row("Sharpe (0% RF)", f"{S['x1']['sharpe']:.2f}", f"{S['x4']['sharpe']:.2f}", f"{S['rec']['sharpe']:.2f}")
body += row("Sortino (0% RF)", f"{S['x1']['sortino']:.2f}", f"{S['x4']['sortino']:.2f}", f"{S['rec']['sortino']:.2f}")
body += row("Calmar Ratio", f"{S['x1']['calmar']:.2f}", f"{S['x4']['calmar']:.2f}", f"{S['rec']['calmar']:.2f}")
body += row("Max Drawdown", pct(S['x1']['maxdd'], sign=False), pct(S['x4']['maxdd'], sign=False), pct(S['rec']['maxdd'], sign=False), R)
body += row("Win Rate (months)", f"{S['x1']['win']:.1f}%", f"{S['x4']['win']:.1f}%", f"{S['rec']['win']:.1f}%")
body += row("Best Month", pct(S['x1']['best']), pct(S['x4']['best']), pct(S['rec']['best']), G)
body += row("Worst Month", pct(S['x1']['worst'], sign=False), pct(S['x4']['worst'], sign=False), pct(S['rec']['worst'], sign=False), R)
body += row("VaR 95%", pct(S['x1']['var95'], sign=False), pct(S['x4']['var95'], sign=False), pct(S['rec']['var95'], sign=False))
body += row("CVaR 95%", pct(S['x1']['cvar'], sign=False), pct(S['x4']['cvar'], sign=False), pct(S['rec']['cvar'], sign=False))
body += row('Capital in Options <span class="text-vr-faint text-xs">(avg premium / portfolio)</span>',
            f"{capin['x1']:.1f}%", f"{capin['x4']:.1f}%", f"{capin['rec']:.1f}% avg (peak {capin['recmax']:.0f}%)", "text-vr-gold")
body += row('Free Cash <span class="text-vr-faint text-xs">(earning MMR)</span>',
            f"~{100-capin['x1']:.1f}%", f"~{100-capin['x4']:.1f}%", f"~{100-capin['rec']:.1f}% avg")
body = body.replace('border-b border-vr-border">\n              <td class="px-5 py-3 text-vr-muted">Free Cash',
                    '">\n              <td class="px-5 py-3 text-vr-muted">Free Cash')  # last row: no bottom border

m = re.search(r'(<thead>.*?2&times; Recovery</th>\s*</tr>\s*</thead>)\s*<tbody>.*?</tbody>', c, re.S)
if not m: print("FAIL summary tbody locate"); sys.exit(1)
c = c[:m.start()] + m.group(1) + "\n          <tbody>" + body + "\n          </tbody>" + c[m.end():]
print("ok   summary tbody rebuilt")

# archive tbody rebuild (133 rows, newest first)
def arow(a):
    wl = "W" if a["r1"] >= 0 else "L"
    def fmt(v):
        color = "#c9a961" if v >= 0 else "#ff6666"
        sign = "+" if v >= 0 else ""
        return (f'<td style="padding:10px 14px;text-align:right;font-family:monospace;'
                f'font-weight:700;color:{color};">{sign}{v:.2f}%</td>')
    return (f'<tr class="arch-row {wl}" style="border-bottom:1px solid #2a2a3e;">'
            f'<td style="padding:10px 14px;color:#e0e0e0;font-weight:600;">{a["ym"]}</td>'
            + fmt(a["r1"]) + fmt(a["r4"]) + fmt(a["rr"]) +
            f'<td style="padding:10px 14px;text-align:right;font-family:monospace;color:#888;font-size:11px;">{a["ci"]:.2f}%</td>'
            f'<td style="padding:10px 14px;text-align:right;color:#888;">{a["bets"]}</td>'
            f'<td style="padding:10px 14px;text-align:right;color:#888;">{a["wins"]}/{a["bets"]}</td>'
            f'<td style="padding:10px 14px;color:#c9a961;font-family:monospace;font-size:11px;">{a["top"]} (+{a["toppnl"]:.2f}%)</td>'
            '</tr>')
rows_html = "\n".join(arow(a) for a in reversed(arch))
m = re.search(r'(<tbody id="archive-body">).*?(</tbody>)', c, re.S)
if not m:
    m = re.search(r'(<tbody id="archive-body">).*?(</table>)', c, re.S)
    if not m: print("FAIL archive tbody locate"); sys.exit(1)
    c = c[:m.start()] + m.group(1) + rows_html + "\n      " + m.group(2) + c[m.end():]
else:
    c = c[:m.start()] + m.group(1) + rows_html + m.group(2) + c[m.end():]
print("ok   archive tbody rebuilt (133 rows)")

# footnote: refresh Sharpe-vs-FFR + extension note
c = rep1(c, "measured as excess over FFR instead, Sharpe is 1.25 (1&times;) and 1.28 (4&times;).",
            "measured as excess over FFR instead, Sharpe is 1.34 (1&times;) and 1.38 (4&times;).", "footnote sharpe")
c = rep1(c, "Its free cash also earns FFR.</p>",
            "Its free cash also earns FFR. Months from Jan 2025 extend the original backtest walk-forward: "
            "prices from monthly adjusted closes; premiums from the live options dataset where available "
            "(through Feb 2026), otherwise the ticker's or its sector proxy's average recorded premium; "
            "FI and MMC lack price data and are excluded in the extension window.</p>", "footnote ext")

obj["insidespx"] = c
idx_new = idx[:start] + json.dumps(obj, ensure_ascii=False) + idx[start + consumed:]

# library card
idx_new = rep1(idx_new, '>+7.5%</div><div class="text-vr-faint text-xs">Ann. Return (1&times;)</div>',
                        '>+8.0%</div><div class="text-vr-faint text-xs">Ann. Return (1&times;)</div>', "card ann1")
idx_new = rep1(idx_new, '>1.65</div><div class="text-vr-faint text-xs">Sharpe (1&times;)</div>',
                        '>1.80</div><div class="text-vr-faint text-xs">Sharpe (1&times;)</div>', "card sharpe1")
idx_new = rep1(idx_new, '>+24.7%</div><div class="text-vr-faint text-xs">Ann. Return (4&times;)</div>',
                        '>+26.5%</div><div class="text-vr-faint text-xs">Ann. Return (4&times;)</div>', "card ann4")
idx_new = rep1(idx_new, '>1.38</div><div class="text-vr-faint text-xs">Sharpe (4&times;)</div>',
                        '>1.50</div><div class="text-vr-faint text-xs">Sharpe (4&times;)</div>', "card sharpe4")
open(f"{SP}/strategies_index_v4.html", "w").write(idx_new)
o2, _ = dec.raw_decode(idx_new[idx_new.find("{", idx_new.find("_CONTENT = ")):])
assert o2["insidespx"] == c
print("index rebuilt:", len(idx_new))

# standalone
det = open(f"{SP}/tb_cur/static/strategies/insidespx-momentum/index.html").read()
head = det[:det.find('<main class="relative z-10 min-h-screen">')]
foot = det[det.find("</main>") + len("</main>"):]
wrapper = ('<div class="pt-28 pb-24 max-w-7xl mx-auto px-6">\n\n  <!-- Breadcrumb -->\n'
  '  <div class="flex items-center gap-2 mb-8">\n'
  '    <a class="text-vr-faint text-xs hover:text-vr-gold transition-colors" href="/strategies/">Strategies</a>\n'
  '    <span class="text-vr-faint text-xs">/</span>\n'
  '    <span class="text-vr-gold text-xs font-semibold tracking-widest uppercase">InsideSPX Momentum</span>\n'
  '  </div>\n')
assert c.startswith("<div>")
content_rel = (wrapper + c[len("<div>"):]).replace(
    "https://d7g7nkeytae81.cloudfront.net/strategies/insidespx-momentum/insidespx_chart_all.png",
    "/strategies/insidespx-momentum/insidespx_chart_all.png")
standalone = head + '<main class="relative z-10 min-h-screen">\n' + content_rel + "\n</main>" + foot
open(f"{SP}/insidespx_standalone_v4.html", "w").write(standalone)
print("standalone rebuilt:", len(standalone), "| divs balanced:",
      content_rel.count("<div") == content_rel.count("</div>"))
