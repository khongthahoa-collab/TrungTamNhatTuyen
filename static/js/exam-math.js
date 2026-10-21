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
    loader: { load: ['[tex]/mhchem', '[ui]/safe'] },
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
  const SCRIPT_TOKEN = /([_^])\{([^{}]*)\}/g;
  const SYMBOL_COMMAND = /\\(rightarrow|times|uparrow)\b/g;

  function replaceSymbolCommands(text, inMath) {
    return text.replace(SYMBOL_COMMAND, (match, command) => {
      if (command === 'times') return 'x';
      if (inMath) return match;
      if (command === 'rightarrow') return '→';
      return '↑';
    });
  }

  function renderScriptsInText(textNode) {
    const parts = textNode.nodeValue.split(MATH_SEGMENT);
    if (!parts.some((part, i) => (
      i % 2 === 0
        ? /[_^]\{[^{}]*\}|\\(?:rightarrow|times|uparrow)\b/.test(part)
        : /\\times\b/.test(part)
    ))) return;
    const fragment = document.createDocumentFragment();
    parts.forEach((part, i) => {
      if (i % 2 === 1) {
        fragment.appendChild(document.createTextNode(replaceSymbolCommands(part, true)));
        return;
      }
      part = replaceSymbolCommands(part, false);
      let last = 0;
      part.replace(SCRIPT_TOKEN, (match, kind, content, offset) => {
        fragment.appendChild(document.createTextNode(part.slice(last, offset)));
        const el = document.createElement(kind === '_' ? 'sub' : 'sup');
        el.textContent = content;
        fragment.appendChild(el);
        last = offset + match.length;
        return match;
      });
      fragment.appendChild(document.createTextNode(part.slice(last)));
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
