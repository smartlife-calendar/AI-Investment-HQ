#!/usr/bin/env python3
"""
Update window._smartData in index.html using data/accumulation.json from GitHub.
Reads accumulation.json, replaces the window._smartData assignment in index.html.
"""
import urllib.request, json, base64, sys, os

GH_TOKEN = os.environ.get("GH_TOKEN", "")
REPO = "smartlife-calendar/AI-Investment-HQ"
BRANCH = "gh-pages"
HEADERS = {"Authorization": f"token {GH_TOKEN}", "Accept": "application/vnd.github.v3+json"}


def gh_get(path):
    """Get file content and SHA from GitHub."""
    url = f"https://api.github.com/repos/{REPO}/contents/{path}?ref={BRANCH}"
    req = urllib.request.Request(url, headers=HEADERS)
    d = json.loads(urllib.request.urlopen(req, timeout=15).read())
    content = base64.b64decode(d["content"]).decode("utf-8")
    return content, d["sha"]


def gh_put(path, content, sha, msg):
    """Update file on GitHub."""
    payload = json.dumps({
        "message": msg,
        "content": base64.b64encode(content.encode()).decode(),
        "sha": sha,
        "branch": BRANCH,
    }).encode()
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/contents/{path}",
        data=payload,
        headers={**HEADERS, "Content-Type": "application/json"},
        method="PUT",
    )
    r = json.loads(urllib.request.urlopen(req, timeout=30).read())
    return r.get("commit", {}).get("sha", "?")[:7]


FOOTER_HTML = '''
<footer style="text-align:center;font-size:12px;color:#94a3b8;padding:24px 20px 40px;max-width:960px;margin:0 auto">
    <p>© 2026 StockIQ (stockiq.tw)｜本平台分析報告不構成投資建議｜投資人應自行評估風險</p>
    <p style="margin-top:4px">資料來源：Yahoo Finance, SEC EDGAR, 公開新聞。資料可能有延遲，僅供參考。</p>
    <p style="margin-top:4px">客服：smartlifecalendar@gmail.com<br>
    <a href="https://buymeacoffee.com/SmartLifeCalendar" target="_blank" style="color:#f59e0b;text-decoration:none;font-weight:700;font-size:14px">☕ 請我喝杯咖啡 — 支持免費開發</a></p>
</footer>
'''

BMC_POPUP_HTML = '''<div id="bmcPopup" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);z-index:9999;justify-content:center;align-items:center">
    <div style="background:white;border-radius:16px;padding:28px;max-width:420px;width:90%;margin:20px;text-align:center;box-shadow:0 20px 60px rgba(0,0,0,0.3);position:relative">
        <button onclick="closeBmcPopup()" style="position:absolute;top:8px;right:12px;background:none;border:none;font-size:20px;color:#94a3b8;cursor:pointer">✕</button>
        <div style="font-size:40px;margin-bottom:12px">☕</div>
        <div style="font-size:18px;font-weight:800;color:#1e293b;margin-bottom:8px">覺得 StockIQ 有用嗎？</div>
        <div style="font-size:13px;color:#64748b;line-height:1.6;margin-bottom:16px">
            我們每天免費分析 296 支美股 + 1,960 支台股<br>
            如果幫到你，請我們喝杯咖啡吧 ❤️
        </div>
        <a href="https://buymeacoffee.com/SmartLifeCalendar" target="_blank" onclick="closeBmcPopup()" style="display:inline-block;background:linear-gradient(135deg,#f59e0b,#d97706);color:white;font-weight:800;font-size:15px;padding:12px 32px;border-radius:12px;text-decoration:none;box-shadow:0 4px 15px rgba(245,158,11,0.4);transition:transform 0.2s" onmouseover="this.style.transform=\'scale(1.05)\'" onmouseout="this.style.transform=\'\'">
            ☕ 請我喝杯咖啡
        </a>
        <div style="margin-top:12px">
            <button onclick="closeBmcPopup()" style="background:none;border:none;color:#94a3b8;font-size:12px;cursor:pointer">下次再說</button>
        </div>
    </div>
</div>
<script>
function closeBmcPopup(){
    document.getElementById('bmcPopup').style.display='none';
    sessionStorage.setItem('bmcDismissed','1');
}
(function(){
    if(sessionStorage.getItem('bmcDismissed')) return;
    setTimeout(function(){
        if(!sessionStorage.getItem('bmcDismissed')){
            document.getElementById('bmcPopup').style.display='flex';
        }
    }, 30000);
})();
</script>
'''

