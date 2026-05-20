/**
 * SlimeDeals — Hover Tooltip System
 * Attaches tooltips to any element with data-tooltip attribute.
 */

window.Tooltips = (function() {
    'use strict';

    var _tooltip = null;
    var _showTimeout = null;
    var SHOW_DELAY = 600;

    function init() {
        _tooltip = document.createElement('div');
        _tooltip.className = 'tooltip-popup';
        _tooltip.style.cssText =
            'position:fixed;background:rgba(10,8,22,0.92);backdrop-filter:blur(12px);' +
            'border:1px solid rgba(165,233,1,0.18);' +
            'color:#e2e8f0;font-size:11.5px;font-weight:500;padding:6px 11px;border-radius:8px;' +
            'max-width:280px;pointer-events:none;opacity:0;' +
            'transition:opacity 0.18s ease,transform 0.18s ease;transform:translateY(4px);' +
            'z-index:9999;box-shadow:0 8px 24px rgba(0,0,0,0.45);line-height:1.45;';
        document.body.appendChild(_tooltip);

        document.addEventListener('mouseover', _onMouseOver);
        document.addEventListener('mouseout', _onMouseOut);
    }

    function _onMouseOver(e) {
        var el = e.target.closest('[data-tooltip]');
        if (!el) return;

        var text = el.getAttribute('data-tooltip');
        if (!text) return;

        clearTimeout(_showTimeout);
        _showTimeout = setTimeout(function() {
            _tooltip.textContent = text;
            _tooltip.style.opacity = '1';
            _tooltip.style.transform = 'translateY(0px)';
            _positionTooltip(el);
        }, SHOW_DELAY);
    }

    function _onMouseOut(e) {
        var el = e.target.closest('[data-tooltip]');
        if (!el) return;
        clearTimeout(_showTimeout);
        _tooltip.style.opacity = '0';
        _tooltip.style.transform = 'translateY(4px)';
    }

    function _positionTooltip(el) {
        var rect = el.getBoundingClientRect();
        var tw = _tooltip.offsetWidth;
        var th = _tooltip.offsetHeight;

        var left = rect.left + (rect.width / 2) - (tw / 2);
        var top = rect.bottom + 8;

        // Keep within viewport
        if (left < 8) left = 8;
        if (left + tw > window.innerWidth - 8) left = window.innerWidth - tw - 8;
        if (top + th > window.innerHeight - 8) {
            top = rect.top - th - 8;
        }

        _tooltip.style.left = left + 'px';
        _tooltip.style.top = top + 'px';
    }

    return { init: init };
})();
