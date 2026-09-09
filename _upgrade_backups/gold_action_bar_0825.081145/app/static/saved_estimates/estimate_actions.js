(function () {
  const actions = document.getElementById('estimate_actions');
  if (!actions) {
    return;
  }

  const saveButton = document.getElementById('save_estimate');
  const printButton = document.getElementById('print_estimate');
  const newButton = document.getElementById('new_calculation');
  const actionStatus = document.getElementById('estimate_action_status');
  let lastCalculationPayload = null;
  let lastCalculationResults = null;
  let savedReference = null;
  let savedUrls = null;

  function setStatus(message, state) {
    actionStatus.textContent = message || '';
    actionStatus.classList.toggle('error', state === 'error');
    actionStatus.classList.toggle('success', state === 'success');
  }

  async function readJsonResponse(response, actionLabel) {
    const contentType = response.headers.get('content-type') || '';
    if (!contentType.includes('application/json')) {
      await response.text();
      throw new Error(`${actionLabel} failed with HTTP ${response.status}. The server returned an unexpected response.`);
    }
    try {
      return await response.json();
    } catch (error) {
      throw new Error(`${actionLabel} failed because the server response was not valid JSON.`);
    }
  }

  function markUnsaved() {
    savedReference = null;
    savedUrls = null;
    saveButton.disabled = !lastCalculationResults;
    saveButton.textContent = 'Save estimate';
    saveButton.classList.remove('estimate-action-saved');
  }

  document.addEventListener('freight:calculation-started', () => {
    lastCalculationPayload = null;
    lastCalculationResults = null;
    markUnsaved();
    setStatus('', 'neutral');
  });

  document.addEventListener('freight:calculated', (event) => {
    lastCalculationPayload = event.detail.payload;
    lastCalculationResults = event.detail.results;
    setStatus('Calculation completed. Save it to print the current estimate.', 'neutral');
    markUnsaved();
  });

  saveButton.addEventListener('click', async () => {
    if (!lastCalculationPayload || !lastCalculationResults) {
      setStatus('Calculate freight before saving an estimate.', 'error');
      return;
    }

    saveButton.disabled = true;
    setStatus('Verifying and saving the estimate...', 'neutral');
    try {
      const response = await fetch('/api/estimates/save/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCookie('csrftoken'),
        },
        credentials: 'same-origin',
        body: JSON.stringify({
          calculation_payload: lastCalculationPayload,
          displayed_results: lastCalculationResults,
        }),
      });
      const data = await readJsonResponse(response, 'Save');
      if (!response.ok || data.error) {
        throw new Error(data.error || `Save failed with HTTP ${response.status}`);
      }

      savedReference = data.reference;
      savedUrls = data;
      saveButton.textContent = 'Save estimate';
      saveButton.disabled = true;
      saveButton.classList.add('estimate-action-saved');
      setStatus(`${savedReference} saved successfully.`, 'success');
    } catch (error) {
      saveButton.disabled = false;
      setStatus(error.message, 'error');
    }
  });

  printButton.addEventListener('click', () => {
    if (savedUrls) {
      window.open(savedUrls.print_url, '_blank', 'noopener');
      return;
    }
    window.location.href = `/estimates/?client=${encodeURIComponent(CURRENT_CLIENT_CODE)}`;
  });

  newButton.addEventListener('click', () => {
    window.location.href = `/?client=${encodeURIComponent(CURRENT_CLIENT_CODE)}`;
  });

  document.querySelector('.fc-main-column').addEventListener('input', (event) => {
    if (event.target.closest('#estimate_actions')) {
      return;
    }
    if (lastCalculationResults || savedReference) {
      lastCalculationPayload = null;
      lastCalculationResults = null;
      markUnsaved();
      setStatus('The shipment changed. Calculate freight again before saving.', 'neutral');
    }
  });

  document.querySelector('.fc-main-column').addEventListener('change', (event) => {
    if (event.target.closest('#estimate_actions')) {
      return;
    }
    if (lastCalculationResults || savedReference) {
      lastCalculationPayload = null;
      lastCalculationResults = null;
      markUnsaved();
      setStatus('The shipment changed. Calculate freight again before saving.', 'neutral');
    }
  });

  async function loadDuplicate(reference) {
    setStatus(`Loading ${reference}...`, 'neutral');
    try {
      const response = await fetch(`/api/estimates/${encodeURIComponent(reference)}/duplicate/`, {
        credentials: 'same-origin',
      });
      const data = await readJsonResponse(response, 'Load');
      if (!response.ok || data.error) {
        throw new Error(data.error || `Load failed with HTTP ${response.status}`);
      }
      applyCalculationPayload(data.calculation_payload);
      document.getElementById('calc_status').textContent = `${reference} duplicated. Calculate freight to refresh current rates.`;
      setStatus('', 'neutral');
    } catch (error) {
      document.getElementById('error').textContent = error.message;
    }
  }

  function applyCalculationPayload(payload) {
    document.getElementById('from_address_id').value = payload.from_address_id || '';
    destinationSuburbInput.value = payload.suburb || '';
    destinationStateInput.value = payload.state || '';
    destinationPostcodeInput.value = payload.postcode || '';
    selectedSuburbLabel = [
      payload.suburb,
      [payload.state, payload.postcode].filter(Boolean).join(' '),
    ].filter(Boolean).join(', ');
    suburbInput.value = selectedSuburbLabel;
    document.getElementById('tailgate').value = payload.tailgate || 'NO';
    document.getElementById('preselect_sku').value = payload.preselect_sku || 'YES';
    document.getElementById('cubic_margin_percent').value = payload.cubic_margin_percent || '0';

    const tbody = document.querySelector('#lines tbody');
    tbody.innerHTML = '';
    (payload.lines || []).forEach((line) => {
      addLine();
      const row = tbody.lastElementChild;
      row.querySelector('.sku').value = line.sku || '';
      row.querySelector('.qty').value = line.quantity || '0';
      row.querySelector('.ftype').value = line.freight_type || 'P';
      row.querySelector('.len').value = line.length_m || '0.00';
      row.querySelector('.wid').value = line.width_m || '0.00';
      row.querySelector('.hei').value = line.height_m || '0.00';
      row.querySelector('.weight').value = line.weight_kg || '0.00';
      row.querySelector('.cubic').value = line.cubic_m3 || '0.000';
    });
    if (!tbody.children.length) {
      addLine();
    }
    updateProductTotals();
    markUnsaved();
  }

  const duplicateReference = new URLSearchParams(window.location.search).get('duplicate');
  if (duplicateReference) {
    loadDuplicate(duplicateReference);
  }
}());
