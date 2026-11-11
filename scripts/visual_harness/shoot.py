"""Capturas: python3 shoot.py nombre=clave[?v=x][#accion] ...  [--sizes desk,cel] [--themes light,dark]
Guarda out/<nombre>_<tamaño>[_dark].png y escribe problemas (desborde, errores de consola, objetivos táctiles chicos)."""
import json
import os
import sys
from urllib.parse import urlparse, parse_qs

from playwright.sync_api import sync_playwright

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'out')
SIZES = {'w1560': (1560, 900), 'w1620': (1620, 900), 'w1700': (1700, 900), 'w1000': (1000, 800), 'w1100': (1100, 800), 'w1280': (1280, 800), 'w1500': (1500, 900), 'w1800': (1800, 900), 'desk': (1440, 900), 'tab': (1024, 768), 'cel': (390, 844), 'narrow': (700, 900)}
BASE = os.environ.get('BASE', 'http://127.0.0.1:8765/p/')

CHECK = r"""() => {
  const W = document.documentElement.clientWidth;
  const sw = document.scrollingElement.scrollWidth;
  const wide = [];
  if (sw > W + 1) {
    document.querySelectorAll('body *').forEach(el => {
      const r = el.getBoundingClientRect();
      if (r.width && r.right > W + 1 && getComputedStyle(el).position !== 'fixed') {
        let p = el.parentElement, clipped = false;
        while (p && p !== document.body) { const o = getComputedStyle(p).overflowX; if (o === 'auto' || o === 'scroll' || o === 'hidden') { clipped = true; break; } p = p.parentElement; }
        if (!clipped) wide.push((el.tagName + '.' + (el.className && el.className.baseVal === undefined ? el.className : '')).slice(0, 80) + ' r=' + Math.round(r.right));
      }
    });
  }
  const small = [];
  if (W < 500) document.querySelectorAll('button, a.gw-btn, input:not([type=hidden]), select, [role=button]').forEach(el => {
    const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
    if (r.width && r.height && cs.visibility !== 'hidden' && r.height < 40 && !(el.type === 'checkbox' || el.type === 'radio')) small.push((el.id || el.textContent.trim().slice(0, 30) || el.className) + ' ' + Math.round(r.width) + 'x' + Math.round(r.height));
  });
  return { overflow: sw > W + 1 ? sw - W : 0, wide: wide.slice(0, 8), small: small.slice(0, 12) };
}"""


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    opts = dict(a[2:].split('=', 1) for a in sys.argv[1:] if a.startswith('--'))
    sizes = opts.get('sizes', 'desk,tab,cel,narrow').split(',')
    themes = opts.get('themes', 'light,dark').split(',')
    maxh = int(opts.get('maxh', '3200'))
    os.makedirs(OUT, exist_ok=True)
    report = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        for spec in args:
            name, _, target = spec.partition('=')
            action = ''
            if '#' in target:
                target, action = target.split('#', 1)
            for th in themes:
                for sz in sizes:
                    w, h = SIZES[sz]
                    ctx = b.new_context(viewport={'width': w, 'height': h}, device_scale_factor=1, has_touch=sz == 'cel', is_mobile=sz == 'cel')
                    ctx.add_init_script("try{localStorage.setItem('gw_tours_seen','1');%s}catch(e){}" % ("localStorage.setItem('gw_theme','dark');" if th == 'dark' else "localStorage.removeItem('gw_theme');"))
                    # sin recorridos de primera vez (tapan la pantalla)
                    ctx.add_init_script("window.GW_TOURS_OFF = true; Object.defineProperty(window, 'GW_TOURS_OFF', {value: true, writable: false});")
                    vq = parse_qs(urlparse(target).query).get('v', [''])[0]
                    ctx.add_cookies([{'name': 'vv', 'value': vq, 'url': 'http://127.0.0.1:8765/'}])
                    pg = ctx.new_page()
                    errs = []
                    pg.on('console', lambda m: errs.append(m.text) if m.type == 'error' else None)
                    pg.on('pageerror', lambda e: errs.append('PAGEERROR ' + str(e)))
                    pg.goto(BASE + target, wait_until='load')
                    pg.wait_for_timeout(int(opts.get('wait', '1500')))
                    if action:
                        for step in action.split('||'):
                            kind, _, arg = step.partition(':')
                            try:
                                if kind == 'click':
                                    pg.click(arg, timeout=3000)
                                elif kind == 'js':
                                    pg.evaluate(arg)
                                elif kind == 'wait':
                                    pg.wait_for_timeout(int(arg))
                                elif kind == 'fill':
                                    sel, val = arg.split('=', 1)
                                    pg.fill(sel, val)
                            except Exception as e:
                                errs.append('ACCION ' + step + ': ' + str(e)[:120])
                        pg.wait_for_timeout(500)
                    if not opts.get('keep'):
                        pg.evaluate('window.scrollTo(0, 0)'); pg.wait_for_timeout(150)
                    chk = pg.evaluate(CHECK)
                    full_h = pg.evaluate('document.scrollingElement.scrollHeight')
                    fn = os.path.join(OUT, f'{name}_{sz}' + ('_dark' if th == 'dark' else '') + '.png')
                    elsel = opts.get('el')
                    if elsel:
                        pg.evaluate("document.documentElement.style.overflow='visible';document.body.style.overflow='visible'")
                        pg.locator(elsel).first.screenshot(path=fn)
                    else:
                        if opts.get('keep'):
                            pg.screenshot(path=fn)
                        else:
                            pg.screenshot(path=fn, full_page=True, clip={'x': 0, 'y': 0, 'width': w, 'height': min(full_h, maxh)})
                    errs = [e for e in errs if 'favicon' not in e and '404' not in e]
                    report[f'{name}_{sz}_{th}'] = {**chk, 'errors': errs[:5]}
                    ctx.close()
        b.close()
    for k, r in report.items():
        flags = []
        if r['overflow']:
            flags.append(f"DESBORDE {r['overflow']}px {r['wide']}")
        if r['errors']:
            flags.append('ERR ' + ' | '.join(r['errors']))
        if r['small'] and k.endswith('_light'):
            flags.append('CHICOS ' + ', '.join(r['small']))
        print(k, '; '.join(flags) if flags else 'ok')


if __name__ == '__main__':
    main()
