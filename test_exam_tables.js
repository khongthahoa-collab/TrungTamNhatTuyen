const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('static/js/exam-tables.js', 'utf8');
const context = { window: {} };
vm.runInNewContext(source.replace(/\}\)\(\);\s*$/, 'window.parseTable = parse; })();'), context);
const parse = value => JSON.parse(JSON.stringify(context.window.parseTable(value)));

const standard = 'Complete the table:\n| Compound | Cation | Anion |\n| :--- | :--- | :--- |\n| NaCl | Na^{+} | Cl^{-} |\n| MgO | Mg^{2+} | O^{2-} |';
const expected = {
  headers: ['Compound', 'Cation', 'Anion'],
  rows: [['NaCl', 'Na^{+}', 'Cl^{-}'], ['MgO', 'Mg^{2+}', 'O^{2-}']],
};
assert.deepEqual(parse(standard)[1], expected);
assert.deepEqual(parse(standard.replace(/\n/g, ' '))[1], expected);
assert.deepEqual(parse(standard.replace(/\n/g, '\\n'))[1], expected);
const math = '| Formula | Value |\n| --- | --- |\n| $|x|$ | \\(\\ce{Na+}\\) |\n| A\\|B | ... |';
assert.deepEqual(parse(math)[1].rows, [['$|x|$', '\\(\\ce{Na+}\\)'], ['A|B', '...']]);
const missing = 'Câu 2. Hoàn thành: | Công thức hợp chất ion | Cation | Anion | | :--- | :--- | :--- | | \n | ... | \n | | ... | \n | \n | | \n | ... | ... | | \n | ... | ... | | ... | \n | \n |';
assert.equal(parse(missing)[1].rows.length, 5);
assert.deepEqual(parse(missing)[1].rows[0], ['', '...', '']);
assert.equal(parse('Just A | B without a table'), null);
assert.equal(parse('$x^{2}$ and \\(\\ce{NaCl}\\)'), null);
assert.equal(parse('| A | B |\n| --- | --- |'), null);
assert.deepEqual(parse(standard + '\n\nAfter the table.').at(-1), { text: '\n\nAfter the table.' });
assert.deepEqual(parse('| A | B | | --- | --- | | <img src=x onerror=alert(1)> | <script>x</script> |')[1].rows,
  [['<img src=x onerror=alert(1)>', '<script>x</script>']]);

const elements = [];
class Element {
  constructor(name) { this.name = name; this.children = []; elements.push(this); }
  append(...children) { this.children.push(...children); }
  createTHead() { const child = new Element('thead'); this.append(child); return child; }
  createTBody() { const child = new Element('tbody'); this.append(child); return child; }
  insertRow() { const child = new Element('tr'); this.append(child); return child; }
  insertCell() { const child = new Element('td'); this.append(child); return child; }
}
context.document = {
  createElement: name => new Element(name),
  createDocumentFragment: () => new Element('fragment'),
  createTextNode: text => ({ textContent: text }),
};
vm.runInNewContext(source.replace(/\}\)\(\);\s*$/, 'window.makeTable = fragmentFor; })();'), context);
context.window.makeTable(parse(standard));
assert.equal(elements.filter(element => element.name === 'table').length, 1);
assert.equal(elements.filter(element => element.name === 'th').length, 3);
assert.equal(elements.filter(element => element.name === 'td').length, 6);
assert.ok(elements.every(element => !('innerHTML' in element)));
console.log('PASS: multiline/flattened tables, blank cells, math pipes, escaped pipes, safe DOM creation, prose preservation.');
