(function () {
  const mathPattern = /(\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|\$[^$\n]*\$)/g;
  const separator = /^\s*:?-{3,}:?\s*$/;

  function splitCells(value) {
    const cells = [];
    const math = [];
    let start = 0;
    const protectedText = value.replace(mathPattern, match => {
      math.push(match);
      return `\u0000${math.length - 1}\u0000`;
    }).replace(/\\r\\n|\\n(?=\s|\||$)/g, '\n');
    for (let i = 0; i < protectedText.length; i += 1) {
      if (protectedText[i] !== '|') continue;
      let slashes = 0;
      for (let j = i - 1; j >= 0 && protectedText[j] === '\\'; j -= 1) slashes += 1;
      if (slashes % 2) continue;
      cells.push({ text: protectedText.slice(start, i), start, end: i });
      start = i + 1;
    }
    cells.push({ text: protectedText.slice(start), start, end: protectedText.length });
    const restore = text => text.replace(/\u0000(\d+)\u0000/g, (_, index) => math[Number(index)])
      .replace(/\\\|/g, '|');
    return { cells, restore, protectedText };
  }

  function parse(value) {
    const { cells, restore, protectedText } = splitCells(value);
    const parts = [];
    let consumed = 0;
    for (let i = 1; i < cells.length - 1; i += 1) {
      if (!separator.test(cells[i].text)) continue;
      let end = i;
      while (end < cells.length && separator.test(cells[end].text)) end += 1;
      const width = end - i;
      const boundary = cells[i - 1].text.trim() === '';
      const headerStart = i - width - (boundary ? 1 : 0);
      if (headerStart < 1 || cells[headerStart].start - 1 < consumed || width < 2) continue;
      const headers = cells.slice(headerStart, headerStart + width);
      if (headers.some(cell => !cell.text.trim())) continue;
      const rows = [];
      let cursor = end;
      // A closing pipe followed by an opening pipe separates rows, even after copy/paste.
      while (cursor < cells.length - 1) {
        if (cells[cursor].text.trim() === '') cursor += 1;
        const row = cells.slice(cursor, cursor + width);
        if (row.length !== width || cursor + width >= cells.length) break;
        if (row.some(cell => /\n\s*\n/.test(cell.text))) break;
        rows.push(row.map(cell => restore(cell.text.trim())));
        cursor += width;
        if (cells[cursor].text.trim() !== '') break;
      }
      if (!rows.length) continue;
      const tableStart = cells[headerStart].start - 1;
      const tableEnd = cells[cursor - 1].end + 1;
      parts.push({ text: restore(protectedText.slice(consumed, tableStart)) });
      parts.push({ headers: headers.map(cell => restore(cell.text.trim())), rows });
      consumed = tableEnd;
      i = cursor - 1;
    }
    if (!parts.length) return null;
    parts.push({ text: restore(protectedText.slice(consumed)) });
    return parts;
  }

  function fragmentFor(parts) {
    const fragment = document.createDocumentFragment();
    parts.forEach(part => {
      if ('text' in part) {
        fragment.append(document.createTextNode(part.text));
        return;
      }
      const wrapper = document.createElement('span');
      wrapper.className = 'exam-table-wrap';
      const table = document.createElement('table');
      table.className = 'exam-content-table';
      const head = table.createTHead().insertRow();
      part.headers.forEach(label => {
        const cell = document.createElement('th');
        cell.scope = 'col';
        cell.textContent = label;
        head.append(cell);
      });
      const body = table.createTBody();
      part.rows.forEach(values => {
        const row = body.insertRow();
        values.forEach(value => { row.insertCell().textContent = value; });
      });
      wrapper.append(table);
      fragment.append(wrapper);
    });
    return fragment;
  }

  window.renderExamTables = function (root) {
    const containers = root.matches?.('.exam-math') ? [root] : root.querySelectorAll('.exam-math');
    containers.forEach(container => {
      const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, {
        acceptNode: node => node.parentElement.closest('table, textarea, pre, code, script, style, mjx-container')
          ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
      });
      const nodes = [];
      while (walker.nextNode()) nodes.push(walker.currentNode);
      nodes.forEach(node => {
        if (!node.isConnected) return;
        const run = [node];
        let next = node.nextSibling;
        while (next && (next.nodeType === Node.TEXT_NODE || next.nodeName === 'BR')) {
          run.push(next);
          next = next.nextSibling;
        }
        const value = run.map(item => item.nodeName === 'BR' ? '\n' : item.textContent).join('');
        const parts = parse(value);
        if (!parts) return;
        node.before(fragmentFor(parts));
        run.forEach(item => item.remove());
      });
    });
  };
})();
