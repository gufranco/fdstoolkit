export function element(tag, properties) {
  return Object.assign(document.createElement(tag), properties);
}

export function banner(kind, message) {
  return element('p', { className: `banner ${kind}`, textContent: message });
}

