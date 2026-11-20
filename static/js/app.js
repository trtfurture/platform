(() => {
  const stripArrows = (node) => {
    const blocked = new Set(['SCRIPT','STYLE','TEXTAREA','INPUT','NOSCRIPT']);
    const clean = (root) => {
      if (!root || (root.nodeType === 1 && blocked.has(root.tagName))) return;
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      const nodes = []; while (walker.nextNode()) nodes.push(walker.currentNode);
      for (const textNode of nodes) { if (textNode.parentElement && textNode.parentElement.closest('script,style,textarea,input,noscript')) continue; const cleaned = textNode.nodeValue.replace(/[↗→←➜➔⟶➝➞⇢⇨➤]/g, ''); if (cleaned !== textNode.nodeValue) textNode.nodeValue = cleaned; }
    };
    clean(node);
  };
  stripArrows(document.body);
  const arrowObserver = new MutationObserver((records) => records.forEach((record) => {
    if (record.type === 'characterData' && record.target && record.target.nodeValue) { const cleaned = record.target.nodeValue.replace(/[↗→←➜➔⟶➝➞⇢⇨➤]/g, ''); if (cleaned !== record.target.nodeValue) record.target.nodeValue = cleaned; }
    record.addedNodes.forEach((node) => { if (node.nodeType === 3) { const cleaned = node.nodeValue.replace(/[↗→←➜➔⟶➝➞⇢⇨➤]/g, ''); if (cleaned !== node.nodeValue) node.nodeValue = cleaned; } else stripArrows(node); });
  }));
  arrowObserver.observe(document.body, { childList: true, subtree: true, characterData: true });
  const toggle = document.querySelector('.nav-toggle');
  const nav = document.querySelector('.main-nav');
  if (toggle && nav) {
    toggle.addEventListener('click', () => {
      const open = nav.classList.toggle('is-open');
      toggle.setAttribute('aria-expanded', String(open));
      toggle.textContent = open ? '×' : '☰';
    });
  }
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => navigator.serviceWorker.register('/service-worker.js').catch(() => {}));
  }
})();
