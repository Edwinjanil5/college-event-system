document.addEventListener('DOMContentLoaded', () => {
  const widget = document.querySelector('[data-assistant-widget]');
  if (!widget) return;

  const panel = widget.querySelector('[data-assistant-panel]') || widget.querySelector('.campus-assistant-panel');
  const openers = document.querySelectorAll('[data-assistant-open]');
  const closeButton = widget.querySelector('[data-assistant-close]');
  const resetButton = widget.querySelector('[data-assistant-reset]');
  const form = widget.querySelector('[data-assistant-form]');
  const input = widget.querySelector('[data-assistant-input]');
  const messages = widget.querySelector('[data-assistant-messages]');
  const suggestions = widget.querySelector('[data-assistant-suggestions]');
  const endpoint = widget.dataset.assistantEndpoint || '/assistant/ask';
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';
  let history = [];
  let requestInFlight = false;

  const scrollToLatest = () => {
    messages.scrollTop = messages.scrollHeight;
  };

  const addMessage = (text, role = 'assistant', links = []) => {
    const row = document.createElement('div');
    row.className = `campus-assistant-message ${role}`;

    const avatar = document.createElement('div');
    avatar.className = 'campus-assistant-avatar';
    avatar.setAttribute('aria-hidden', 'true');
    avatar.textContent = role === 'user' ? 'You' : '✦';

    const bubble = document.createElement('div');
    bubble.className = 'campus-assistant-bubble';
    bubble.textContent = text;

    if (Array.isArray(links) && links.length) {
      const link = document.createElement('a');
      const selected = links[0];
      link.href = selected.url;
      link.textContent = selected.label || 'Open page';
      link.className = 'campus-assistant-link';
      bubble.append(document.createElement('br'), link);
    }

    row.append(avatar, bubble);
    messages.appendChild(row);
    scrollToLatest();
  };

  const setSuggestions = (items) => {
    suggestions.replaceChildren();
    const safeItems = Array.isArray(items) ? items.slice(0, 4) : [];
    safeItems.forEach((item) => {
      if (!item || !item.url || !item.label) return;
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.assistantQuestion = item.label;
      button.textContent = item.label;
      button.addEventListener('click', () => ask(item.label));
      suggestions.appendChild(button);
    });
  };

  const setOpen = (open) => {
    panel.hidden = !open;
    openers.forEach((opener) => opener.setAttribute('aria-expanded', String(open)));
    if (open) {
      window.setTimeout(() => input.focus(), 0);
    }
  };

  const addTyping = () => {
    const row = document.createElement('div');
    row.className = 'campus-assistant-message assistant typing';
    row.dataset.assistantTyping = 'true';
    const avatar = document.createElement('div');
    avatar.className = 'campus-assistant-avatar';
    avatar.setAttribute('aria-hidden', 'true');
    avatar.textContent = '✦';
    const bubble = document.createElement('div');
    bubble.className = 'campus-assistant-bubble';
    bubble.textContent = 'Finding the right CampusPulse answer…';
    row.append(avatar, bubble);
    messages.appendChild(row);
    scrollToLatest();
  };

  const removeTyping = () => {
    widget.querySelector('[data-assistant-typing]')?.remove();
  };

  const renderWelcome = () => {
    messages.replaceChildren();
    addMessage('Hello! I can help you navigate CampusPulse. Ask about accounts, events, registrations, feedback, PA points, reports, or a problem you are facing.');
    setSuggestions([
      { label: 'Create an account', url: '/register' },
      { label: 'Register for an event', url: '/login' },
      { label: 'PA points', url: '/how-to-use' },
      { label: 'Find an event', url: '/login' },
    ]);
  };

  const ask = async (question) => {
    const trimmed = String(question || '').trim();
    if (!trimmed || requestInFlight) return;

    requestInFlight = true;
    input.disabled = true;
    addMessage(trimmed, 'user');
    history.push({ role: 'user', content: trimmed });
    history = history.slice(-6);
    addTyping();

    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        body: JSON.stringify({
          message: trimmed,
          history,
          page: window.location.pathname,
        }),
      });
      const payload = await response.json().catch(() => ({}));
      removeTyping();
      if (!response.ok) {
        throw new Error(payload.error || 'The assistant is temporarily unavailable.');
      }
      addMessage(payload.answer || 'I could not find an answer to that question.', 'assistant', payload.suggestions);
      setSuggestions(payload.suggestions);
    } catch (error) {
      removeTyping();
      addMessage(error.message || 'The assistant is temporarily unavailable. Please try again.', 'assistant');
    } finally {
      requestInFlight = false;
      input.disabled = false;
      input.focus();
    }
  };

  openers.forEach((opener) => opener.addEventListener('click', () => setOpen(true)));
  closeButton?.addEventListener('click', () => {
    setOpen(false);
    widget.querySelector('[data-assistant-open]')?.focus();
  });
  resetButton?.addEventListener('click', () => {
    history = [];
    renderWelcome();
    input.focus();
  });
  form?.addEventListener('submit', (event) => {
    event.preventDefault();
    const question = input.value;
    input.value = '';
    ask(question);
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !panel.hidden) {
      setOpen(false);
      widget.querySelector('[data-assistant-open]')?.focus();
    }
  });

  renderWelcome();
});
