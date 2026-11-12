'use strict';

/*
 * Google inside the player, where the network blocks the app from searching
 * YouTube (NetFree): a bar drawn here — back to the player, the query, back
 * and forward in the search — and under it the page itself, which
 * electron/main.js lays over this view's frame. A click on a YouTube result
 * comes back as a link to the view the search started from (results.js).
 * Esc, inside the page or here, goes back to the player.
 */
(function () {
  const { h, icon, api } = H;
  const root = H.$('#view-websearch');
  let frame = null;
  let input = null;
  let nav = null;
  let from = null; // { view, holder }: where the search started

  function rect() {
    const r = frame.getBoundingClientRect();
    return { x: r.left, y: r.top, width: r.width, height: r.height };
  }

  const place = () => { if (!root.hidden && frame) api.searchPlace(rect()); };
  const observer = new ResizeObserver(place);
  window.addEventListener('resize', place);

  function draw(query) {
    input = h('input', {
      class: 'websearch-input', type: 'search', value: query || '', dir: 'auto',
      'aria-label': 'מה לחפש בגוגל', autocomplete: 'off', spellcheck: 'false',
    });
    const form = h('form', {
      class: 'websearch-form', role: 'search',
      onsubmit: (e) => { e.preventDefault(); if (input.value.trim()) open(input.value.trim()); },
    }, input, h('button', { class: 'btn btn-primary btn-sm', type: 'submit' }, icon('search', 'icon-sm'), 'חיפוש'));
    nav = {
      back: h('button', { class: 'icon-btn', type: 'button', disabled: true, 'aria-label': 'אחורה בחיפוש', title: 'אחורה', onclick: () => api.searchNav('back') }, icon('chevron-right')),
      forward: h('button', { class: 'icon-btn', type: 'button', disabled: true, 'aria-label': 'קדימה בחיפוש', title: 'קדימה', onclick: () => api.searchNav('forward') }, icon('chevron-left')),
      reload: h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'לטעון שוב', title: 'לטעון שוב', onclick: () => api.searchNav('reload') }, icon('refresh-cw')),
    };
    frame = h('div', { class: 'websearch-frame is-loading' },
      h('div', { class: 'websearch-loading' }, icon('loader-circle', 'spin'), 'טוען את גוגל…'));
    H.clear(root).append(
      h('div', { class: 'websearch-bar' },
        h('button', { class: 'btn btn-quiet', type: 'button', onclick: () => H.closeWebSearch() }, icon('undo-2'), 'חזרה למנגן'),
        form,
        h('div', { class: 'websearch-nav' }, nav.back, nav.forward, nav.reload)),
      h('p', { class: 'websearch-hint' },
        'גוגל, בתוך המנגן. לוחצים על תוצאה מיוטיוב, והשיר עובר למנגן: לשמוע בלי לשמור, או להוריד. Esc חוזר למנגן.'),
      frame);
    observer.disconnect();
    observer.observe(frame);
  }

  function open(query) {
    // After the layout, so that the frame has its size.
    requestAnimationFrame(() => api.searchOpen(query, rect()));
  }

  function show(params = {}) {
    if (params.from) from = params.from;
    draw(params.query);
    open(params.query || '');
  }

  api.on('search-state', (state) => {
    if (!nav) return;
    nav.back.disabled = !state.canGoBack;
    nav.forward.disabled = !state.canGoForward;
    frame.classList.toggle('is-loading', !!state.loading);
  });
  api.on('search-closed', () => { if (!root.hidden) H.closeWebSearch(); });   // Esc inside the page
  root.addEventListener('keydown', (e) => { if (e.key === 'Escape') H.closeWebSearch(); });

  /** Back to where the search started, as it was left. */
  H.closeWebSearch = function closeWebSearch() {
    api.searchHide();
    if (from && from.view) H.reveal(from.view);
    else H.go('home');
  };
  /** Where the current search started ({ view, holder }), or null. */
  H.webSearchFrom = () => from;

  H.views = H.views || {};
  H.views.websearch = { show };
})();
