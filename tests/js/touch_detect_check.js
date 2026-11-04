// Detección automática del modo touch (Plan 7): node tests/js/touch_detect_check.js
const assert = require('assert');
const { detect } = require('../../static/js/touch-detect.js');
const mm = (flags) => (q) => ({ matches: !!flags[q] });
const DESKTOP = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36';
assert.strictEqual(detect({ matchMedia: mm({ '(pointer: fine)': true }), userAgent: DESKTOP }), false, 'PC con mouse: apagado');
assert.strictEqual(detect({ userAgent: DESKTOP }), false, 'sin matchMedia: se decide por userAgent');
assert.strictEqual(detect({}), false);
assert.strictEqual(detect({ matchMedia: mm({ '(pointer: coarse)': true }), userAgent: DESKTOP }), true, 'puntero grueso');
assert.strictEqual(detect({ matchMedia: mm({ '(hover: none)': true }), userAgent: DESKTOP }), true, 'sin hover');
assert.strictEqual(detect({ matchMedia: mm({}), userAgent: 'Mozilla/5.0 (Linux; Android 14; SM-X710) AppleWebKit/537.36 Chrome/130 Safari/537.36' }), true, 'tableta Android');
assert.strictEqual(detect({ matchMedia: mm({}), userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148' }), true, 'iPhone');
assert.strictEqual(detect({ matchMedia: mm({}), userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15', maxTouchPoints: 5 }), true, 'iPad en modo escritorio');
assert.strictEqual(detect({ matchMedia: mm({}), userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15', maxTouchPoints: 0 }), false, 'Mac real');
assert.strictEqual(detect({ matchMedia: () => { throw new Error('x'); }, userAgent: DESKTOP }), false, 'matchMedia que falla no rompe');
console.log('touch_detect_check OK');
