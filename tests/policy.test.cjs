'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const {inspect} = require('../scripts/check_source.cjs');

test('policy distinguishes comments from URLs, regular expressions, and CSS strings', () => {
  assert.deepEqual(inspect('sample.js', 'var value = "https://example.test"; var pattern = /https?:\\/\\//;'), []);
  assert.equal(inspect('sample.js', 'var value = 1; // explanation').length, 1);
  assert.equal(inspect('sample.css', 'a {color: red} /* explanation */').length, 1);
  assert.deepEqual(inspect('sample.css', 'a:before {content: "/* literal */"}'), []);
});

test('HT-27 runtime syntax gate rejects modern syntax but permits host tests', () => {
  assert.throws(() => inspect('app.js', 'const value = () => 1;'));
  assert.deepEqual(inspect('tests/example.cjs', 'const value = () => 1;'), []);
});
