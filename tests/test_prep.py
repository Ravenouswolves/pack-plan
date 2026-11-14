#!/usr/bin/env python3
"""Prep-branch checks for Pack Plan: first run, persistence, disclaimer,
no console errors, 390px wrap fixes, service worker, and no unexpected
outside calls."""
HOST = 'https://ravenouswolves.github.io/pack-plan/'  # GitHub Pages test host; swap at the real launch
import json
import os
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PORT = int(os.environ.get('WB_PORT', '8765'))
URL = os.environ.get('WB_URL', f'http://127.0.0.1:{PORT}/index.html')
ORIGIN = URL.rsplit('/', 1)[0]
CHROME = '/usr/bin/google-chrome'

fails = []
results = []

def check(name, cond, detail=''):
    status = 'PASS' if cond else 'FAIL'
    results.append({'name': name, 'ok': bool(cond), 'detail': str(detail)})
    print(f'  [{status}] {name}' + (f' — {detail}' if detail else ''))
    if not cond:
        fails.append(name + ((': ' + str(detail)) if detail else ''))

def line_words(page, sel):
    return page.evaluate("""(sel) => {
      const el = document.querySelector(sel);
      if (!el) return {error: 'missing ' + sel};
      const lines = [];
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) {
        const node = walker.currentNode;
        const text = node.textContent;
        const re = /\\S+/g;
        let m;
        while ((m = re.exec(text))) {
          const range = document.createRange();
          range.setStart(node, m.index);
          range.setEnd(node, m.index + m[0].length);
          const r = range.getBoundingClientRect();
          if (r.width === 0 && r.height === 0) continue;
          const top = Math.round(r.top * 2) / 2;
          let line = lines.find(l => Math.abs(l.top - top) < 2);
          if (!line) { line = {top, words: []}; lines.push(line); }
          line.words.push(m[0]);
        }
      }
      lines.sort((a,b) => a.top - b.top);
      return {
        text: el.innerText,
        lines: lines.map(l => ({words: l.words, text: l.words.join(' ')}))
      };
    }""", sel)


# ---------- static file / source checks (no browser) ----------
html = (ROOT / 'index.html').read_text()
headers = (ROOT / '_headers').read_text()
sw_src = (ROOT / 'sw.js').read_text()
robots = (ROOT / 'robots.txt').read_text()
sitemap = (ROOT / 'sitemap.xml').read_text()

check('STORE_KEY is rwBudget.v1', "STORE_KEY = 'rwBudget.v1'" in html)
check('empty first-run state has empty lists',
      re.search(r'function emptyState\(\)\{[^}]+income: \[\]', html) is not None)
check('footer disclaimer in source',
      'Free tool by Ravenous Wolves' in html
      and 'Your data stays on this device' in html
      and 'Not financial advice' in html)
# No API keys: no obvious secret material, and no fetch/XHR
check('no fetch() or XHR in the app', 'fetch(' not in html and 'XMLHttp' not in html)
check('no apiKey-like strings',
      not re.search(r'api[_-]?key|sk-[A-Za-z0-9]|Bearer\s+[A-Za-z0-9]', html, re.I))
# Outside URLs in source: only Google Fonts (plus w3.org SVG namespace, not a network call)
urls = set(re.findall(r'https?://[^\s"\'<>]+', html))
non_font = [u for u in urls if 'fonts.googleapis.com' not in u and 'fonts.gstatic.com' not in u
            and 'www.w3.org/2000/svg' not in u and 'https://DOMAIN' not in u and HOST not in u]
check('only Google Fonts as outside calls (plus DOMAIN placeholders and SVG ns)',
      non_font == [], non_font)
check('Google Fonts preconnect + stylesheet present',
      'fonts.googleapis.com' in html and 'fonts.gstatic.com' in html)
check('CSP allows Google Fonts',
      'fonts.googleapis.com' in headers and 'fonts.gstatic.com' in headers
      and 'Content-Security-Policy' in headers)
