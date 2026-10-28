'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const {inspect} = require('../scripts/check_source.cjs');

test('policy allows documentation comments and distinguishes syntax from text', () => {
  assert.deepEqual(inspect('sample.js', 'var value = "https://example.test"; var pattern = /https?:\\/\\//;'), []);
  assert.deepEqual(inspect('sample.js', 'var value = 1; // Explain why this branch is safe.'), []);
  assert.deepEqual(inspect('sample.css', 'a {color: red} /* Keep focus visible for remote navigation. */'), []);
  assert.deepEqual(inspect('sample.css', 'a:before {content: "/* literal */"}'), []);
});

test('HT-27 runtime syntax gate rejects modern syntax but permits host tests', () => {
  assert.throws(() => inspect('app.js', 'const value = () => 1;'));
  assert.deepEqual(inspect('tests/example.cjs', 'const value = () => 1;'), []);
});
