(function () {
    'use strict';

    function updateRow(row) {
        if (!row) {
            return;
        }

        var decision = row.querySelector(
            'select.postcodes-review-decision'
        );
        var override = row.querySelector(
            '.postcodes-manual-override'
        );

        if (!decision || !override) {
            return;
        }

        if (decision.value === 'MANUAL_OVERRIDE') {
            override.hidden = false;
        } else {
            override.hidden = true;
        }
    }

    function initialise() {
        document.querySelectorAll(
            'tr.form-row'
        ).forEach(updateRow);
    }

    document.addEventListener('change', function (event) {
        var target = event.target;
        if (
            target &&
            target.matches &&
            target.matches('select.postcodes-review-decision')
        ) {
            updateRow(target.closest('tr.form-row'));
        }
    });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initialise);
    } else {
        initialise();
    }
}());
