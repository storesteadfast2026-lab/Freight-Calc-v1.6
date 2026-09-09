(function () {
  const form = document.getElementById('estimate-email-form');
  if (!form) {
    return;
  }

  const selectors = Array.from(form.querySelectorAll('.estimate-selector'));
  const selectAll = document.getElementById('select-all-estimates');
  const sendButton = document.getElementById('email-selected');
  const recipientSelect = document.getElementById('estimate-recipient');
  const customerRecipient = document.getElementById('customer-recipient');
  const selectionCount = document.getElementById('estimate-selection-count');
  const optionsElement = document.getElementById('estimate-recipient-options');
  const recipientOptions = optionsElement ? JSON.parse(optionsElement.textContent) : {};
  const emailEnabled = Boolean(window.ESTIMATE_EMAIL_ENABLED);
  const maxSelection = Number(window.ESTIMATE_EMAIL_MAX_SELECTION) || 20;

  function selectedSelectors() {
    return selectors.filter((selector) => selector.checked);
  }

  function selectedClient() {
    const selected = selectedSelectors();
    return selected.length ? selected[0].dataset.client : '';
  }

  function populateRecipients(clientCode) {
    if (!recipientSelect) {
      return;
    }
    const previousValue = recipientSelect.value;
    const options = recipientOptions[clientCode] || [];
    recipientSelect.innerHTML = '';
    const prompt = document.createElement('option');
    prompt.value = '';
    prompt.textContent = options.length ? 'Select customer email' : 'No registered customer email';
    recipientSelect.appendChild(prompt);
    options.forEach((option) => {
      const element = document.createElement('option');
      element.value = option.email;
      element.textContent = option.label;
      recipientSelect.appendChild(element);
    });
    if (options.some((option) => option.email === previousValue)) {
      recipientSelect.value = previousValue;
    } else if (options.length === 1) {
      recipientSelect.value = options[0].email;
    }
    recipientSelect.disabled = !clientCode || options.length === 0;
  }

  function updateState() {
    const selected = selectedSelectors();
    const clientCode = selectedClient();
    selectors.forEach((selector) => {
      selector.disabled = Boolean(clientCode) && selector.dataset.client !== clientCode;
    });

    populateRecipients(clientCode);
    const recipientAvailable = recipientSelect
      ? Boolean(recipientSelect.value)
      : Boolean(customerRecipient && customerRecipient.textContent.trim() !== 'No registered email');
    sendButton.disabled = !emailEnabled
      || selected.length === 0
      || selected.length > maxSelection
      || !recipientAvailable;
    selectionCount.textContent = `${selected.length} selected`;

    const enabledSelectors = selectors.filter((selector) => !selector.disabled);
    if (selectAll) {
      selectAll.checked = enabledSelectors.length > 0
        && enabledSelectors.every((selector) => selector.checked);
      selectAll.indeterminate = selected.length > 0 && !selectAll.checked;
    }
  }

  selectors.forEach((selector) => selector.addEventListener('change', updateState));
  if (recipientSelect) {
    recipientSelect.addEventListener('change', () => {
      const selected = selectedSelectors();
      sendButton.disabled = !emailEnabled
        || selected.length === 0
        || selected.length > maxSelection
        || !recipientSelect.value;
    });
  }
  if (selectAll) {
    selectAll.addEventListener('change', () => {
      let clientCode = selectedClient();
      if (!clientCode && selectors.length) {
        clientCode = selectors[0].dataset.client;
      }
      selectors.forEach((selector) => {
        if (selector.dataset.client === clientCode) {
          selector.checked = selectAll.checked;
        }
      });
      updateState();
    });
  }
  form.addEventListener('submit', () => {
    sendButton.disabled = true;
    sendButton.textContent = 'Sending...';
  });

  updateState();
}());
