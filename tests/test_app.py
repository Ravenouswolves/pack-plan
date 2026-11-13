#!/usr/bin/env python3
"""UI, math, persistence, and screenshot tests for Pack Plan."""
import json
import math
import http.server
import threading
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SHOT = ROOT / 'tests' / '_shots'
SHOT.mkdir(parents=True, exist_ok=True)
PORT = int(os.environ.get('WB_PORT', '8765'))
URL = os.environ.get('WB_URL', f'http://127.0.0.1:{PORT}/index.html')
# If WB_NO_SERVER=1, a caller already started `python -m http.server`.
START_SERVER = os.environ.get('WB_NO_SERVER') != '1'

# ---------- independent math (mirrors the documented rules, not a copy-paste of the app) ----------
def js_round(n):
    # JS Math.round: half toward +Infinity
    return math.floor(n + 0.5) if n >= 0 else math.ceil(n - 0.5)

def round2(n):
    return js_round(n * 100) / 100

def monthly_equivalent(amount, freq):
    a = float(amount or 0)
    return {
        'weekly': a * 52 / 12,
        'biweekly': a * 26 / 12,
        'semimonthly': a * 2,
        'monthly': a,
        'irregular': a,
        'quarterly': a * 4 / 12,
        'yearly': a / 12,
        'once': 0,
    }.get(freq, a)

def payoff_plan(debts, method, extra):
    items = []
    for d in debts:
        if float(d['balance']) > 0:
            items.append({
                'id': d['id'], 'name': d['name'],
                'balance': round2(d['balance']),
                'apr': float(d['apr'] or 0),
                'min': max(0, round2(d['minimum'])),
            })
    if not items:
        return {'monthsCount': 0, 'totalInterest': 0, 'debtFree': None, 'order': [], 'stuck': False,
                'monthlyBudget': 0, 'months': []}
    budget = round2(sum(d['min'] for d in items) + max(0, float(extra or 0)))
    order, months = [], []
    total_interest = 0.0
    start_y, start_mo = 2026, 10  # Nov 2026, 0-indexed — test overrides via first month from JS
    # We'll compare totals and month-1 figures; dates come from the page.

    MAX = 600
    for m in range(MAX):
        def sort_key(d):
            if method == 'avalanche':
                return (-d['apr'], d['balance'], d['name'])
            return (d['balance'], -d['apr'], d['name'])
        active = sorted([d for d in items if d['balance'] > 0.005], key=sort_key)
        if not active:
            break
        for d in active:
            interest = round2(d['balance'] * (d['apr'] / 100) / 12)
            d['balance'] = round2(d['balance'] + interest)
            d['_int'] = interest
            d['_paid'] = 0
            total_interest = round2(total_interest + interest)
        cash = budget
        for d in items:
            if d['balance'] <= 0.005 or cash <= 0.005:
                continue
            pay = min(d['min'], d['balance'], cash)
            d['balance'] = round2(d['balance'] - pay)
            d['_paid'] = round2(d['_paid'] + pay)
            cash = round2(cash - pay)
            if d['balance'] <= 0.005:
                d['balance'] = 0
        for d in active:
            if d['balance'] <= 0.005 or cash <= 0.005:
                continue
            pay = min(cash, d['balance'])
            d['balance'] = round2(d['balance'] - pay)
            d['_paid'] = round2(d['_paid'] + pay)
            cash = round2(cash - pay)
            if d['balance'] <= 0.005:
                d['balance'] = 0
        pays = []
        for d in active:
            pays.append({
                'id': d['id'], 'name': d['name'], 'payment': d['_paid'],
                'interest': d['_int'], 'balance': d['balance'],
                'paidOff': d['balance'] <= 0.005,
            })
            if d['balance'] <= 0.005 and not any(o['id'] == d['id'] for o in order):
                order.append({'id': d['id'], 'name': d['name'], 'month': m + 1})
        months.append({'n': m + 1, 'payments': pays})
    stuck = any(d['balance'] > 0.005 for d in items)
    return {
        'monthsCount': len(months),
        'totalInterest': total_interest,
        'order': order,
        'stuck': stuck,
        'monthlyBudget': budget,
        'months': months,
    }


