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

  window.typesetExamMath = function (root) {
    const target = root || document.body;
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
