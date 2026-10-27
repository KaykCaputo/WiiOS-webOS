'use strict';
const fs = require('node:fs');
const acorn = require('acorn');
const postcss = require('postcss');

function inspect(path, source) {
  const errors = [];
  if (/\.(?:js|cjs)$/.test(path)) {
    const runtime = !path.includes('/') || path.startsWith('root-services/') || path.startsWith('platform/');
    acorn.parse(source, {ecmaVersion: runtime ? 5 : 'latest', allowHashBang: true,
      onComment: (block, text, start) => {
        if (!(start === 0 && source.startsWith('#!'))) errors.push('Source comment');
      }});
  } else if (path.endsWith('.css')) {
    postcss.parse(source, {from: path, map: false}).walkComments(() => errors.push('Source comment'));
  }
  return errors;
}

module.exports = {inspect};
if (require.main === module) {
  const paths = JSON.parse(fs.readFileSync(0, 'utf8'));
  const errors = [];
  for (const path of paths) {
    try { for (const error of inspect(path, fs.readFileSync(path, 'utf8'))) errors.push(path + ': ' + error); }
    catch (error) { errors.push(path + ': ' + error.message); }
  }
  process.stdout.write(JSON.stringify(errors));
  process.exitCode = errors.length ? 1 : 0;
}