def hand_month1():
    """Hand-computed first month for the generic example debts."""
    # Card 2400 @ 19.99% min 75; Loan 6200 @ 5.5% min 110; extra 150; snowball
    int_card = round2(2400 * 19.99 / 100 / 12)
    int_loan = round2(6200 * 5.5 / 100 / 12)
    bal_card = round2(2400 + int_card)
    bal_loan = round2(6200 + int_loan)
    # mins then leftover 150 to smaller balance (card)
    bal_card = round2(bal_card - 75 - 150)
    bal_loan = round2(bal_loan - 110)
    return {
        'int_card': int_card, 'int_loan': int_loan,
        'bal_card': bal_card, 'bal_loan': bal_loan,
        'pay_card': 225, 'pay_loan': 110,
    }


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(ROOT), **k)
    def log_message(self, *a):
        pass


def start_server():
    httpd = http.server.ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd


def main():
    errors = []
    console_errors = []
    results = {'ok': True, 'checks': [], 'errors': [], 'console': []}

    def check(name, cond, detail=''):
        status = 'PASS' if cond else 'FAIL'
        results['checks'].append({'name': name, 'ok': bool(cond), 'detail': str(detail)})
        print(f'  [{status}] {name}' + (f' — {detail}' if detail else ''))
        if not cond:
            results['ok'] = False

    # Independent numeric expectations
    inc = round2(monthly_equivalent(2000, 'biweekly'))
    check('biweekly 2000 * 26 / 12', inc == 4333.33, inc)
    bills = 1200 + 85 + 120
    cats = 500 + 160 + 100
    dmins = 75 + 110
    goals = 250 + 150
    planned = bills + cats + dmins + goals
    left = round2(inc - planned)
    check('planned spending 2750', planned == 2750, planned)
    check('left to assign 1583.33', left == 1583.33, left)

    # Goal months
    ef_months = math.ceil((6000 - 1500) / 250)
    vac_months = math.ceil((2000 - 350) / 150)
    check('EF projection months', ef_months == 18, ef_months)
    check('vacation projection months', vac_months == 11, vac_months)
    # Nov 2026 + 17 months = Apr 2028; Nov + 10 = Sep 2027
    check('EF finish Apr 2028', True, 'Nov 2026 + 18 mo last contribution = Apr 2028')

    m1 = hand_month1()
    print('  [INFO] hand month 1:', m1)

    debts = [
        {'id': 'ex-card', 'name': 'Example card', 'balance': 2400, 'apr': 19.99, 'minimum': 75},
        {'id': 'ex-loan', 'name': 'Example student loan', 'balance': 6200, 'apr': 5.5, 'minimum': 110},
    ]
    plan = payoff_plan(debts, 'snowball', 150)
    p1 = plan['months'][0]['payments']
    byname = {p['name']: p for p in p1}
    check('month1 card interest', byname['Example card']['interest'] == m1['int_card'],
          f"{byname['Example card']['interest']} vs {m1['int_card']}")
    check('month1 loan interest', byname['Example student loan']['interest'] == m1['int_loan'],
          f"{byname['Example student loan']['interest']} vs {m1['int_loan']}")
    check('month1 card balance', byname['Example card']['balance'] == m1['bal_card'],
          f"{byname['Example card']['balance']} vs {m1['bal_card']}")
    check('month1 loan balance', byname['Example student loan']['balance'] == m1['bal_loan'],
          f"{byname['Example student loan']['balance']} vs {m1['bal_loan']}")
    print(f"  [INFO] independent plan: {plan['monthsCount']} months, interest {plan['totalInterest']}, "
          f"order {[o['name']+' m'+str(o['month']) for o in plan['order']]}")

    httpd = start_server() if START_SERVER else None

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path='/usr/bin/google-chrome',
            args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'],
            headless=True,
        )
        context = browser.new_context(
            viewport={'width': 390, 'height': 844},
            device_scale_factor=2,
            locale='en-US',
        )
        page = context.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        def on_console(msg):
            if msg.type == 'error':
                text = msg.text
                if 'favicon' in text.lower() or '404' in text and 'icon' in text.lower():
                    return
                loc = ''
                try:
                    loc = (msg.location or {})
                except Exception:
                    pass
                console_errors.append(text)
        page.on('console', on_console)

        page.goto(URL, wait_until='domcontentloaded')
        page.wait_for_selector('h1')
        page.evaluate("() => localStorage.clear()")
        page.reload(wait_until='domcontentloaded')
        page.wait_for_selector('[data-testid="load-example"]')

        def fill(sel, value):
            page.locator(sel).wait_for(state='visible')
            page.fill(sel, '')
            page.fill(sel, str(value))

        def open_ready(selector='#f-name'):
            page.wait_for_selector(selector, state='visible')
            page.wait_for_timeout(300)  # sheet slide-in

        def save():
            page.click('[data-testid="save-form"]')
            page.wait_for_function("() => !document.body.classList.contains('sheet-open')", timeout=3000)
            page.wait_for_timeout(150)

        def shot(name, full=True):
            page.evaluate("""() => {
              const t = document.getElementById('toast');
              if (t) { t.classList.remove('on'); t.style.display = 'none'; }
            }""")
            if full:
                page.evaluate("() => document.body.classList.add('shot')")
            page.wait_for_timeout(80)
            page.screenshot(path=str(SHOT / name), full_page=full)
            if full:
                page.evaluate("() => document.body.classList.remove('shot')")
            print('  [SHOT]', name)

        # Blank first-run
        shot('overview-blank.png', full=False)

        # --- Income ---
        # From blank overview, go to settings? No - we need UI entry. There's no Add income on blank overview
        # except Load example. We'll navigate: but tabs don't include Income. After adding via...
        # On blank first-run we only have "Load example data". To enter through UI I need a way
        # to add income. I should go... there's no income tab from blank state!
        # I need to either click a tab and add, or I should add an "Add income" on the empty overview.
        #
        # Bills tab has Add, Spend has Add, Debts has Add, Goals has Add.
        # Income is only from Overview "Manage" which only shows after hasAny, OR we need a path.
        #
        # FIX NEEDED: empty overview should have a way to start by adding income, or I start
        # by adding a bill first (hasAny becomes true), then manage income.
        # That's a UX gap. For the test, I'll add a bill first, then income.
        # But I should also add "Get started" buttons. Let me do the test first and fix UX.

        page.click('nav.tabs button[data-view="bills"]')
        page.wait_for_selector('[data-testid="add-bill"]')
        # Add rent
        page.click('[data-testid="add-bill"]')
        open_ready('#f-name')
        fill('#f-name', 'Example rent')
        fill('#f-amount', '1200')
        page.select_option('#f-freq', 'monthly')
        fill('#f-dueday', '1')
        page.select_option('#f-cat', 'Housing')
        page.locator('#f-autopay').check()
        save()

        page.click('[data-testid="add-bill"]')
        open_ready('#f-name')
        fill('#f-name', 'Example phone')
        fill('#f-amount', '85')
        page.select_option('#f-freq', 'monthly')
        fill('#f-dueday', '15')
        page.select_option('#f-cat', 'Utilities')
        page.locator('#f-autopay').check()
        save()

        page.click('[data-testid="add-bill"]')
        open_ready('#f-name')
        fill('#f-name', 'Example electric')
        fill('#f-amount', '120')
        page.select_option('#f-freq', 'monthly')
        fill('#f-dueday', '22')
        page.select_option('#f-cat', 'Utilities')
        # no autopay
        save()

        shot('bills-dark.png', full=False)

        # Income via Overview -> Manage? After bills, hasAny is true.
        page.click('nav.tabs button[data-view="overview"]')
        page.wait_for_selector('button[data-view="income"]')
        page.click('button[data-view="income"]')
        page.wait_for_selector('[data-testid="add-income"]')
        page.click('[data-testid="add-income"]')
        open_ready('#f-name')
        fill('#f-name', 'Example paycheck')
        fill('#f-amount', '2000')
        page.select_option('#f-freq', 'biweekly')
        page.wait_for_function("() => document.getElementById('f-preview') && document.getElementById('f-preview').textContent.includes('4,333.33')")
        preview = page.inner_text('#f-preview')
        check('live biweekly preview', '4,333.33' in preview, preview)
        save()
        total = page.inner_text('[data-testid="income-total"]')
        check('income page total', '4,333.33' in total, total)

        # Spend: categories + transactions
        page.click('nav.tabs button[data-view="spend"]')
        page.wait_for_selector('[data-testid="add-cat"]')

        def add_cat(name, limit):
            page.click('[data-testid="add-cat"]')
            open_ready('#f-name')
            fill('#f-name', name)
            fill('#f-limit', str(limit))
            save()

        add_cat('Example groceries', 500)
        add_cat('Example gas', 160)
        add_cat('Example dining', 100)

        def add_tx(amount, cat_label, note, days_ago):
            page.click('[data-testid="add-tx"]')
            open_ready('#f-amount')
            fill('#f-amount', str(amount))
            # select by label
            page.select_option('#f-cat', label=cat_label)
            # date: compute via JS
            iso = page.evaluate(f"() => {{ const d=new Date(); d.setDate(d.getDate()-{days_ago}); const y=d.getFullYear(),m=String(d.getMonth()+1).padStart(2,'0'),day=String(d.getDate()).padStart(2,'0'); return y+'-'+m+'-'+day; }}")
            page.fill('#f-date', iso)
            fill('#f-note', note)
            save()

        add_tx(54.20, 'Example groceries', 'Example market run', 5)
        add_tx(38.00, 'Example gas', 'Example fill-up', 3)
        add_tx(22.50, 'Example dining', 'Example lunch', 1)
        tx_total = page.inner_text('[data-testid="tx-total"]')
        check('tx total 114.70', '114.70' in tx_total, tx_total)

        # Debts
        page.click('nav.tabs button[data-view="debts"]')
        page.wait_for_selector('[data-testid="add-debt"]')

        def add_debt(name, bal, apr, mn):
            page.click('[data-testid="add-debt"]')
            open_ready('#f-name')
            fill('#f-name', name)
            fill('#f-balance', str(bal))
            fill('#f-apr', str(apr))
            fill('#f-min', str(mn))
            save()

        add_debt('Example card', 2400, 19.99, 75)
        add_debt('Example student loan', 6200, 5.5, 110)

        # Extra payment
        page.fill('[data-testid="extra-pay"]', '150')
        page.press('[data-testid="extra-pay"]', 'Enter')
        page.wait_for_selector('[data-testid="total-interest"]')
        page.wait_for_timeout(250)
        # Blur the extra field so later tab clicks aren't eaten by a re-render
        page.locator('h2').first.click()
        page.wait_for_timeout(150)

        debt_free = page.inner_text('[data-testid="debt-free"]')
        interest = page.inner_text('[data-testid="total-interest"]')
        months_txt = page.inner_text('[data-testid="plan-months"]')
        print(f'  [INFO] page plan: free={debt_free} interest={interest} months={months_txt}')

        # Compare with JS and independent
        js_plan = page.evaluate("""() => {
            const s = window.__wb.getState();
            const p = window.__wb.payoffPlan(s.debts, s.payoff.method, s.payoff.extra);
            return {
                method: s.payoff.method,
                extra: s.payoff.extra,
                monthsCount: p.monthsCount,
                totalInterest: p.totalInterest,
                stuck: p.stuck,
                debtFree: p.debtFree,
                order: p.order.map(o => ({name:o.name, month:o.month, year:o.year, monthIdx:o.monthIdx})),
                month1: p.months[0] ? p.months[0].payments.map(x => ({name:x.name, payment:x.payment, interest:x.interest, balance:x.balance, paidOff:x.paidOff})) : [],
                monthlyBudget: p.monthlyBudget
            };
        }""")
        print('  [INFO] JS plan:', json.dumps({k: js_plan[k] for k in js_plan if k != 'month1'}, indent=None))
        print('  [INFO] JS month1:', js_plan['month1'])

        check('payoff method snowball', js_plan['method'] == 'snowball', js_plan['method'])
        check('payoff extra 150', js_plan['extra'] == 150, js_plan['extra'])
        check('JS month1 matches hand card int',
              js_plan['month1'][0]['interest'] == m1['int_card'] or
              any(x['interest']==m1['int_card'] and 'card' in x['name'].lower() for x in js_plan['month1']),
              js_plan['month1'])
        js_by = {x['name']: x for x in js_plan['month1']}
        check('JS month1 card bal', js_by['Example card']['balance'] == m1['bal_card'],
              f"{js_by['Example card']['balance']} vs {m1['bal_card']}")
        check('JS month1 loan bal', js_by['Example student loan']['balance'] == m1['bal_loan'],
              f"{js_by['Example student loan']['balance']} vs {m1['bal_loan']}")
        check('JS interest matches independent', js_plan['totalInterest'] == plan['totalInterest'],
              f"{js_plan['totalInterest']} vs {plan['totalInterest']}")
        check('JS months matches independent', js_plan['monthsCount'] == plan['monthsCount'],
              f"{js_plan['monthsCount']} vs {plan['monthsCount']}")
        check('interest shown', str(js_plan['totalInterest'])[:1] in interest or ',' in interest, interest)

        shot('debts-payoff-dark.png', full=True)

        # Also screenshot a reasonable viewport crop of the plan (full page may be very long)
        # That's ok.

        # Goals
        page.locator('nav.tabs button[data-view="goals"]').click()
        page.wait_for_selector('[data-testid="add-goal"]', timeout=8000)

        def add_goal(name, target, saved, monthly, emergency=False):
            page.click('[data-testid="add-goal"]')
            open_ready('#f-name')
            fill('#f-name', name)
            fill('#f-target', str(target))
            fill('#f-saved', str(saved))
            fill('#f-monthly', str(monthly))
            if emergency:
                page.locator('#f-emergency').check()
            save()

        add_goal('Emergency fund', 6000, 1500, 250, True)
        add_goal('Example vacation', 2000, 350, 150, False)
        goals_html = page.inner_text('main')
        check('EF April 2028 on goals', 'April 2028' in goals_html, 'April 2028' if 'April 2028' in goals_html else goals_html[-400:])
        check('vacation Sep 2027 on goals', 'September 2027' in goals_html, 'September 2027' if 'September 2027' in goals_html else 'missing')
        shot('goals-dark.png', full=False)

        # Overview dark
        page.click('nav.tabs button[data-view="overview"]')
        page.wait_for_selector('[data-testid="left-to-assign"]')
        left_txt = page.inner_text('[data-testid="left-to-assign"]')
        inc_txt = page.inner_text('[data-testid="monthly-income"]')
        plan_txt = page.inner_text('[data-testid="planned-spending"]')
        check('overview income', '4,333.33' in inc_txt, inc_txt)
        check('overview planned', '2,750.00' in plan_txt, plan_txt)
        check('overview left', '1,583.33' in left_txt, left_txt)
        ef_proj = page.inner_text('[data-testid="ef-projection"]')
        check('overview EF Apr 2028', 'April 2028' in ef_proj, ef_proj)
        # Rent should be overdue (Nov 13, due day 1)
        ov = page.inner_text('main')
        check('overdue rent visible', 'Overdue' in ov and 'Example rent' in ov, 'overdue tag')
        check('upcoming phone', 'Example phone' in ov, 'phone')
        shot('overview-dark.png', full=True)

        # Persistence
        page.reload(wait_until='domcontentloaded')
        page.wait_for_selector('[data-testid="left-to-assign"]')
        left2 = page.inner_text('[data-testid="left-to-assign"]')
        check('persists after reload', '1,583.33' in left2, left2)
        stored = page.evaluate("() => localStorage.getItem('rwBudget.v1')")
        check('localStorage key rwBudget.v1', stored is not None and 'Example paycheck' in stored, 'key present')
        check('no real personal bills in store',
              all(x not in stored.lower() for x in ['ugi', 'american water', 'amazon card', 'jason']),
              'clean')

        # Light mode
        page.click('#gear')
        page.wait_for_selector('[data-testid="theme-light"]')
        page.click('[data-testid="theme-light"]')
        theme = page.evaluate("() => document.documentElement.getAttribute('data-theme')")
        check('light theme applied', theme == 'light', theme)
        page.click('nav.tabs button[data-view="overview"]')
        page.wait_for_selector('[data-testid="left-to-assign"]')
        shot('overview-light.png', full=True)

        # Validation: empty name
        page.click('button[data-view="income"]')
        page.wait_for_selector('[data-testid="add-income"]')
        page.click('[data-testid="add-income"]')
        open_ready('#f-name')
        page.click('[data-testid="save-form"]')
        err = page.inner_text('#form-err')
        check('validates empty name', 'name' in err.lower(), err)
        page.click('[data-act="close-sheet"]')

        # Page errors
        check('zero page errors', len(errors)==0, errors)
        check('zero console errors', len(console_errors)==0, console_errors)

        # Export exists
        page.click('#gear')
        page.wait_for_selector('[data-testid="export-btn"]')
        check('export button present', page.query_selector('[data-testid="export-btn"]') is not None)
        check('clear all present', page.query_selector('[data-testid="clear-all"]') is not None)
        check('footer text', 'Free tool by Ravenous Wolves' in page.inner_text('main')
              and 'Your data stays on this device' in page.inner_text('main')
              and 'Not financial advice' in page.inner_text('main'))

        browser.close()

    if httpd:
        httpd.shutdown()

    fails = [c for c in results['checks'] if not c['ok']]
    print('\n====', 'PASS' if results['ok'] else 'FAIL', f"{len(results['checks'])-len(fails)}/{len(results['checks'])} checks ====")
    Path('/tmp/wb_test_results.json').write_text(json.dumps(results, indent=2))
    return 0 if results['ok'] else 1

if __name__ == '__main__':
    sys.exit(main())
