(function () {
  const actions = document.getElementById('estimate_actions');
  if (!actions) {
    return;
  }

  const saveButton = document.getElementById('save_estimate');
  const printButton = document.getElementById('print_estimate');
  const duplicateButton = document.getElementById('duplicate_estimate');
  const newButton = document.getElementById('new_calculation');
  const csvLink = document.getElementById('export_estimate_csv');
  const xlsxLink = document.getElementById('export_estimate_xlsx');
  const actionStatus = document.getElementById('estimate_action_status');
  let lastCalculationPayload = null;
  let lastCalculationResults = null;
  let savedReference = null;
  let savedUrls = null;

  function setStatus(message, isError) {
    actionStatus.textContent = message || '';
    actionStatus.classList.toggle('error', Boolean(isError));
  }

  function setSavedActionsEnabled(enabled) {
    printButton.disabled = !enabled;
    if (duplicateButton) {
      duplicateButton.disabled = !enabled;
    }
    [csvLink, xlsxLink].filter(Boolean).forEach((link) => {
      link.classList.toggle('estimate-action-disabled', !enabled);
      link.setAttribute('aria-disabled', enabled ? 'false' : 'true');
      if (!enabled) {
        link.removeAttribute('href');
      }
    });
  }

  function markUnsaved() {
    savedReference = null;
    savedUrls = null;
    saveButton.disabled = !lastCalculationResults;
    saveButton.textContent = 'Save estimate';
    setSavedActionsEnabled(false);
  }

  document.addEventListener('freight:calculation-started', () => {
    actions.hidden = true;
    lastCalculationPayload = null;
    lastCalculationResults = null;
    markUnsaved();
  });

  document.addEventListener('freight:calculated', (event) => {
    lastCalculationPayload = event.detail.payload;
    lastCalculationResults = event.detail.results;
    actions.hidden = false;
    setStatus('Calculation completed. Save it before printing or exporting.', false);
    markUnsaved();
  });

  saveButton.addEventListener('click', async () => {
    if (!lastCalculationPayload || !lastCalculationResults) {
      setStatus('Calculate freight before saving an estimate.', true);
      return;
    }

    saveButton.disabled = true;
    setStatus('Verifying and saving the estimate...', false);
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
      const data = await response.json();
      if (!response.ok || data.error) {
        throw new Error(data.error || `Save failed with HTTP ${response.status}`);
      }

      savedReference = data.reference;
      savedUrls = data;
      saveButton.textContent = `Saved ${savedReference}`;
      saveButton.disabled = true;
      printButton.disabled = false;
      if (duplicateButton) {
        duplicateButton.disabled = false;
      }
      if (csvLink) {
        csvLink.href = data.csv_url;
        csvLink.classList.remove('estimate-action-disabled');
        csvLink.setAttribute('aria-disabled', 'false');
      }
      if (xlsxLink) {
        xlsxLink.href = data.xlsx_url;
        xlsxLink.classList.remove('estimate-action-disabled');
        xlsxLink.setAttribute('aria-disabled', 'false');
      }
      setStatus(`${savedReference} saved successfully.`, false);
    } catch (error) {
      saveButton.disabled = false;
      setStatus(error.message, true);
    }
  });

  printButton.addEventListener('click', () => {
    if (savedUrls) {
      window.open(savedUrls.print_url, '_blank', 'noopener');
    }
  });

  if (duplicateButton) {
    duplicateButton.addEventListener('click', () => {
      if (!savedReference) {
        return;
      }
      window.location.href = `/?client=${encodeURIComponent(CURRENT_CLIENT_CODE)}&duplicate=${encodeURIComponent(savedReference)}`;
    });
  }

  newButton.addEventListener('click', () => {
    window.location.href = `/?client=${encodeURIComponent(CURRENT_CLIENT_CODE)}`;
  });

  document.querySelector('.fc-main-column').addEventListener('input', (event) => {
    if (event.target.closest('#estimate_actions')) {
      return;
    }
    if (savedReference) {
      markUnsaved();
      setStatus('The shipment changed. Calculate freight again before saving.', false);
    }
  });

  document.querySelector('.fc-main-column').addEventListener('change', (event) => {
    if (event.target.closest('#estimate_actions')) {
      return;
    }
    if (savedReference) {
      markUnsaved();
      setStatus('The shipment changed. Calculate freight again before saving.', false);
    }
  });

  async function loadDuplicate(reference) {
    setStatus(`Loading ${reference}...`, false);
    try {
      const response = await fetch(`/api/estimates/${encodeURIComponent(reference)}/duplicate/`, {
        credentials: 'same-origin',
      });
      const data = await response.json();
      if (!response.ok || data.error) {
        throw new Error(data.error || `Load failed with HTTP ${response.status}`);
      }
      applyCalculationPayload(data.calculation_payload);
      document.getElementById('calc_status').textContent = `${reference} duplicated. Calculate freight to refresh current rates.`;
      setStatus('', false);
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
    actions.hidden = true;
  }

  const duplicateReference = new URLSearchParams(window.location.search).get('duplicate');
  if (duplicateReference) {
    loadDuplicate(duplicateReference);
  }
}());
