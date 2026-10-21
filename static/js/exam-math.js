(function () {
  let typesetQueue = Promise.resolve();
  const scheduledTypesets = new WeakMap();
  let resolveReady;
  let rejectReady;
  const mathJaxReady = new Promise((resolve, reject) => {
    resolveReady = resolve;
    rejectReady = reject;
  });

  window.MathJax = {
    loader: {
      paths: {
        mathjax: 'https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5',
        ui: '[mathjax]/ui',
      },
      load: ['[tex]/mhchem', '[ui]/safe'],
    },
    tex: {
      inlineMath: [['\\(', '\\)'], ['$', '$']],
      displayMath: [['\\[', '\\]'], ['$$', '$$']],
      packages: { '[+]': ['mhchem'] },
      processEscapes: true,
    },
    options: {
      skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code'],
      safeOptions: {
        allow: { URLs: 'safe', classes: 'safe', cssIDs: 'safe', styles: 'safe' },
        safeProtocols: { http: true, https: true, file: false, javascript: false, data: false },
      },
    },
    startup: { typeset: false },
  };

  const script = document.createElement('script');
  script.src = 'https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-chtml.js';
  script.async = true;
  script.onload = () => {
    window.MathJax.startup.promise.then(resolveReady, rejectReady);
  };
  script.onerror = () => rejectReady(new Error('Không tải được bộ hiển thị công thức toán/hóa.'));
  document.head.appendChild(script);

  // Plain-text shorthand outside math delimiters: CO_{2} -> CO<sub>2</sub>,
  // x^{2} -> x<sup>2</sup>. TeX commands inside math remain with MathJax except \times.
  const MATH_SEGMENT = /(\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|\$[^$]*\$)/;
  const SYMBOL_COMMAND = /\\(rightarrow|times|uparrow|downarrow)\b/g;

  function replaceSymbolCommands(text, inMath) {
    return text.replace(SYMBOL_COMMAND, (match, command) => {
      if (command === 'times') return 'x';
      if (inMath) return match;
      if (command === 'rightarrow') return '→';
      return command === 'uparrow' ? '↑' : '↓';
    });
  }

  function readBracedGroup(text, start) {
    if (text[start] !== '{') return null;
    let depth = 1;
    for (let i = start + 1; i < text.length; i += 1) {
      if (text[i] === '\\') {
        i += 1;
      } else if (text[i] === '{') {
        depth += 1;
      } else if (text[i] === '}') {
        depth -= 1;
        if (depth === 0) return { content: text.slice(start + 1, i), end: i + 1 };
      }
    }
    return null;
  }

  function appendPlainText(fragment, text) {
    let plainText = '';
    const flushText = () => {
      if (!plainText) return;
      fragment.appendChild(document.createTextNode(plainText));
      plainText = '';
    };

    for (let i = 0; i < text.length;) {
      if (text.startsWith('\\frac', i)) {
        const numerator = readBracedGroup(text, i + 5);
        const denominator = numerator && readBracedGroup(text, numerator.end);
        if (numerator && denominator) {
          flushText();
          fragment.appendChild(document.createTextNode(
            `\\(\\frac{${numerator.content}}{${denominator.content}}\\)`,
          ));
          i = denominator.end;
          continue;
        }
      }

      if (text.startsWith('\\text', i)) {
        const group = readBracedGroup(text, i + 5);
        if (group) {
          flushText();
          fragment.appendChild(document.createTextNode(group.content));
          i = group.end;
          continue;
        }
      }

      if ((text[i] === '_' || text[i] === '^') && text[i + 1] === '{') {
        const group = readBracedGroup(text, i + 1);
        if (group) {
          flushText();
          const element = document.createElement(text[i] === '_' ? 'sub' : 'sup');
          appendPlainText(element, group.content);
          fragment.appendChild(element);
          i = group.end;
          continue;
        }
      }

      const symbol = text.slice(i).match(/^\\(?:rightarrow|times|uparrow|downarrow)\b/);
      if (symbol) {
        plainText += replaceSymbolCommands(symbol[0], false);
        i += symbol[0].length;
        continue;
      }

      plainText += text[i];
      i += 1;
    }
    flushText();
  }

  function renderPlainText(text) {
    const fragment = document.createDocumentFragment();
    appendPlainText(fragment, text);
    return fragment;
  }

  function shouldRenderPlainText(parts) {
    return parts.some((part, i) => (
      i % 2 === 0
        ? /(?:\\(?:frac|text|rightarrow|times|uparrow|downarrow)\b|[_^]\{)/.test(part)
        : /\\times\b/.test(part)
    ));
  }

  function renderScriptsInText(textNode) {
    const parts = textNode.nodeValue.split(MATH_SEGMENT);
    if (!shouldRenderPlainText(parts)) return;
    const fragment = document.createDocumentFragment();
    parts.forEach((part, i) => {
      if (i % 2 === 1) {
        fragment.appendChild(document.createTextNode(replaceSymbolCommands(part, true)));
      } else {
        fragment.appendChild(renderPlainText(replaceSymbolCommands(part, false)));
      }
    });
    textNode.parentNode.replaceChild(fragment, textNode);
  }

  function renderPlainScripts(root) {
    const containers = root.matches && root.matches('.exam-math')
      ? [root] : Array.from(root.querySelectorAll('.exam-math'));
    containers.forEach(container => {
      const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, {
        acceptNode: node => (node.parentElement.closest('textarea, script, style, code, mjx-container')
          ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
      });
      const nodes = [];
      while (walker.nextNode()) nodes.push(walker.currentNode);
      nodes.forEach(renderScriptsInText);
    });
  }

  window.typesetExamMath = function (root) {
    const target = root || document.body;
    renderPlainScripts(target);
    typesetQueue = typesetQueue.then(async () => {
      await mathJaxReady;
      window.MathJax.typesetClear([target]);
      await window.MathJax.typesetPromise([target]);
    }).catch(error => {
      console.error('Không thể hiển thị công thức trong đề thi.', error);
    });
    return typesetQueue;
  };

  window.scheduleExamMathTypeset = function (root, delay = 180) {
    const target = root || document.body;
    const timer = scheduledTypesets.get(target);
    if (timer) window.clearTimeout(timer);
    scheduledTypesets.set(target, window.setTimeout(() => {
      scheduledTypesets.delete(target);
      window.typesetExamMath(target);
    }, delay));
  };

  document.addEventListener('DOMContentLoaded', () => window.typesetExamMath());
})();