check('SW ignores cross-origin', 'url.origin !== self.location.origin' in sw_src)
check('SW is network-first for HTML', 'isHTMLRequest' in sw_src and 'network' in sw_src.lower())
check('site host uses /pack-plan/ slug',
      HOST in robots and HOST in sitemap
      and 'rel="canonical"' in html and HOST in html)
check('Open Graph tags name Pack Plan',
      'og:title' in html and 'Pack Plan' in html
      and 'property="og:title" content="Pack Plan"' in html
      and 'og:description' in html and 'og:url' in html)
check('Export and Import already in the app',
      'data-testid="export-btn"' in html and 'data-testid="import-btn"' in html
      and 'function exportJson' in html)
check('404.html exists', (ROOT / '404.html').is_file())
check('manifest.json names Pack Plan',
      (ROOT / 'manifest.json').is_file()
      and 'Pack Plan' in (ROOT / 'manifest.json').read_text())
check('SW cache is pack-plan-shell-v1', "CACHE = 'pack-plan-shell-v1'" in sw_src)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=CHROME,
            args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'],
            headless=True,
        )

        # --- 390px: blank first run, persistence, disclaimer, wrap fixes ---
        ctx = browser.new_context(
            viewport={'width': 390, 'height': 844},
            device_scale_factor=2,
            locale='en-US',
        )
        page = ctx.new_page()
        errors = []
        console_errors = []
        requests = []

        def on_console(msg):
            if msg.type == 'error':
                text = msg.text
                if 'favicon' in text.lower():
                    return
                console_errors.append(text)

        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', on_console)
        page.on('request', lambda r: requests.append(r.url))

        page.goto(URL, wait_until='networkidle')
        page.evaluate('() => localStorage.clear()')
        page.reload(wait_until='networkidle')
        page.wait_for_selector('h1')

        # Blank first run
        h1 = page.inner_text('h1')
        check('title is Pack Plan', 'pack plan' in h1.lower(), h1)
        main_txt = page.inner_text('main')
        check('blank first-run hero',
              'a free, private budget tool' in main_txt.lower()
              and 'load example data' in main_txt.lower(), main_txt[:400])
        stored = page.evaluate("() => localStorage.getItem('rwBudget.v1')")
        # First paint may not write an empty state; either absent or empty lists is fine
        if stored is None:
            check('first run has no rwBudget.v1 (or empty)', True, 'absent')
        else:
            data = json.loads(stored)
            empty = (not data.get('income') and not data.get('bills') and not data.get('debts')
                     and not data.get('goals') and not data.get('categories')
                     and not data.get('transactions'))
            check('first run rwBudget.v1 is empty', empty, stored[:200])
        check('disclaimer on blank first run',
              'Free tool by Ravenous Wolves' in main_txt
              and 'Your data stays on this device' in main_txt
              and 'Not financial advice' in main_txt)

        # Outside requests should only be the app origin + Google Fonts
        outside = []
        for u in requests:
            if u.startswith(ORIGIN) or u.startswith('http://127.0.0.1') or u.startswith('http://localhost'):
                continue
            if 'fonts.googleapis.com' in u or 'fonts.gstatic.com' in u:
                continue
            outside.append(u)
        check('runtime outside requests are only Google Fonts', outside == [], outside)

        # Persistence: load example, reload, key is rwBudget.v1
        page.click('[data-testid="load-example"]')
        page.wait_for_selector('[data-testid="left-to-assign"]')
        left = page.inner_text('[data-testid="left-to-assign"]')
        stored = page.evaluate("() => localStorage.getItem('rwBudget.v1')")
        check('example data written to rwBudget.v1',
              stored is not None and 'Example paycheck' in stored, 'key')
        # Confirm no other budget keys
        keys = page.evaluate("() => Object.keys(localStorage)")
        budget_keys = [k for k in keys if k.startswith('rwBudget')]
        check('only rwBudget.v1 (and maybe rwBudget.theme) keys',
              set(budget_keys) <= {'rwBudget.v1', 'rwBudget.theme'}, budget_keys)
        page.reload(wait_until='networkidle')
        page.wait_for_selector('[data-testid="left-to-assign"]')
        left2 = page.inner_text('[data-testid="left-to-assign"]')
        check('persists after reload', left2 == left, f'{left2} vs {left}')

        # 390px overdue wrap: last line must not be a single word when there are 2+ lines
        info = line_words(page, '.soft.warn > div')
        if 'error' in info:
            # fallback to .soft.warn
            info = line_words(page, '.soft.warn')
        check('overdue warning is present', 'error' not in info and 'overdue' in info.get('text','').lower(), info)
        lines = info.get('lines') or []
        if len(lines) >= 2:
            last = lines[-1]['words']
            check('overdue last line is not a single word',
                  len(last) >= 2, json.dumps(lines))
        else:
            check('overdue warning fits on one line (no orphan wrap)', True, info)

        # 390px payoff table: long debt names must not wrap
        page.click('nav.tabs button[data-view="debts"]')
        page.wait_for_selector('[data-testid="plan-table"]')
        page.wait_for_timeout(200)
        wraps = page.evaluate("""() => {
          function lineCount(el) {
            const texts = [];
            const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
            while (walker.nextNode()) {
              const node = walker.currentNode;
              const re = /\\S+/g; let m;
              while ((m = re.exec(node.textContent))) {
                const range = document.createRange();
                range.setStart(node, m.index);
                range.setEnd(node, m.index + m[0].length);
                const r = range.getBoundingClientRect();
                if (!r.height) continue;
                const top = Math.round(r.top);
                if (!texts.some(t => Math.abs(t - top) < 2)) texts.push(top);
              }
            }
            return texts.length;
          }
          const cells = [...document.querySelectorAll('.plan-table .debt-name')];
          if (!cells.length) return {error: 'no .debt-name cells'};
          return cells.slice(0, 8).map(td => {
            const cs = getComputedStyle(td);
            const n = lineCount(td);
            return {
              text: td.innerText, lines: n, wraps: n > 1,
              whiteSpace: cs.whiteSpace, overflow: cs.overflow,
              textOverflow: cs.textOverflow
            };
          });
        }""")
        if isinstance(wraps, dict) and 'error' in wraps:
            check('payoff debt-name cells exist', False, wraps)
        else:
            bad = [c for c in wraps if c['wraps']]
            check('payoff debt names do not wrap at 390px', not bad, json.dumps(wraps))
            ellipsis = all(c['textOverflow'] == 'ellipsis' and 'nowrap' in c['whiteSpace'] for c in wraps)
            check('payoff debt names use ellipsis at 390px', ellipsis, wraps[0] if wraps else '')

        # A deliberately long name also stays on one line
        page.evaluate("""() => {
          const s = window.__wb.getState();
          s.debts = s.debts.map((d, i) => i === 1
            ? Object.assign({}, d, {name: 'Example student loan — federal subsidized'})
            : d);
          window.__wb.setState(s);
        }""")
        page.wait_for_timeout(200)
        long_wraps = page.evaluate("""() => {
          function lineCount(el) {
            const texts = [];
            const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
            while (walker.nextNode()) {
              const node = walker.currentNode;
              const re = /\\S+/g; let m;
              while ((m = re.exec(node.textContent))) {
                const range = document.createRange();
                range.setStart(node, m.index);
                range.setEnd(node, m.index + m[0].length);
                const r = range.getBoundingClientRect();
                if (!r.height) continue;
                const top = Math.round(r.top);
                if (!texts.some(t => Math.abs(t - top) < 2)) texts.push(top);
              }
            }
            return texts.length;
          }
          const cells = [...document.querySelectorAll('.plan-table .debt-name')];
          return cells.filter(td => /federal/.test(td.innerText) || (td.getAttribute('title')||'').includes('federal'))
            .slice(0, 4).map(td => {
              const n = lineCount(td);
              return {text: td.innerText, title: td.getAttribute('title'), lines: n, wraps: n > 1};
            });
        }""")
        check('long debt names stay one line at 390px',
              long_wraps and all(not c['wraps'] for c in long_wraps), json.dumps(long_wraps))

        # Desktop 1280: "Example student loan" (standard example) still wraps freely
        # (design unchanged). Use a fresh page at 1280 after resetting to example names.
        desk = browser.new_context(viewport={'width': 1280, 'height': 900}, locale='en-US').new_page()
        desk_err = []
        desk.on('pageerror', lambda e: desk_err.append(str(e)))
        desk.goto(URL, wait_until='networkidle')
        desk.evaluate('() => localStorage.clear()')
        desk.reload(wait_until='networkidle')
        desk.click('[data-testid="load-example"]')
        desk.wait_for_selector('[data-testid="left-to-assign"]')
        desk.click('nav.tabs button[data-view="debts"]')
        desk.wait_for_selector('[data-testid="plan-table"]')
        desk_info = desk.evaluate("""() => {
          const cells = [...document.querySelectorAll('.plan-table td')];
          const loan = cells.find(td => (td.innerText||'').includes('Example student loan'));
          if (!loan) return {error: 'no loan cell'};
          const cs = getComputedStyle(loan);
          return {
            text: loan.innerText,
            w: Math.round(loan.getBoundingClientRect().width),
            h: Math.round(loan.getBoundingClientRect().height),
            whiteSpace: cs.whiteSpace,
            textOverflow: cs.textOverflow,
            tableLayout: getComputedStyle(loan.closest('table')).tableLayout
          };
        }""")
        check('desktop table layout is not forced-fixed',
              desk_info.get('tableLayout') == 'auto', desk_info)
        check('desktop standard debt name is visible in full (no ellipsis)',
              desk_info.get('text', '').startswith('Example student loan')
              and desk_info.get('textOverflow') in ('clip', '') 
              or (desk_info.get('whiteSpace') == 'normal' and desk_info.get('textOverflow') != 'ellipsis'),
              desk_info)
        # overdue at desktop: should be one line (design unchanged)
        desk.click('nav.tabs button[data-view="overview"]')
        desk.wait_for_selector('.soft.warn')
        dlines = line_words(desk, '.soft.warn > div')
        check('desktop overdue warning is a single line',
              'error' not in dlines and len(dlines.get('lines') or []) == 1, dlines)
        check('desktop no page errors', desk_err == [], desk_err)

        # Service worker: registers, reload still works, offline shell serves
        # Need a fresh context that's not already mid-test. Reuse 390 page.
        # Unregister first then re-register by reload, wait for ready.
        ready = page.evaluate("() => navigator.serviceWorker.ready.then(r => r.active && r.active.scriptURL)")
        check('service worker became ready', ready and str(ready).endswith('/sw.js'), ready)
        # Online reload still shows the app (network-first)
        page.reload(wait_until='networkidle')
        page.wait_for_selector('h1')
        check('reload after SW still shows Pack Plan', 'pack plan' in page.inner_text('h1').lower())
        # Offline: HTML falls back to cache. Data is in localStorage so example may still show.
        ctx.set_offline(True)
        page.reload(wait_until='domcontentloaded')
        page.wait_for_selector('h1', timeout=8000)
        check('offline shell still shows Pack Plan', 'pack plan' in page.inner_text('h1').lower())
        ctx.set_offline(False)

        check('zero page errors', errors == [], errors)
        check('zero console errors', console_errors == [], console_errors)

        # Clear sample data used during the test (leave the origin clean)
        page.evaluate("""() => { localStorage.removeItem('rwBudget.v1'); }""")

        browser.close()

    print('\n====', 'PASS' if not fails else 'FAIL',
          f'{len(results)-len(fails)}/{len(results)} checks ====')
    Path('/tmp/wb_prep_results.json').write_text(json.dumps({'ok': not fails, 'checks': results}, indent=2))
    return 0 if not fails else 1

if __name__ == '__main__':
    sys.exit(main())
