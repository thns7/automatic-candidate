// Extrai um descritor de cada campo visivel do formulario.
// Marca os elementos com data-ac-idx para o Python poder agir sobre eles depois.
() => {
  const SKIP_TYPES = new Set(['hidden', 'submit', 'button', 'reset', 'image']);
  const text = (node) => (node ? (node.innerText || node.textContent || '') : '')
    .replace(/\s+/g, ' ')
    .replace(/\*$/, '')
    .trim()
    .slice(0, 180);

  const labelFor = (el) => {
    if (el.id) {
      try {
        const lbl = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
        if (lbl && text(lbl)) return text(lbl);
      } catch (e) { /* id invalido para seletor */ }
    }
    const aria = el.getAttribute('aria-label');
    if (aria && aria.trim()) return aria.trim().slice(0, 180);

    const labelledBy = el.getAttribute('aria-labelledby');
    if (labelledBy) {
      const parts = labelledBy.split(/\s+/)
        .map((id) => document.getElementById(id))
        .filter(Boolean)
        .map(text)
        .filter(Boolean);
      if (parts.length) return parts.join(' ').slice(0, 180);
    }

    const wrapping = el.closest('label');
    if (wrapping && text(wrapping)) return text(wrapping);

    // Contêiner de pergunta usado por Greenhouse, Gupy, Workday, Lever...
    const container = el.closest(
      'fieldset, .field, .form-group, .form-field, [class*="field"], [class*="question"], [data-automation-id]'
    );
    if (container) {
      const legend = container.querySelector('legend, label, .label, [class*="label"], h3, h4');
      if (legend && text(legend)) return text(legend);
    }

    let prev = el.previousElementSibling;
    while (prev) {
      const t = text(prev);
      if (t) return t;
      prev = prev.previousElementSibling;
    }
    return el.getAttribute('placeholder') || el.getAttribute('name') || '';
  };

  const kindOf = (el) => {
    const tag = el.tagName.toLowerCase();
    if (tag === 'select') return 'select';
    if (tag === 'textarea') return 'textarea';
    const type = (el.getAttribute('type') || 'text').toLowerCase();
    if (type === 'file') return 'file';
    if (type === 'checkbox') return 'checkbox';
    if (type === 'radio') return 'radio';
    const role = (el.getAttribute('role') || '').toLowerCase();
    if (role === 'combobox' || el.getAttribute('aria-haspopup') === 'listbox') return 'combobox';
    return ['email', 'tel', 'url', 'number', 'date', 'password'].includes(type) ? type : 'text';
  };

  const visible = (el) => {
    const style = window.getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none' || style.opacity === '0') return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };

  const out = [];
  const elements = Array.from(document.querySelectorAll('input, textarea, select'));
  elements.forEach((el, index) => {
    const type = (el.getAttribute('type') || '').toLowerCase();
    if (SKIP_TYPES.has(type)) return;
    if (el.disabled || el.readOnly) return;
    // inputs de arquivo costumam ser invisiveis por design
    if (type !== 'file' && !visible(el)) return;

    el.setAttribute('data-ac-idx', String(index));
    const kind = kindOf(el);
    const record = {
      idx: index,
      kind,
      name: el.getAttribute('name') || el.id || '',
      placeholder: el.getAttribute('placeholder') || '',
      required: el.required || el.getAttribute('aria-required') === 'true',
      label: labelFor(el),
      options: [],
      optionLabel: '',
      groupLabel: '',
      accept: el.getAttribute('accept') || '',
      checked: !!el.checked,
      value: (el.value || '').slice(0, 120),
    };

    if (kind === 'select') {
      record.options = Array.from(el.options)
        .map((o) => (o.textContent || '').trim())
        .filter((t) => t && !/^(selecione|select|choose|escolha|--)/i.test(t));
    }

    if (kind === 'radio') {
      record.optionLabel = record.label;
      const group = el.closest('fieldset, [role="radiogroup"], .field, .form-group, [class*="question"]');
      if (group) {
        const legend = group.querySelector('legend, .label, label:not([for]), h3, h4');
        record.groupLabel = text(legend);
      }
    }
    out.push(record);
  });
  return out;
}