GTBOX_HTML = '''
<div id="gtBox" style="position:fixed;bottom:16px;right:16px;z-index:9999">
<div id="langMenu" style="display:none;background:white;border-radius:12px;padding:8px;margin-bottom:8px;box-shadow:0 4px 20px rgba(0,0,0,0.15);min-width:140px">
<div style="font-size:10px;color:#94a3b8;padding:4px 8px;font-weight:700">Select Language</div>
<a onclick="gtGo(\'en\')" style="display:block;padding:6px 12px;font-size:13px;color:#1e293b;cursor:pointer;border-radius:6px;text-decoration:none" onmouseover="this.style.background=\'#f1f5f9\'" onmouseout="this.style.background=\'\'">🇺🇸 English</a>
<a onclick="gtGo(\'ja\')" style="display:block;padding:6px 12px;font-size:13px;color:#1e293b;cursor:pointer;border-radius:6px;text-decoration:none" onmouseover="this.style.background=\'#f1f5f9\'" onmouseout="this.style.background=\'\'">🇯🇵 日本語</a>
<a onclick="gtGo(\'ko\')" style="display:block;padding:6px 12px;font-size:13px;color:#1e293b;cursor:pointer;border-radius:6px;text-decoration:none" onmouseover="this.style.background=\'#f1f5f9\'" onmouseout="this.style.background=\'\'">🇰🇷 한국어</a>
<a onclick="gtGo(\'th\')" style="display:block;padding:6px 12px;font-size:13px;color:#1e293b;cursor:pointer;border-radius:6px;text-decoration:none" onmouseover="this.style.background=\'#f1f5f9\'" onmouseout="this.style.background=\'\'">🇹🇭 ไทย</a>
<a onclick="gtGo(\'vi\')" style="display:block;padding:6px 12px;font-size:13px;color:#1e293b;cursor:pointer;border-radius:6px;text-decoration:none" onmouseover="this.style.background=\'#f1f5f9\'" onmouseout="this.style.background=\'\'">🇻🇳 Tiếng Việt</a>
<a onclick="gtGo(\'id\')" style="display:block;padding:6px 12px;font-size:13px;color:#1e293b;cursor:pointer;border-radius:6px;text-decoration:none" onmouseover="this.style.background=\'#f1f5f9\'" onmouseout="this.style.background=\'\'">🇮🇩 Bahasa</a>
</div>
<button onclick="var m=document.getElementById(\'langMenu\');m.style.display=m.style.display===\'none\'?\'block\':\'none\'" style="background:#1e40af;color:white;border:none;padding:10px 16px;border-radius:24px;font-size:13px;font-weight:700;cursor:pointer;box-shadow:0 2px 10px rgba(0,0,0,0.2)">🌐 Translate</button>
</div>
'''


def ensure_tail_elements(html):
    """Ensure footer, BMC popup, translate button, and closing tags are present."""
    changed = False

    # 1. Footer
    if '<footer' not in html:
        # Insert before bmcPopup or before </body> or at end
        if 'id="bmcPopup"' in html:
            idx = html.find('<div id="bmcPopup"')
            html = html[:idx] + FOOTER_HTML + '\n' + html[idx:]
        elif '</body>' in html:
            idx = html.find('</body>')
            html = html[:idx] + FOOTER_HTML + '\n' + html[idx:]
        else:
            html = html.rstrip() + '\n' + FOOTER_HTML
        changed = True
        print("  🔧 Footer restored")

    # 2. BMC popup
    if 'id="bmcPopup"' not in html:
        if '</body>' in html:
            idx = html.find('</body>')
            html = html[:idx] + BMC_POPUP_HTML + '\n' + html[idx:]
        else:
            html = html.rstrip() + '\n' + BMC_POPUP_HTML
        changed = True
        print("  🔧 BMC popup restored")

    # 3. Translate button
    if 'id="gtBox"' not in html:
        if '</body>' in html:
            idx = html.find('</body>')
            html = html[:idx] + GTBOX_HTML + '\n' + html[idx:]
        else:
            html = html.rstrip() + '\n' + GTBOX_HTML
        changed = True
        print("  🔧 Translate button restored")

    # 4. Closing tags
    if '</body>' not in html:
        html = html.rstrip() + '\n</body>\n</html>'
        changed = True
        print("  🔧 Closing tags restored")

    if not changed:
        print("  ✅ All tail elements intact")

    return html


def main():
    print("🔄 Updating window._smartData in index.html...")

    # 1. Read accumulation.json
    print("  📥 Reading data/accumulation.json...")
    acc_content, _ = gh_get("data/accumulation.json")
    acc_data = json.loads(acc_content)
    print(f"  ✅ {len(acc_data.get('stocks', []))} bull, {len(acc_data.get('bearish', []))} bear signals")

    # 2. Read index.html
    print("  📥 Reading index.html...")
    html, sha = gh_get("index.html")
    original_size = len(html)

    # 3. Find and replace window._smartData = {...};
    marker = "window._smartData ="
    start = html.find(marker)
    if start == -1:
        print("  ❌ window._smartData not found in index.html!")
        sys.exit(1)

    # Find the semicolon that ends the assignment
    # Need to find matching closing brace first
    brace_start = html.find("{", start)
    depth = 0
    i = brace_start
    while i < len(html):
        if html[i] == "{":
            depth += 1
        elif html[i] == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    # i is now at closing }, find the ;
    end = html.find(";", i) + 1

    if end == 0:
        print("  ❌ Could not find end of window._smartData assignment!")
        sys.exit(1)

    old_data = html[start:end]
    print(f"  Old _smartData: {len(old_data)} bytes")

    # Build new assignment with compact JSON
    new_json = json.dumps(acc_data, ensure_ascii=False, separators=(",", ":"))
    new_assignment = f"window._smartData = {new_json};"
    print(f"  New _smartData: {len(new_assignment)} bytes")

    # Replace
    new_html = html[:start] + new_assignment + html[end:]
    new_size = len(new_html)
    size_diff = abs(new_size - original_size)
    print(f"  Size: {original_size} → {new_size} (diff: {size_diff})")

    # Safety check
    if size_diff > 80000:
        print(f"  ❌ ABORT: size diff {size_diff} > 80000 bytes!")
        sys.exit(1)

    # ── Ensure essential tail elements survive ──
    new_html = ensure_tail_elements(new_html)

    # 4. Push
    commit = gh_put("index.html", new_html, sha, "📊 Update _smartData (auto)")
    print(f"  ✅ index.html commit: {commit}")
    print("✅ Done!")


if __name__ == "__main__":
    main()
